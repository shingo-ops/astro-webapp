#!/usr/bin/env python3
"""仕入元マスタを public.suppliers に seed する。

spec.md v1.1 Sprint 1 / F1 / DOD「suppliers 45 行 が seed 完了」:
  spreadsheet → CSV export → 本スクリプトで public.suppliers へ投入。
  supplier_type は CSV で 'individual' / 'corporate' を指定（A4 確定）。
  CSV が無い場合は migration 056 で {tenant_xxx}.suppliers から既に
  promote 済のため、本スクリプトは追加 45 仕入元の初期登録用と位置付ける。

CSV 期待カラム:
  supplier_code,name,supplier_type,default_language,
  contact_name,email,phone,address,notes

CSV データ源:
  1. astro-webapp/sheets/suppliers_master.csv が存在すればそれを優先
  2. なければ embedded サンプル 3 行で動作（CI / 開発用）

実行方法:
  docker compose exec -w /app backend python scripts/seed_suppliers_from_sheet.py --dry-run
  docker compose exec -w /app backend python scripts/seed_suppliers_from_sheet.py --apply

冪等:
  supplier_code が UNIQUE のため ON CONFLICT (supplier_code) DO UPDATE
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
CSV_PATH = BASE_DIR / "sheets" / "suppliers_master.csv"

# fallback sample（CI / 開発用、3 行のみ。本番では sheets/suppliers_master.csv 必須）
_FALLBACK_SAMPLE: list[tuple[str, str, str, str, str | None, str | None, str | None, str | None, str | None]] = [
    ("SUP-001", "サンプル法人A", "corporate", "ja",
     "山田太郎", "sample-a@example.com", None, None, "fallback sample"),
    ("SUP-002", "サンプル個人B", "individual", "ja",
     "佐藤花子", "sample-b@example.com", None, None, "fallback sample"),
    ("SUP-003", "Sample Overseas Corp", "corporate", "en",
     "John Doe", "sample-c@example.com", None, None, "fallback sample EN"),
]


def _load_rows() -> list[tuple[str, str, str, str, str | None, str | None, str | None, str | None, str | None]]:
    if CSV_PATH.exists():
        logger.info("CSV 検出: %s", CSV_PATH)
        rows: list[tuple[str, str, str, str, str | None, str | None, str | None, str | None, str | None]] = []
        with CSV_PATH.open(encoding="utf-8") as f:
            reader = csv.DictReader(f)
            required = {"supplier_code", "name", "supplier_type"}
            if not required.issubset(reader.fieldnames or []):
                raise ValueError(
                    f"CSV ヘッダー不正。必須: {required}, 実際: {reader.fieldnames}"
                )
            for row in reader:
                stype = row["supplier_type"].strip()
                if stype not in ("individual", "corporate"):
                    raise ValueError(
                        f"supplier_type は 'individual' / 'corporate' のみ可。"
                        f"実際: {stype} (supplier_code={row['supplier_code']})"
                    )
                rows.append((
                    row["supplier_code"].strip(),
                    row["name"].strip(),
                    stype,
                    (row.get("default_language") or "ja").strip(),
                    (row.get("contact_name") or "").strip() or None,
                    (row.get("email") or "").strip() or None,
                    (row.get("phone") or "").strip() or None,
                    (row.get("address") or "").strip() or None,
                    (row.get("notes") or "").strip() or None,
                ))
        return rows
    logger.warning(
        "CSV ファイル %s が存在しません。fallback サンプル 3 行で動作します。"
        " 本番運用では 45 仕入元の CSV を配置してください。",
        CSV_PATH,
    )
    return list(_FALLBACK_SAMPLE)


async def _seed(rows: Iterable, dry_run: bool) -> None:
    rows_list = list(rows)
    if dry_run:
        logger.info("dry-run: %d 仕入元行を投入予定（DB 変更なし）", len(rows_list))
        for r in rows_list[:5]:
            logger.info("  sample: code=%s type=%s name=%s", r[0], r[2], r[1])
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
                await conn.execute(text("SELECT COUNT(*) FROM public.suppliers"))
            ).scalar_one()
            logger.info("適用前 public.suppliers 件数: %d", before)

            inserted = 0
            updated = 0
            for r in rows_list:
                result = await conn.execute(
                    text(
                        "INSERT INTO public.suppliers "
                        "(supplier_code, name, supplier_type, default_language, "
                        " contact_name, email, phone, address, notes) "
                        "VALUES (:sc, :nm, :st, :dl, :cn, :em, :ph, :ad, :nt) "
                        "ON CONFLICT (supplier_code) DO UPDATE SET "
                        "  name = EXCLUDED.name, "
                        "  supplier_type = EXCLUDED.supplier_type, "
                        "  default_language = EXCLUDED.default_language, "
                        "  contact_name = EXCLUDED.contact_name, "
                        "  email = EXCLUDED.email, "
                        "  phone = EXCLUDED.phone, "
                        "  address = EXCLUDED.address, "
                        "  notes = EXCLUDED.notes "
                        "RETURNING (xmax = 0) AS inserted"
                    ),
                    {
                        "sc": r[0], "nm": r[1], "st": r[2], "dl": r[3],
                        "cn": r[4], "em": r[5], "ph": r[6], "ad": r[7], "nt": r[8],
                    },
                )
                row = result.fetchone()
                if row and row.inserted:
                    inserted += 1
                else:
                    updated += 1

            after = (
                await conn.execute(text("SELECT COUNT(*) FROM public.suppliers"))
            ).scalar_one()
            logger.info(
                "適用完了: insert=%d update=%d 現在件数=%d",
                inserted, updated, after,
            )
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="public.suppliers seed (spec F1 / 45 仕入元)")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    rows = _load_rows()
    asyncio.run(_seed(rows, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
