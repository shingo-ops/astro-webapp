#!/usr/bin/env python3
"""
Phase 2 マイグレーションスクリプト（販売・財務プロセス）。

既存の全テナントに対して Phase 2 テーブル（products, quotes, invoices,
shipping_zones, shipping_rates, + orders拡張）を追加する。

実行方法（VPS側、backendコンテナ内）:
  docker compose exec backend python /app/scripts/migrate_phase2.py

冪等性: CREATE TABLE IF NOT EXISTS / ADD COLUMN IF NOT EXISTS /
        ON CONFLICT DO NOTHING を使用。複数回実行しても安全。

変更履歴:
  2026-04-17: 初版作成
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

from app.services.tenant import seed_system_roles

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    logger.error("DATABASE_URL 環境変数が設定されていません")
    sys.exit(1)

BASE_DIR = Path(__file__).resolve().parent.parent
PERMISSIONS_SQL = BASE_DIR / "migrations" / "004_add_phase2_permissions.sql"
TENANT_TEMPLATE_SQL = BASE_DIR / "migrations" / "005_add_phase2_tenant_tables.sql"


def _split_sql_preserving_do_blocks(sql: str) -> list[str]:
    """DO $$ ... END $$ ブロック内の ; を保持したまま SQL をステートメント単位に分割。"""
    result: list[str] = []
    buffer: list[str] = []
    in_dollar_block = False
    i = 0
    while i < len(sql):
        if sql[i:i + 2] == "$$":
            in_dollar_block = not in_dollar_block
            buffer.append("$$")
            i += 2
            continue
        ch = sql[i]
        if ch == ";" and not in_dollar_block:
            result.append("".join(buffer))
            buffer = []
        else:
            buffer.append(ch)
        i += 1
    if buffer:
        result.append("".join(buffer))
    return result


async def _execute_multi_statement(conn, sql: str) -> None:
    for stmt in _split_sql_preserving_do_blocks(sql):
        stmt = stmt.strip()
        if stmt:
            await conn.execute(text(stmt))


async def apply_permissions(engine) -> None:
    sql = PERMISSIONS_SQL.read_text(encoding="utf-8")
    async with engine.begin() as conn:
        await _execute_multi_statement(conn, sql)
    logger.info("✓ Phase 2 パーミッション追加完了（16件）")


async def get_active_tenants(engine) -> list[tuple[int, str]]:
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT id, tenant_code FROM public.tenants WHERE is_active = true ORDER BY id")
        )
        return [(row.id, row.tenant_code) for row in result]


async def apply_tenant_migration(engine, tenant_id: int) -> None:
    template = TENANT_TEMPLATE_SQL.read_text(encoding="utf-8")
    schema_name = f"tenant_{tenant_id:03d}"
    sql = template.format(schema=schema_name, schema_raw=schema_name, tenant_id=tenant_id)
    async with engine.begin() as conn:
        await _execute_multi_statement(conn, sql)
    logger.info("✓ tenant_%03d Phase 2 テーブル追加完了", tenant_id)


async def reseed_roles(engine, tenant_id: int) -> None:
    """ロールの権限を再シードして新権限を反映する。"""
    schema_name = f"tenant_{tenant_id:03d}"
    async with engine.begin() as conn:
        await conn.execute(text(f"SET search_path = {schema_name}, public"))
        await conn.execute(text(f"SET app.tenant_id = '{tenant_id}'"))
        await seed_system_roles(conn, tenant_id, schema_name)
    logger.info("✓ tenant_%03d ロール権限を再シード", tenant_id)


async def main() -> None:
    url = DATABASE_URL
    if url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://"):]

    engine = create_async_engine(url, echo=False)
    try:
        logger.info("=== Phase 2 マイグレーション開始 ===")
        await apply_permissions(engine)

        tenants = await get_active_tenants(engine)
        logger.info("対象テナント数: %d", len(tenants))

        for tenant_id, tenant_code in tenants:
            logger.info("--- tenant_id=%d (%s) ---", tenant_id, tenant_code)
            await apply_tenant_migration(engine, tenant_id)
            await reseed_roles(engine, tenant_id)

        logger.info("=== Phase 2 マイグレーション完了 ===")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
