#!/usr/bin/env python3
"""出力.csv を public.inventory (F11) に seed する (spec.md v1.3 / Sprint 11)。

入力: astro-webapp/sheets/raw/出力.csv (102 行)
出力: public.inventory に UPSERT (UNIQUE (supplier_id, product_id, condition))

CSV ヘッダー期待:
  Categoly, Series, Quantity, Unit Price, Condition, Status,
  Note_JA, Note_EN, 提供者, Mark, Japanese Title, English Title,
  Boxes per Case, Packs per Box, Box重量, Case重量, Release Date, MOQ

DB マッピング:
  提供者       → supplier_id (suppliers.name で resolve)
  Mark         → product_id (products.product_code で resolve)
  Quantity     → quantity
  Unit Price   → unit_price (JPY, INTEGER)
  Condition    → condition (raw のまま、e.g., 'Sealed box', 'No shrink box', 'Damaged box')
  Status       → status ('In Stock' → 'in_stock' 等に正規化)
  Note_JA/EN   → notes_ja/notes_en

Resolve 失敗 (supplier/product 不在) は warning ログ + skip。

実行方法:
  docker compose exec -w /app backend python scripts/seed_inventory_from_output.py --dry-run
  docker compose exec -w /app backend python scripts/seed_inventory_from_output.py --apply

冪等: ON CONFLICT (supplier_id, product_id, condition) DO UPDATE

前提:
  - migration 081 (public.inventory 作成) 適用済
  - seed_products_from_master.py 実行済 (Mark で products 参照可能)
  - seed_suppliers_from_line_master.py 実行済 (LINE名 = suppliers.name で参照可能)
"""
from __future__ import annotations

import argparse
import asyncio
import csv
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
    BASE_DIR / "sheets" / "inventory_offers.csv",
    BASE_DIR / "sheets" / "raw" / "出力.csv",
]

# Status の正規化マップ
STATUS_MAP = {
    "in stock": "in_stock",
    "out of stock": "out_of_stock",
    "reserved": "reserved",
    "archived": "archived",
}


class InventoryRow(NamedTuple):
    supplier_name: str
    product_mark: str
    condition: str
    quantity: int
    unit_price: int
    status: str
    notes_ja: str | None
    notes_en: str | None


def _parse_int(s: str) -> int | None:
    s = (s or "").strip().replace(",", "")
    if not s:
        return None
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return None


def _normalize_status(s: str) -> str:
    return STATUS_MAP.get((s or "").strip().lower(), "in_stock")


