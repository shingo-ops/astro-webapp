#!/usr/bin/env python3
"""Migration 079: バディ・バッジ機能のテナントスキーマ完全削除。

対象テーブル (per-tenant schema):
  - buddy_feedbacks    (Buddy フィードバック)
  - buddy_pairs        (Buddy ペアリング)
  - user_badges        (ユーザーバッジ獲得)
  - badge_definitions  (バッジ定義)

対象カラム (per-tenant schema):
  - staff_ui_preferences.show_buddy_menu

すべて CASCADE で関連 RLS ポリシーも削除される。
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

TENANT_SQL = """
DROP TABLE IF EXISTS {schema}.buddy_feedbacks CASCADE;
DROP TABLE IF EXISTS {schema}.buddy_pairs CASCADE;
DROP TABLE IF EXISTS {schema}.user_badges CASCADE;
DROP TABLE IF EXISTS {schema}.badge_definitions CASCADE;
ALTER TABLE IF EXISTS {schema}.staff_ui_preferences DROP COLUMN IF EXISTS show_buddy_menu;
"""


async def main() -> None:
    url = DATABASE_URL
    if url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://"):]
    engine = create_async_engine(url, echo=False)
    try:
        logger.info("=== Migration 079: buddy/badge 削除開始 ===")

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

        logger.info("=== Migration 079: buddy/badge 削除完了 ===")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
