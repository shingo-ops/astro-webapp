#!/usr/bin/env python3
"""Migration 074: english_name カラムを nickname にリネーム。

実施内容:
  全テナントスキーマの leads.english_name を nickname に改名する。
  ADR-015 の定義では「呼び名」が意味的に正しく、"english_name" は誤った名称だった。

冪等:
  english_name カラムが存在する場合のみ RENAME COLUMN を実行。
  nickname が既に存在する場合はスキップ（再実行安全）。

実行方法（VPS 側、docker compose exec 経由）:
  docker compose exec -e TENANT_CODE=highlife-jpn backend \\
      python /app/scripts/migrate_074_rename_english_name_to_nickname.py
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
        logger.info("=== Migration 074 (english_name → nickname リネーム) 開始 ===")

        async with engine.connect() as conn:
            r = await conn.execute(
                text("SELECT id, tenant_code FROM public.tenants WHERE is_active = true ORDER BY id")
            )
            tenants = [(row.id, row.tenant_code) for row in r]
        logger.info("対象テナント: %d", len(tenants))

        for tid, tc in tenants:
            schema = f"tenant_{tid:03d}"
            try:
                async with engine.connect() as conn:
                    # english_name カラムが存在するか確認（冪等チェック）
                    result = await conn.execute(
                        text(
                            "SELECT COUNT(*) FROM information_schema.columns "
                            "WHERE table_schema = :schema AND table_name = 'leads' "
                            "AND column_name = 'english_name'"
                        ),
                        {"schema": schema},
                    )
                    has_english_name = result.scalar() > 0

                if not has_english_name:
                    logger.info("✓ %s (tenant_code=%s): english_name カラムなし → スキップ", schema, tc)
                    continue

                async with engine.begin() as conn:
                    await conn.execute(
                        text(f"ALTER TABLE {schema}.leads RENAME COLUMN english_name TO nickname")
                    )
                logger.info("✓ %s (tenant_code=%s): english_name → nickname リネーム完了", schema, tc)

            except Exception as e:
                logger.error("✗ %s 失敗: %s", schema, e)
                raise

        logger.info("=== Migration 074 完了 ===")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
