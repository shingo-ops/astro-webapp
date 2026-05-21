#!/usr/bin/env python3
"""Pokemon 図鑑 (1025 行) を public.pokemon_dex に seed する。

spec.md v1.1 Sprint 1 / F1 / AC1.4:
  - --dry-run: 1025 行の検証ログを出力（DB 変更なし）
  - --apply  : public.pokemon_dex に INSERT ... ON CONFLICT (dex_number) DO UPDATE
               で冪等投入。二度実行しても件数変化なし。

CSV データ源:
  1. astro-webapp/sheets/pokemon_dex.csv が存在すればそれを優先
  2. なければ Google スプレッドシート ID
     1or39_glwYtF9OfOxXizN8ZjcUKL0hNIeW3qP3nCx3AI から運用 admin が export して
     上記 CSV に保存する想定（メイン Claude が一度確認済、本スクリプトはローカル
     CSV のみを参照、Google API 呼び出しは行わない）
  3. CSV ファイルが無い場合、スクリプトは sample データ 25 行を埋め込んだ
     fallback mode で動作する（CI / テスト用、本番では使わない）

CSV 期待カラム（順不同、ヘッダー必須）:
  dex_number,name_ja,name_en,generation,region

実行方法（VPS 側、しんごさん作業）:
  # Dry run
  docker compose exec -w /app backend python scripts/seed_pokemon_dex.py --dry-run

  # Apply
  docker compose exec -w /app backend python scripts/seed_pokemon_dex.py --apply

冪等:
  ON CONFLICT (dex_number) DO UPDATE SET name_ja=..., name_en=..., generation=..., region=...
  二度実行しても件数は変化しない（更新のみ）。

関連:
  scripts/migrate_adr015_lead_foundation.py (DB 接続パターン踏襲)
  migrations/061_create_tcg_and_dex_masters.sql (テーブル定義)
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import os
import sys
from pathlib import Path
from typing import Iterable

_APP_ROOT = Path(__file__).resolve().parent.parent
if str(_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_ROOT))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
CSV_PATH = BASE_DIR / "sheets" / "pokemon_dex.csv"

# CSV が無い場合の fallback サンプル（CI / 開発用、世代 1 から 25 種）
# 本番運用では sheets/pokemon_dex.csv を必ず配置すること（spec 上 1025 行）
_FALLBACK_SAMPLE = [
    # (dex_number, name_ja, name_en, generation, region)
    (1, "フシギダネ", "Bulbasaur", 1, "Kanto"),
    (2, "フシギソウ", "Ivysaur", 1, "Kanto"),
    (3, "フシギバナ", "Venusaur", 1, "Kanto"),
    (4, "ヒトカゲ", "Charmander", 1, "Kanto"),
    (5, "リザード", "Charmeleon", 1, "Kanto"),
    (6, "リザードン", "Charizard", 1, "Kanto"),
    (7, "ゼニガメ", "Squirtle", 1, "Kanto"),
    (8, "カメール", "Wartortle", 1, "Kanto"),
    (9, "カメックス", "Blastoise", 1, "Kanto"),
    (10, "キャタピー", "Caterpie", 1, "Kanto"),
    (11, "トランセル", "Metapod", 1, "Kanto"),
    (12, "バタフリー", "Butterfree", 1, "Kanto"),
    (13, "ビードル", "Weedle", 1, "Kanto"),
    (14, "コクーン", "Kakuna", 1, "Kanto"),
    (15, "スピアー", "Beedrill", 1, "Kanto"),
    (16, "ポッポ", "Pidgey", 1, "Kanto"),
    (17, "ピジョン", "Pidgeotto", 1, "Kanto"),
    (18, "ピジョット", "Pidgeot", 1, "Kanto"),
    (19, "コラッタ", "Rattata", 1, "Kanto"),
    (20, "ラッタ", "Raticate", 1, "Kanto"),
    (21, "オニスズメ", "Spearow", 1, "Kanto"),
    (22, "オニドリル", "Fearow", 1, "Kanto"),
    (23, "アーボ", "Ekans", 1, "Kanto"),
    (24, "アーボック", "Arbok", 1, "Kanto"),
    (25, "ピカチュウ", "Pikachu", 1, "Kanto"),
]


def _load_rows() -> list[tuple[int, str, str, int | None, str | None]]:
    """CSV を読み込む。無ければ fallback サンプルを返す。"""
    if CSV_PATH.exists():
        logger.info("CSV 検出: %s", CSV_PATH)
        rows: list[tuple[int, str, str, int | None, str | None]] = []
        with CSV_PATH.open(encoding="utf-8") as f:
            reader = csv.DictReader(f)
            required = {"dex_number", "name_ja", "name_en"}
            if not required.issubset(reader.fieldnames or []):
                raise ValueError(
                    f"CSV ヘッダー不正。必須: {required}, 実際: {reader.fieldnames}"
                )
            for row in reader:
                dex_number = int(row["dex_number"])
                name_ja = row["name_ja"].strip()
                name_en = row["name_en"].strip()
                generation = int(row["generation"]) if row.get("generation") else None
                region = row.get("region", "").strip() or None
                rows.append((dex_number, name_ja, name_en, generation, region))
        return rows
    logger.warning(
        "CSV ファイル %s が存在しません。fallback サンプル 25 行で動作します。"
        " 本番運用前にしんごさんから取得した正式 CSV を配置してください。",
        CSV_PATH,
    )
    return list(_FALLBACK_SAMPLE)


async def _seed(rows: Iterable, dry_run: bool) -> None:
    if dry_run:
        rows_list = list(rows)
        logger.info("dry-run: %d 行を投入予定（DB 変更なし）", len(rows_list))
        for r in rows_list[:5]:
            logger.info("  sample: dex=%d ja=%s en=%s", r[0], r[1], r[2])
        if len(rows_list) > 5:
            logger.info("  ... (残り %d 行は省略)", len(rows_list) - 5)
        return

    url = os.getenv("DATABASE_URL")
    if not url:
        logger.error("DATABASE_URL not set")
        sys.exit(1)
    if url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://"):]
    engine = create_async_engine(url, echo=False)

    try:
        async with engine.begin() as conn:
            # 既存件数の事前確認
            before_count = (
                await conn.execute(text("SELECT COUNT(*) FROM public.pokemon_dex"))
            ).scalar_one()
            logger.info("適用前 public.pokemon_dex 件数: %d", before_count)

            inserted = 0
            updated = 0
            rows_list = list(rows)
            for r in rows_list:
                result = await conn.execute(
                    text(
                        "INSERT INTO public.pokemon_dex "
                        "(dex_number, name_ja, name_en, generation, region) "
                        "VALUES (:dn, :nj, :ne, :gn, :rg) "
                        "ON CONFLICT (dex_number) DO UPDATE SET "
                        "  name_ja = EXCLUDED.name_ja, "
                        "  name_en = EXCLUDED.name_en, "
                        "  generation = EXCLUDED.generation, "
                        "  region = EXCLUDED.region "
                        "RETURNING (xmax = 0) AS inserted"
                    ),
                    {"dn": r[0], "nj": r[1], "ne": r[2], "gn": r[3], "rg": r[4]},
                )
                row = result.fetchone()
                if row and row.inserted:
                    inserted += 1
                else:
                    updated += 1

            after_count = (
                await conn.execute(text("SELECT COUNT(*) FROM public.pokemon_dex"))
            ).scalar_one()
            logger.info(
                "適用完了: 投入候補 %d 件 (insert=%d, update=%d), 現在件数=%d",
                len(rows_list),
                inserted,
                updated,
                after_count,
            )
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="public.pokemon_dex seed (spec F1/AC1.4)")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="検証のみ、DB 変更なし")
    mode.add_argument("--apply", action="store_true", help="DB に適用（冪等）")
    args = parser.parse_args()

    rows = _load_rows()
    asyncio.run(_seed(rows, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
