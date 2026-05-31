#!/usr/bin/env python3
"""Migration 090: leads テーブルに messenger_link / discord_id を追加。

冪等: ADD COLUMN IF NOT EXISTS。何度実行しても副作用なし。

実行方法:
  docker compose exec -e TENANT_CODE=highlife-jpn backend \\
      python /app/scripts/migrate_090_lead_contact_links.py
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parent.parent
if str(_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_ROOT))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


async def main() -> None:
    url = os.getenv("DATABASE_URL")
    if not url:
        logger.error("DATABASE_URL not set")
        sys.exit(1)
    if url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://"):]
    engine = create_async_engine(url, echo=False)

    try:
        logger.info("=== Migration 090 (lead contact links) 開始 ===")

        async with engine.connect() as conn:
            r = await conn.execute(
                text("SELECT id, tenant_code FROM public.tenants WHERE is_active = true ORDER BY id")
            )
            tenants = [(row.id, row.tenant_code) for row in r]
        logger.info("対象テナント: %d", len(tenants))

        tmpl = (MIGRATIONS_DIR / "090_add_lead_contact_links.sql").read_text("utf-8")
        for tid, tc in tenants:
            schema = f"tenant_{tid:03d}"
            try:
                async with engine.begin() as conn:
                    sql = tmpl.replace("{schema}", schema)
                    for stmt in [s.strip() for s in sql.split(";") if s.strip()]:
                        await conn.exec_driver_sql(stmt)
                logger.info("✓ %s (tenant_code=%s) messenger_link / discord_id 追加", schema, tc)
            except Exception as e:
                logger.error("✗ %s 失敗: %s", schema, e)
                raise

        logger.info("=== Migration 090 完了 ===")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
