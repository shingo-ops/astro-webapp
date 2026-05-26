#!/usr/bin/env python3
"""商品マスタ.csv を public.products に seed する (spec.md v1.3 F1 / Sprint 9 revised)。

入力: astro-webapp/sheets/raw/商品マスタ.csv (210 行、19 列)
出力: public.products に UPSERT (Mark を product_code として ON CONFLICT DO UPDATE)

CSV ヘッダー期待:
  Category, Mark, Japanese Title, English Title, Boxes per Case, Packs per Box,
  VOLUME WEIGHT, Box重量, Case重量, Release Date, Search Keywords, Exclude Keywords,
  Related Series, カテゴリ分類, REQUIRED_OUTPUT_VALUE, MOQ, 品目, HSコード, 素材

DB マッピング:
  Mark            → product_code
  Japanese Title  → name
  English Title   → name_en
  Category        → category (migration 082)
  Boxes per Case  → boxes_per_case
  Packs per Box   → packs_per_box
  Box重量          → box_weight_kg
  Case重量         → case_weight_kg
  Release Date    → release_date (YYYY/MM/DD → DATE)
  MOQ             → moq
  HSコード         → hs_code
  素材            → material

実行方法:
  docker compose exec -w /app backend python scripts/seed_products_from_master.py --dry-run
  docker compose exec -w /app backend python scripts/seed_products_from_master.py --apply

冪等: ON CONFLICT (product_code) DO UPDATE SET ...

関連:
  migrations/082_extend_products_box_attributes.sql
  spec.md v1.3 F1 / F11
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
    BASE_DIR / "sheets" / "products_master.csv",  # 標準名 (将来)
    BASE_DIR / "sheets" / "raw" / "商品マスタ.csv",  # 現状 (スプレッドシート由来)
]


class ProductRow(NamedTuple):
    product_code: str
    name: str
    name_en: str | None
    category: str | None
    boxes_per_case: int | None
    packs_per_box: int | None
    box_weight_kg: float | None
    case_weight_kg: float | None
    release_date: dt.date | None
    moq: int | None
    hs_code: str | None
    material: str | None


def _parse_int(s: str) -> int | None:
    s = (s or "").strip()
    if not s or s == "-":
        return None
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return None


def _parse_float(s: str) -> float | None:
    s = (s or "").strip()
    if not s or s == "-":
        return None
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def _parse_date(s: str) -> dt.date | None:
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    logger.warning("Release Date を parse できませんでした: %r", s)
    return None


def _load_rows() -> list[ProductRow]:
    csv_path = next((p for p in CSV_CANDIDATES if p.exists()), None)
    if csv_path is None:
        logger.error("CSV ファイルが見つかりません。候補: %s", CSV_CANDIDATES)
        sys.exit(1)
    logger.info("CSV 検出: %s", csv_path)

    rows: list[ProductRow] = []
    with csv_path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        required = {"Mark", "Japanese Title", "English Title", "Category"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError(
                f"CSV ヘッダー不正。必須: {required}, 実際: {reader.fieldnames}"
            )
        for raw in reader:
            mark = (raw.get("Mark") or "").strip()
            if not mark:
                continue  # 空行スキップ
            rows.append(
                ProductRow(
                    product_code=mark,
                    name=(raw.get("Japanese Title") or "").strip() or mark,
                    name_en=(raw.get("English Title") or "").strip() or None,
                    category=(raw.get("Category") or "").strip() or None,
                    boxes_per_case=_parse_int(raw.get("Boxes per Case", "")),
                    packs_per_box=_parse_int(raw.get("Packs per Box", "")),
                    box_weight_kg=_parse_float(raw.get("Box重量", "")),
                    case_weight_kg=_parse_float(raw.get("Case重量", "")),
                    release_date=_parse_date(raw.get("Release Date", "")),
                    moq=_parse_int(raw.get("MOQ", "")),
                    hs_code=(raw.get("HSコード") or "").strip() or None,
                    material=(raw.get("素材") or "").strip() or None,
                )
            )
    return rows


async def _seed(rows: Iterable[ProductRow], dry_run: bool) -> None:
    rows_list = list(rows)
    if dry_run:
        logger.info("dry-run: %d 行を投入予定 (DB 変更なし)", len(rows_list))
        for r in rows_list[:5]:
            logger.info("  sample: %s | %s | %s | %s", r.product_code, r.name, r.category, r.release_date)
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
            before = (await conn.execute(text("SELECT COUNT(*) FROM public.products"))).scalar_one()
            logger.info("適用前 public.products 件数: %d", before)

            inserted = updated = 0
            for r in rows_list:
                result = await conn.execute(
                    text(
                        """
                        INSERT INTO public.products
                            (product_code, name, name_en, category, boxes_per_case,
                             packs_per_box, box_weight_kg, case_weight_kg, release_date,
                             moq, hs_code, material, stock_quantity)
                        VALUES (:pc, :nm, :ne, :cat, :bpc, :ppb, :bw, :cw, :rd,
                                :moq, :hs, :mat, 0)
                        ON CONFLICT (product_code) DO UPDATE SET
                            name = EXCLUDED.name,
                            name_en = EXCLUDED.name_en,
                            category = EXCLUDED.category,
                            boxes_per_case = EXCLUDED.boxes_per_case,
                            packs_per_box = EXCLUDED.packs_per_box,
                            box_weight_kg = EXCLUDED.box_weight_kg,
                            case_weight_kg = EXCLUDED.case_weight_kg,
                            release_date = EXCLUDED.release_date,
                            moq = EXCLUDED.moq,
                            hs_code = EXCLUDED.hs_code,
                            material = EXCLUDED.material,
                            updated_at = NOW()
                        RETURNING (xmax = 0) AS inserted
                        """
                    ),
                    {
                        "pc": r.product_code, "nm": r.name, "ne": r.name_en,
                        "cat": r.category, "bpc": r.boxes_per_case, "ppb": r.packs_per_box,
                        "bw": r.box_weight_kg, "cw": r.case_weight_kg, "rd": r.release_date,
                        "moq": r.moq, "hs": r.hs_code, "mat": r.material,
                    },
                )
                row = result.fetchone()
                if row and row.inserted:
                    inserted += 1
                else:
                    updated += 1

            after = (await conn.execute(text("SELECT COUNT(*) FROM public.products"))).scalar_one()
            logger.info("適用後 public.products 件数: %d (inserted=%d, updated=%d)",
                        after, inserted, updated)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="商品マスタ.csv → public.products seed")
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    rows = _load_rows()
    asyncio.run(_seed(rows, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
