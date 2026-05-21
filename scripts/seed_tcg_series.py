#!/usr/bin/env python3
"""TCG シリーズマスタを public.tcg_series_master に seed する。

spec.md v1.1 Sprint 1 / F1 / DOD「tcg_series_master 主要 6 シリーズ」:
  Pokemon Booster Box / One Piece / Dragon Ball / Union Arena / 遊戯王 + その他

CSV データ源:
  1. astro-webapp/sheets/tcg_series.csv が存在すればそれを優先
  2. なければ embedded サンプル（5 系列各 1 シリーズ + その他 1 行 = 6 行）で動作

CSV 期待カラム:
  tcg_type,series_code,name_ja,name_en,release_date,category

実行方法:
  docker compose exec -w /app backend python scripts/seed_tcg_series.py --dry-run
  docker compose exec -w /app backend python scripts/seed_tcg_series.py --apply

冪等:
  ON CONFLICT (tcg_type, series_code) DO UPDATE
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import datetime as dt
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
CSV_PATH = BASE_DIR / "sheets" / "tcg_series.csv"

# 仕様書 F1 で「主要 6 シリーズ」と明記されている初期 seed
_FALLBACK_SAMPLE: list[tuple[str, str, str, str, dt.date | None, str | None]] = [
    ("pokemon_booster_box", "SV1a", "ポケモンカードゲーム スカーレット&バイオレット 拡張パック バイオレット",
     "Pokemon TCG Scarlet & Violet Expansion Pack Violet",
     dt.date(2023, 1, 20), "expansion"),
    ("one_piece", "OP-01", "ワンピースカードゲーム 第1弾 ROMANCE DAWN",
     "One Piece Card Game Vol.1 ROMANCE DAWN",
     dt.date(2022, 7, 22), "starter"),
    ("dragon_ball", "DB-FW01", "ドラゴンボールスーパーカードゲーム フュージョンワールド 第1弾",
     "Dragon Ball Super Card Game Fusion World Set 01",
     dt.date(2024, 2, 16), "expansion"),
    ("union_arena", "UA-01", "ユニオンアリーナ 鬼滅の刃",
     "Union Arena Demon Slayer",
     dt.date(2023, 4, 14), "expansion"),
    ("yugioh", "YGO-25TH", "遊戯王オフィシャルカードゲーム デュエルモンスターズ 25th ANNIVERSARY",
     "Yu-Gi-Oh! OCG Duel Monsters 25th Anniversary",
     dt.date(2024, 1, 1), "anniversary"),
    ("other", "OTHER-DEFAULT", "その他 TCG（未分類）",
     "Other TCG (uncategorized)",
     None, "other"),
]


def _load_rows() -> list[tuple[str, str, str, str, dt.date | None, str | None]]:
    if CSV_PATH.exists():
        logger.info("CSV 検出: %s", CSV_PATH)
        rows: list[tuple[str, str, str, str, dt.date | None, str | None]] = []
        with CSV_PATH.open(encoding="utf-8") as f:
            reader = csv.DictReader(f)
            required = {"tcg_type", "series_code", "name_ja", "name_en"}
            if not required.issubset(reader.fieldnames or []):
                raise ValueError(
                    f"CSV ヘッダー不正。必須: {required}, 実際: {reader.fieldnames}"
                )
            for row in reader:
                rd: dt.date | None = None
                if row.get("release_date"):
                    rd = dt.date.fromisoformat(row["release_date"].strip())
                rows.append((
                    row["tcg_type"].strip(),
                    row["series_code"].strip(),
                    row["name_ja"].strip(),
                    row["name_en"].strip(),
                    rd,
                    (row.get("category") or "").strip() or None,
                ))
        return rows
    logger.warning(
        "CSV ファイル %s が存在しません。fallback サンプル 6 行で動作します。",
        CSV_PATH,
    )
    return list(_FALLBACK_SAMPLE)


async def _seed(rows: Iterable, dry_run: bool) -> None:
    rows_list = list(rows)
    if dry_run:
        logger.info("dry-run: %d 行を投入予定（DB 変更なし）", len(rows_list))
        for r in rows_list:
            logger.info("  sample: type=%s code=%s ja=%s", r[0], r[1], r[2])
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
            before = (
                await conn.execute(text("SELECT COUNT(*) FROM public.tcg_series_master"))
            ).scalar_one()
            logger.info("適用前 public.tcg_series_master 件数: %d", before)

            inserted = 0
            updated = 0
            for r in rows_list:
                result = await conn.execute(
                    text(
                        "INSERT INTO public.tcg_series_master "
                        "(tcg_type, series_code, name_ja, name_en, release_date, category) "
                        "VALUES (:tt, :sc, :nj, :ne, :rd, :ct) "
                        "ON CONFLICT (tcg_type, series_code) DO UPDATE SET "
                        "  name_ja = EXCLUDED.name_ja, "
                        "  name_en = EXCLUDED.name_en, "
                        "  release_date = EXCLUDED.release_date, "
                        "  category = EXCLUDED.category "
                        "RETURNING (xmax = 0) AS inserted"
                    ),
                    {
                        "tt": r[0], "sc": r[1], "nj": r[2], "ne": r[3],
                        "rd": r[4], "ct": r[5],
                    },
                )
                row = result.fetchone()
                if row and row.inserted:
                    inserted += 1
                else:
                    updated += 1
            after = (
                await conn.execute(text("SELECT COUNT(*) FROM public.tcg_series_master"))
            ).scalar_one()
            logger.info(
                "適用完了: insert=%d update=%d 現在件数=%d",
                inserted, updated, after,
            )
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="public.tcg_series_master seed")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    rows = _load_rows()
    asyncio.run(_seed(rows, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
