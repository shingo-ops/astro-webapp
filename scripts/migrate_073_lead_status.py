#!/usr/bin/env python3
"""Migration 073: LeadStatus 整理 — 受信箱タブを商談進捗ベースに変更。

実施内容:
  全テナントスキーマの leads.status を新しい値に移行する。
    - '案件化' → '商談中'
    - 'AI対応中' / 'コンタクト中' / '提案中' → '新規'
    - '保留' → '追客（短期）'

冪等:
  WHERE status = '...' 条件付きの UPDATE なので何度実行しても安全。

実行方法（VPS 側、docker compose exec 経由）:
  docker compose exec -e TENANT_CODE=highlife-jpn backend \\
      python /app/scripts/migrate_073_lead_status.py
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
        logger.info("=== Migration 073 (lead status 整理) 開始 ===")

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
                    r1 = await conn.execute(
                        text(f"UPDATE {schema}.leads SET status = '商談中', updated_at = NOW() WHERE status = '案件化'")
                    )
                    r2 = await conn.execute(
                        text(f"UPDATE {schema}.leads SET status = '新規', updated_at = NOW() WHERE status = ANY(ARRAY['AI対応中', 'コンタクト中', '提案中'])")
                    )
                    r3 = await conn.execute(
                        text(f"UPDATE {schema}.leads SET status = '追客（短期）', updated_at = NOW() WHERE status = '保留'")
                    )
                    total = r1.rowcount + r2.rowcount + r3.rowcount
                logger.info(
                    "✓ %s (tenant_code=%s): 案件化→商談中=%d, 廃止値→新規=%d, 保留→追客=%d",
                    schema, tc, r1.rowcount, r2.rowcount, r3.rowcount,
                )
            except Exception as e:
                logger.error("✗ %s 失敗: %s", schema, e)
                raise

        logger.info("=== Migration 073 完了 ===")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