def _load_rows() -> list[InventoryRow]:
    csv_path = next((p for p in CSV_CANDIDATES if p.exists()), None)
    if csv_path is None:
        logger.error("CSV ファイルが見つかりません。候補: %s", CSV_CANDIDATES)
        sys.exit(1)
    logger.info("CSV 検出: %s", csv_path)

    rows: list[InventoryRow] = []
    with csv_path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        required = {"提供者", "Mark", "Quantity", "Unit Price", "Condition", "Status"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError(
                f"CSV ヘッダー不正。必須: {required}, 実際: {reader.fieldnames}"
            )
        for raw in reader:
            supplier_name = (raw.get("提供者") or "").strip()
            mark = (raw.get("Mark") or "").strip()
            if not supplier_name or not mark:
                continue
            quantity = _parse_int(raw.get("Quantity", ""))
            unit_price = _parse_int(raw.get("Unit Price", ""))
            if quantity is None or unit_price is None:
                logger.warning("数値パース失敗 supplier=%s mark=%s qty=%r price=%r → skip",
                               supplier_name, mark, raw.get("Quantity"), raw.get("Unit Price"))
                continue
            condition = (raw.get("Condition") or "").strip() or "unknown"
            rows.append(
                InventoryRow(
                    supplier_name=supplier_name,
                    product_mark=mark,
                    condition=condition,
                    quantity=quantity,
                    unit_price=unit_price,
                    status=_normalize_status(raw.get("Status", "")),
                    notes_ja=(raw.get("Note_JA") or "").strip() or None,
                    notes_en=(raw.get("Note_EN") or "").strip() or None,
                )
            )
    return rows


async def _seed(rows: Iterable[InventoryRow], dry_run: bool) -> None:
    rows_list = list(rows)

    url = os.getenv("DATABASE_URL")
    if not url:
        logger.error("DATABASE_URL not set")
        sys.exit(1)
    if url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://"):]
    engine = create_async_engine(url, echo=False)

    try:
        async with engine.begin() as conn:
            # supplier_name → supplier_id の lookup table を構築
            sup_rows = (await conn.execute(text("SELECT id, name FROM public.suppliers"))).all()
            sup_map = {r.name: r.id for r in sup_rows}
            logger.info("supplier lookup: %d entries loaded", len(sup_map))

            # product_code → product_id の lookup table を構築
            prod_rows = (await conn.execute(text(
                "SELECT id, product_code FROM public.products WHERE product_code IS NOT NULL"
            ))).all()
            prod_map = {r.product_code: r.id for r in prod_rows}
            logger.info("product lookup: %d entries loaded", len(prod_map))

            resolved = []
            unresolved_sup = 0
            unresolved_prod = 0
            for r in rows_list:
                sid = sup_map.get(r.supplier_name)
                pid = prod_map.get(r.product_mark)
                if sid is None:
                    logger.warning("supplier 未登録: %r (Mark=%s) → skip", r.supplier_name, r.product_mark)
                    unresolved_sup += 1
                    continue
                if pid is None:
                    logger.warning("product 未登録: Mark=%r (supplier=%s) → skip", r.product_mark, r.supplier_name)
                    unresolved_prod += 1
                    continue
                resolved.append((r, sid, pid))

            logger.info("resolve 結果: 成功=%d, supplier 不在 skip=%d, product 不在 skip=%d",
                        len(resolved), unresolved_sup, unresolved_prod)

            if dry_run:
                logger.info("dry-run: %d 行を投入予定 (DB 変更なし)", len(resolved))
                for (r, sid, pid) in resolved[:5]:
                    logger.info("  sample: sup=%s(id=%d) prod=%s(id=%d) cond=%s qty=%d price=%d",
                                r.supplier_name, sid, r.product_mark, pid, r.condition, r.quantity, r.unit_price)
                if len(resolved) > 5:
                    logger.info("  ... (残り %d 行は省略)", len(resolved) - 5)
                return

            before = (await conn.execute(text("SELECT COUNT(*) FROM public.inventory"))).scalar_one()
            logger.info("適用前 public.inventory 件数: %d", before)

            inserted = updated = 0
            for (r, sid, pid) in resolved:
                result = await conn.execute(
                    text(
                        """
                        INSERT INTO public.inventory
                            (supplier_id, product_id, condition, quantity, unit_price,
                             status, notes_ja, notes_en, source)
                        VALUES (:sid, :pid, :cond, :qty, :up, :st, :nj, :ne, 'csv_import')
                        ON CONFLICT (supplier_id, product_id, condition) DO UPDATE SET
                            quantity = EXCLUDED.quantity,
                            unit_price = EXCLUDED.unit_price,
                            status = EXCLUDED.status,
                            notes_ja = EXCLUDED.notes_ja,
                            notes_en = EXCLUDED.notes_en,
                            source = 'csv_import',
                            offered_at = NOW(),
                            updated_at = NOW()
                        RETURNING (xmax = 0) AS inserted
                        """
                    ),
                    {
                        "sid": sid, "pid": pid, "cond": r.condition, "qty": r.quantity,
                        "up": r.unit_price, "st": r.status, "nj": r.notes_ja, "ne": r.notes_en,
                    },
                )
                row = result.fetchone()
                if row and row.inserted:
                    inserted += 1
                else:
                    updated += 1

            after = (await conn.execute(text("SELECT COUNT(*) FROM public.inventory"))).scalar_one()
            logger.info("適用後 public.inventory 件数: %d (inserted=%d, updated=%d)",
                        after, inserted, updated)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="出力.csv → public.inventory seed")
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    rows = _load_rows()
    asyncio.run(_seed(rows, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
