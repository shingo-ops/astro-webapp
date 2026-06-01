#!/usr/bin/env python3
"""Migration 091 + 092: Discord B2C 顧客メッセージング用 DB 拡張。

実施内容:
  091: {tenant_NNN}.leads に discord_user_id / discord_dm_channel_id カラム + インデックスを追加
  092: {tenant_NNN}.meta_messages に Discord 用 Partial Index を追加

冪等:
  ADD COLUMN IF NOT EXISTS / CREATE INDEX IF NOT EXISTS で複数回実行しても安全。

実行方法（VPS 側、docker compose exec 経由）:
  docker compose exec backend python scripts/migrate_discord_b2c.py
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


async def main() -> None:
    url = os.getenv("DATABASE_URL")
    if not url:
        logger.error("DATABASE_URL not set")
        sys.exit(1)
    if url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://"):]

    engine = create_async_engine(url, echo=False)

    try:
        logger.info("=== Migration 091+092 (Discord B2C メッセージング) 開始 ===")

        async with engine.connect() as conn:
            r = await conn.execute(
                text("SELECT id, tenant_code FROM public.tenants WHERE is_active = true ORDER BY id")
            )
            tenants = [(row.id, row.tenant_code) for row in r]
        logger.info("対象テナント: %d", len(tenants))

        for tid, tc in tenants:
            schema = f"tenant_{tid:03d}"
            try:
                async with engine.begin() as conn:
                    # --- Migration 091: leads に discord カラム追加 ---
                    await conn.execute(text(f"""
                        ALTER TABLE {schema}.leads
                        ADD COLUMN IF NOT EXISTS discord_user_id       VARCHAR(50),
                        ADD COLUMN IF NOT EXISTS discord_dm_channel_id VARCHAR(50)
                    """))
                    await conn.execute(text(f"""
                        CREATE INDEX IF NOT EXISTS idx_leads_discord_user_id
                        ON {schema}.leads (tenant_id, discord_user_id)
                        WHERE discord_user_id IS NOT NULL
                    """))
                    await conn.execute(text(f"""
                        CREATE UNIQUE INDEX IF NOT EXISTS idx_leads_discord_source_unique
                        ON {schema}.leads (source)
                        WHERE source LIKE 'discord:%'
                    """))

                    # --- Migration 092: meta_messages に Discord インデックス追加 ---
                    await conn.execute(text(f"""
                        CREATE INDEX IF NOT EXISTS idx_meta_messages_discord
                        ON {schema}.meta_messages (tenant_id, platform, lead_id)
                        WHERE platform = 'discord'
                    """))

                logger.info("✓ %s (tenant_code=%s): Discord B2C カラム + インデックス適用完了", schema, tc)
            except Exception as e:
                logger.error("✗ %s 失敗: %s", schema, e)
                raise

        logger.info("=== Migration 091+092 完了 ===")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
