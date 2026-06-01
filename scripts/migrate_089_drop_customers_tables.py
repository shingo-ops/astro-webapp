#!/usr/bin/env python3
"""Migration 089: customers 系テーブルの完全削除（ADR-089 Sprint 7）。

Sprint 1–6 でデータは companies / company_addresses / company_discord /
company_sales_channels に移行済み。
本マイグレーションは旧 customers 系テーブルを全テナントスキーマから削除する。

対象テーブル (per-tenant schema):
  - customer_contact_channels  (顧客連絡チャネル)
  - customer_discord           (顧客Discord設定)
  - customer_sales_channels    (顧客販売チャネル)
  - customer_addresses         (顧客住所)
  - customers                  (顧客マスタ)  ← 最後に削除（FK 依存あり）

削除順: 依存テーブルを先に CASCADE 削除し、最後に親テーブルを削除する。
"""
from __future__ import annotations
import asyncio, logging, os, sys
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parent.parent
if str(_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_ROOT))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    logger.error("DATABASE_URL not set"); sys.exit(1)

# 依存順（子→親）で削除
TENANT_SQL = """
DROP TABLE IF EXISTS {schema}.customer_contact_channels CASCADE;
DROP TABLE IF EXISTS {schema}.customer_discord CASCADE;
DROP TABLE IF EXISTS {schema}.customer_sales_channels CASCADE;
DROP TABLE IF EXISTS {schema}.customer_addresses CASCADE;
DROP TABLE IF EXISTS {schema}.customers CASCADE;
"""


async def main() -> None:
    url = DATABASE_URL
    if url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://"):]
    engine = create_async_engine(url, echo=False)
    try:
        logger.info("=== Migration 089: customers 系テーブル削除開始 ===")

        async with engine.connect() as conn:
            r = await conn.execute(
                text("SELECT id, tenant_code FROM public.tenants WHERE is_active = true ORDER BY id")
            )
            tenants = [(row.id, row.tenant_code) for row in r]
        logger.info("対象テナント: %d", len(tenants))

        for tid, tc in tenants:
            schema = f"tenant_{tid:03d}"
            async with engine.begin() as conn:
                await conn.execute(text(f"SET search_path = {schema}, public"))
                sql = TENANT_SQL.format(schema=schema)
                for stmt in [s.strip() for s in sql.split(";") if s.strip()]:
                    await conn.execute(text(stmt))
            logger.info("✓ %s (%s) 完了", schema, tc)

        logger.info("=== Migration 089: customers 系テーブル削除完了 ===")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
