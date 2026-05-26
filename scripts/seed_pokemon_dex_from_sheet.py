#!/usr/bin/env python3
"""ポケモン図鑑.csv (スプレッドシート由来、世代集計 + 個別 1025 種混在) を public.pokemon_dex に seed する。

spec.md v1.3 F1 / Sprint 9 revised:
  - 既存 seed_pokemon_dex.py は `dex_number,name_ja,name_en,generation,region` の単純 CSV を期待
  - 本 script は実スプレッドシート CSV 構造に対応:
      L1: 世代集計ヘッダー (5 列)
      L2-10: 世代集計 9 行 (skip)
      L11: 「ポケモン図鑑」section break
      L12: 個別データヘッダー (No.,日本語名,英語名,地方名,Generation)
      L13-1036: 個別ポケモン 1024 行

入力: astro-webapp/sheets/raw/ポケモン図鑑.csv
出力: public.pokemon_dex に UPSERT (dex_number ON CONFLICT)

DB マッピング:
  No.       → dex_number (INTEGER)
  日本語名   → name_ja
  英語名     → name_en
  地方名     → region (e.g., カントー → "Kanto" に変換)
  Generation → generation (e.g., "Generation 1" → 1)

実行方法:
  docker compose exec -w /app backend python scripts/seed_pokemon_dex_from_sheet.py --dry-run
  docker compose exec -w /app backend python scripts/seed_pokemon_dex_from_sheet.py --apply

冪等: ON CONFLICT (dex_number) DO UPDATE
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import os
import re
import sys
from pathlib import Path
from typing import Iterable, NamedTuple

_APP_ROOT = Path(__file__).resolve().parent.parent
if str(_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_ROOT))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
CSV_CANDIDATES = [
    BASE_DIR / "sheets" / "pokemon_dex.csv",
    BASE_DIR / "sheets" / "raw" / "ポケモン図鑑.csv",
]

# 地方名 ja → en マッピング (Generation-Region 1対1)
REGION_JA_TO_EN = {
    "カントー": "Kanto",
    "ジョウト": "Johto",
    "ホウエン": "Hoenn",
    "シンオウ": "Sinnoh",
    "イッシュ": "Unova",
    "カロス": "Kalos",
    "アローラ": "Alola",
    "ガラル": "Galar",
    "パルデア/キタカミ/ブルーベリー": "Paldea",
    "パルデア": "Paldea",
}


class DexRow(NamedTuple):
    dex_number: int
    name_ja: str
    name_en: str
    generation: int | None
    region: str | None


def _parse_generation(s: str) -> int | None:
    s = (s or "").strip()
    m = re.search(r"(\d+)", s)
    return int(m.group(1)) if m else None


def _normalize_region(s: str) -> str | None:
    s = (s or "").strip()
    if not s:
        return None
    return REGION_JA_TO_EN.get(s, s)


def _load_rows() -> list[DexRow]:
    csv_path = next((p for p in CSV_CANDIDATES if p.exists()), None)
    if csv_path is None:
        logger.error("CSV ファイルが見つかりません。候補: %s", CSV_CANDIDATES)
        sys.exit(1)
    logger.info("CSV 検出: %s", csv_path)

    rows: list[DexRow] = []
    with csv_path.open(encoding="utf-8") as f:
        all_rows = list(csv.reader(f))

    # L11 (index 10) の「ポケモン図鑑」section break を探す
    section_header_idx = None
    for i, r in enumerate(all_rows):
        first = (r[0] if r else "").strip()
        if first in ("ポケモン図鑑", "トレーナー図鑑"):
            section_header_idx = i
            break

    if section_header_idx is None:
        logger.error("section break (「ポケモン図鑑」行) が CSV 内に見つかりません")
        sys.exit(1)

    # 次の行が header (No.,日本語名,...)、その次から個別データ
    header_idx = section_header_idx + 1
    if header_idx >= len(all_rows):
        logger.error("section break の次の header 行がない")
        sys.exit(1)

    header = [h.strip() for h in all_rows[header_idx]]
    if not all(c in header for c in ("No.", "日本語名", "英語名")):
        logger.error("個別データ header 不正: %s", header)
        sys.exit(1)

    col = {name: header.index(name) for name in header if name}
    for i in range(header_idx + 1, len(all_rows)):
        r = all_rows[i]
        if not r or not r[col["No."]]:
            continue
        try:
            dex_number = int(r[col["No."]].strip())
        except (ValueError, IndexError):
            continue
        name_ja = (r[col["日本語名"]] if col["日本語名"] < len(r) else "").strip()
        name_en = (r[col["英語名"]] if col["英語名"] < len(r) else "").strip()
        if not name_ja or not name_en:
            # 空行 (枠だけ) はスキップ
            continue
        region = _normalize_region(r[col["地方名"]] if "地方名" in col and col["地方名"] < len(r) else "")
        generation = _parse_generation(r[col["Generation"]] if "Generation" in col and col["Generation"] < len(r) else "")
        rows.append(DexRow(dex_number, name_ja, name_en, generation, region))

    return rows


async def _seed(rows: Iterable[DexRow], dry_run: bool) -> None:
    rows_list = list(rows)
    if dry_run:
        logger.info("dry-run: %d 行を投入予定 (DB 変更なし)", len(rows_list))
        for r in rows_list[:5]:
            logger.info("  sample: dex=%d ja=%s en=%s gen=%s region=%s",
                        r.dex_number, r.name_ja, r.name_en, r.generation, r.region)
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
            before = (await conn.execute(text("SELECT COUNT(*) FROM public.pokemon_dex"))).scalar_one()
            logger.info("適用前 public.pokemon_dex 件数: %d", before)

            inserted = updated = 0
            for r in rows_list:
                result = await conn.execute(
                    text(
                        """
                        INSERT INTO public.pokemon_dex
                            (dex_number, name_ja, name_en, generation, region)
                        VALUES (:dn, :nj, :ne, :gn, :rg)
                        ON CONFLICT (dex_number) DO UPDATE SET
                            name_ja = EXCLUDED.name_ja,
                            name_en = EXCLUDED.name_en,
                            generation = EXCLUDED.generation,
                            region = EXCLUDED.region
                        RETURNING (xmax = 0) AS inserted
                        """
                    ),
                    {"dn": r.dex_number, "nj": r.name_ja, "ne": r.name_en,
                     "gn": r.generation, "rg": r.region},
                )
                row = result.fetchone()
                if row and row.inserted:
                    inserted += 1
                else:
                    updated += 1

            after = (await conn.execute(text("SELECT COUNT(*) FROM public.pokemon_dex"))).scalar_one()
            logger.info("適用後 public.pokemon_dex 件数: %d (inserted=%d, updated=%d)",
                        after, inserted, updated)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="ポケモン図鑑.csv → public.pokemon_dex seed")
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    rows = _load_rows()
    asyncio.run(_seed(rows, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
