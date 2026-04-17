#!/usr/bin/env python3
"""Meta Messaging マイグレーション（meta_messagesテーブル追加）。"""
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

BASE_DIR = Path(__file__).resolve().parent.parent


def _split(sql):
    result, buf, dollar = [], [], False
    i = 0
    while i < len(sql):
        if sql[i:i+2] == "$$":
            dollar = not dollar; buf.append("$$"); i += 2; continue
        if sql[i] == ";" and not dollar:
            result.append("".join(buf)); buf = []
        else:
            buf.append(sql[i])
        i += 1
    if buf: result.append("".join(buf))
    return result


async def _exec(conn, sql):
    for s in _split(sql):
        s = s.strip()
        if s: await conn.execute(text(s))


async def main():
    url = DATABASE_URL
    if url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://"):]
    engine = create_async_engine(url, echo=False)
    try:
        logger.info("=== Meta マイグレーション開始 ===")

        async with engine.connect() as conn:
            r = await conn.execute(
                text("SELECT id, tenant_code FROM public.tenants WHERE is_active = true ORDER BY id")
            )
            tenants = [(row.id, row.tenant_code) for row in r]
        logger.info("対象テナント: %d", len(tenants))

        tmpl = (BASE_DIR / "migrations" / "012_add_meta_tenant_tables.sql").read_text("utf-8")
        for tid, tc in tenants:
            schema = f"tenant_{tid:03d}"
            async with engine.begin() as conn:
                await _exec(conn, tmpl.format(schema=schema, schema_raw=schema, tenant_id=tid))
            logger.info("✓ tenant_%03d meta_messages テーブル追加", tid)

        logger.info("=== Meta マイグレーション完了 ===")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
