#!/usr/bin/env python3
"""Sprint 9 / F9 v1.2: Phase A 並走運用の CSV エクスポート (AC9.2)。

spec.md v1.2 F9 / AC9.2:
  - 承認済 inventory_movements を CSV 出力 (Phase A 並走中の運用フロー)。
  - 運用担当者がスプレッドシートに反映するためのフィードバック CSV。

CSV 列:
  product_id, delta_qty, occurred_at, supplier_id, operator_id, notes

冪等性:
  - 同じ期間を 2 回実行しても CSV の中身は同じ（順序 = (occurred_at, id) ASC で固定）。
  - 重複出力防止のために再実行間で状態を持たない（純粋関数）。

使い方:
  python scripts/export_inventory_for_sheet.py \\
      --tenant 4 --since 2026-05-01 --output /tmp/inventory-2026-05.csv

オプション:
  --tenant N            : public.tenants.id (必須)
  --since YYYY-MM-DD    : occurred_at >= この日時 (必須)
  --until YYYY-MM-DD    : occurred_at < この日時 (任意、未指定なら無制限)
  --output path.csv     : 出力ファイル (必須)
  --include-rejected    : reject されたが残る movements も含む (デフォルト false、
                          現状の Sprint 6 経路では reject 時は movement を作らないので
                          実質変化なし)

関連:
  .claude-pipeline/spec.md F9 / AC9.2
  backend/app/services/inventory_movements.py
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parent.parent
if str(_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_ROOT))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


CSV_COLUMNS = [
    "product_id",
    "delta_qty",
    "occurred_at",
    "supplier_id",
    "operator_id",
    "notes",
]


def _parse_date(s: str) -> date:
    """YYYY-MM-DD を date に解釈。"""
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError as e:
        raise argparse.ArgumentTypeError(
            f"--since/--until は YYYY-MM-DD 形式で指定してください: {s!r}"
        ) from e


def _normalize_db_url(raw: str) -> str:
    if raw.startswith("postgresql+asyncpg://"):
        return raw
    if raw.startswith("postgresql://"):
        return raw.replace("postgresql://", "postgresql+asyncpg://", 1)
    return raw


async def fetch_movements(
    engine,
    *,
    tenant_id: int,
    since: date,
    until: date | None,
) -> list[dict]:
    """tenant_id + 期間でフィルタした inventory_movements を取得する。

    冪等性: (occurred_at ASC, id ASC) で固定ソート。

    Returns:
        dict のリスト（CSV_COLUMNS に対応）。
    """
    sql = (
        "SELECT product_id, delta_qty, occurred_at, supplier_id, operator_id, notes "
        "FROM public.inventory_movements "
        "WHERE tenant_id = :tid "
        "  AND occurred_at >= :since "
    )
    params: dict = {"tid": tenant_id, "since": since}
    if until is not None:
        sql += "  AND occurred_at < :until "
        params["until"] = until
    sql += "ORDER BY occurred_at ASC, id ASC"

    async with engine.connect() as conn:
        rows = (await conn.execute(text(sql), params)).mappings().all()
    return [dict(r) for r in rows]


def write_csv(rows: list[dict], output: Path) -> None:
    """CSV 書き出し。

    occurred_at は ISO8601 文字列で出力する。
    """
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(CSV_COLUMNS)
        for row in rows:
            occurred_at = row.get("occurred_at")
            occurred_str = (
                occurred_at.isoformat()
                if hasattr(occurred_at, "isoformat")
                else (str(occurred_at) if occurred_at is not None else "")
            )
            writer.writerow(
                [
                    row.get("product_id", ""),
                    row.get("delta_qty", ""),
                    occurred_str,
                    row.get("supplier_id", "") if row.get("supplier_id") is not None else "",
                    row.get("operator_id", "") if row.get("operator_id") is not None else "",
                    row.get("notes", "") if row.get("notes") is not None else "",
                ]
            )


async def export_inventory(
    *,
    tenant_id: int,
    since: date,
    until: date | None,
    output: Path,
    db_url: str,
) -> int:
    """エクスポート本体 (テストからも呼べる)。

    Returns:
        書き出した行数 (header 除く)。
    """
    engine = create_async_engine(_normalize_db_url(db_url), echo=False)
    try:
        rows = await fetch_movements(
            engine, tenant_id=tenant_id, since=since, until=until
        )
    finally:
        await engine.dispose()
    write_csv(rows, output)
    logger.info(
        "tenant=%s since=%s until=%s output=%s rows=%d",
        tenant_id, since, until, output, len(rows),
    )
    return len(rows)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Sprint 9 / F9: Phase A 並走運用の CSV エクスポート"
    )
    p.add_argument("--tenant", type=int, required=True, help="public.tenants.id")
    p.add_argument("--since", type=_parse_date, required=True, help="YYYY-MM-DD")
    p.add_argument("--until", type=_parse_date, default=None, help="YYYY-MM-DD (任意)")
    p.add_argument("--output", type=Path, required=True, help="出力 CSV ファイルパス")
    return p


async def main_async() -> int:
    args = _build_parser().parse_args()
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        logger.error("DATABASE_URL が未設定です")
        return 1
    try:
        rows_count = await export_inventory(
            tenant_id=args.tenant,
            since=args.since,
            until=args.until,
            output=args.output,
            db_url=db_url,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("export 失敗: %s", exc)
        return 2
    logger.info("OK: %d rows written to %s", rows_count, args.output)
    return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    sys.exit(main())
