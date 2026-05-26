#!/usr/bin/env python3
"""仕入元マスタ.csv (LINE名ベース) を public.suppliers に seed する (spec.md v1.3)。

入力: astro-webapp/sheets/raw/仕入元マスタ.csv (43 行)
出力: public.suppliers に UPSERT (supplier_code を生成して ON CONFLICT)

CSV ヘッダー期待:
  LINE名, Discord ID, 郵便番号, 都道府県, 市町村, 住所1, 住所2, 電話番号, メールアドレス

DB マッピング:
  LINE名         → name
  Discord ID    → notes (「Discord ID: XXX」形式で記録)
  郵便番号+...    → address (空文字 join)
  電話番号        → phone
  メールアドレス  → email
  (生成)         → supplier_code: 「SUP-{NNN:03d}」連番
  (デフォルト)    → supplier_type: 'individual' (LINE名ベースなので個人想定)
  (デフォルト)    → default_language: 'ja'

実行方法:
  docker compose exec -w /app backend python scripts/seed_suppliers_from_line_master.py --dry-run
  docker compose exec -w /app backend python scripts/seed_suppliers_from_line_master.py --apply

冪等: ON CONFLICT (supplier_code) DO UPDATE SET ...

関連:
  spec.md v1.3 / sheets/raw/仕入元マスタ.csv
  migrations/056_add_suppliers_type_and_promote_public.sql
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
    BASE_DIR / "sheets" / "suppliers_line_master.csv",
    BASE_DIR / "sheets" / "raw" / "仕入元マスタ.csv",
]


class SupplierRow(NamedTuple):
    supplier_code: str
    name: str
    supplier_type: str
    default_language: str
    phone: str | None
    email: str | None
    address: str | None
    notes: str | None


def _build_address(parts: list[str]) -> str | None:
    cleaned = [p.strip() for p in parts if p and p.strip()]
    return " ".join(cleaned) if cleaned else None


def _load_rows() -> list[SupplierRow]:
    csv_path = next((p for p in CSV_CANDIDATES if p.exists()), None)
    if csv_path is None:
        logger.error("CSV ファイルが見つかりません。候補: %s", CSV_CANDIDATES)
        sys.exit(1)
    logger.info("CSV 検出: %s", csv_path)

    rows: list[SupplierRow] = []
    seq = 0
    with csv_path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        required = {"LINE名"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError(
                f"CSV ヘッダー不正。必須: {required}, 実際: {reader.fieldnames}"
            )
        for raw in reader:
            name = (raw.get("LINE名") or "").strip()
            if not name:
                continue
            seq += 1
            discord_id = (raw.get("Discord ID") or "").strip()
            notes = f"Discord ID: {discord_id}" if discord_id else None
            address = _build_address([
                raw.get("郵便番号", ""),
                raw.get("都道府県", ""),
                raw.get("市町村", ""),
                raw.get("住所1", ""),
                raw.get("住所2", ""),
            ])
            rows.append(
                SupplierRow(
                    supplier_code=f"SUP-{seq:03d}",
                    name=name,
                    supplier_type="individual",
                    default_language="ja",
                    phone=(raw.get("電話番号") or "").strip() or None,
                    email=(raw.get("メールアドレス") or "").strip() or None,
                    address=address,
                    notes=notes,
                )
            )
    return rows


async def _seed(rows: Iterable[SupplierRow], dry_run: bool) -> None:
    rows_list = list(rows)
    if dry_run:
        logger.info("dry-run: %d 行を投入予定 (DB 変更なし)", len(rows_list))
        for r in rows_list[:5]:
            logger.info("  sample: %s | %s | type=%s", r.supplier_code, r.name, r.supplier_type)
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
            before = (await conn.execute(text("SELECT COUNT(*) FROM public.suppliers"))).scalar_one()
            logger.info("適用前 public.suppliers 件数: %d", before)

            inserted = updated = 0
            for r in rows_list:
                result = await conn.execute(
                    text(
                        """
                        INSERT INTO public.suppliers
                            (supplier_code, name, supplier_type, default_language,
                             phone, email, address, notes, is_active)
                        VALUES (:sc, :nm, :st, :dl, :ph, :em, :ad, :nt, TRUE)
                        ON CONFLICT (supplier_code) DO UPDATE SET
                            name = EXCLUDED.name,
                            supplier_type = EXCLUDED.supplier_type,
                            default_language = EXCLUDED.default_language,
                            phone = EXCLUDED.phone,
                            email = EXCLUDED.email,
                            address = EXCLUDED.address,
                            notes = EXCLUDED.notes,
                            updated_at = NOW()
                        RETURNING (xmax = 0) AS inserted
                        """
                    ),
                    {
                        "sc": r.supplier_code, "nm": r.name, "st": r.supplier_type,
                        "dl": r.default_language, "ph": r.phone, "em": r.email,
                        "ad": r.address, "nt": r.notes,
                    },
                )
                row = result.fetchone()
                if row and row.inserted:
                    inserted += 1
                else:
                    updated += 1

            after = (await conn.execute(text("SELECT COUNT(*) FROM public.suppliers"))).scalar_one()
            logger.info("適用後 public.suppliers 件数: %d (inserted=%d, updated=%d)",
                        after, inserted, updated)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="仕入元マスタ.csv → public.suppliers seed")
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    rows = _load_rows()
    asyncio.run(_seed(rows, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
