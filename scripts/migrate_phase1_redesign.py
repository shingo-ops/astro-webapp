#!/usr/bin/env python3
"""
Phase 1 再設計マイグレーションスクリプト。

新仕様3冊（2026-04-22版）を既存astro-webappに反映する。
migration 014〜022 を適切な順序で適用する。

構成:
    1. public schema 対象（全テナント共通、1回のみ実行）:
       - 014 current_tenant_id() 関数定義
       - 018 permissions 拡張 + menu.* 19件seed
    2. tenant schema 対象（各テナントごとにテンプレート適用）:
       - 015 customers 系スキーマ置換
       - 016 customers 系 RLS
       - 017 quotes/invoices FK 再構築
       - 019 staff 系テーブル + customers.sales_rep_id FK 付与
       - 020 bots + v_senders ビュー
       - 021 新6役割seed + role_permissions マトリクス
       - 022 staff/bots 系 RLS

実行方法（VPS側）:
    docker compose exec backend python /app/scripts/migrate_phase1_redesign.py

変更履歴:
    2026-04-23: 初版作成（Phase 1 再設計）
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    logger.error("DATABASE_URL 環境変数が設定されていません")
    sys.exit(1)

BASE_DIR = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = BASE_DIR / "migrations"

# public schema 対象（1回のみ実行）
PUBLIC_MIGRATIONS = [
    "014_create_current_tenant_id_function.sql",
    "018_extend_permissions_with_menu_grain.sql",
]

# tenant schema 対象（全テナントにテンプレート適用、順序厳守）
TENANT_TEMPLATE_MIGRATIONS = [
    "015_replace_customers_schema.sql",
    "016_customers_rls_policies.sql",
    "017_rewire_quotes_invoices_to_new_customers.sql",
    "019_create_staff_tables.sql",
    "020_create_bots_and_senders_view.sql",
    "021_seed_roles_and_role_permissions.sql",
    "022_staff_bots_rls_policies.sql",
    "023_fix_system_admin_is_system_flag.sql",
]


def _split_sql_preserving_do_blocks(sql: str) -> list[str]:
    """
    DO $$ ... END $$ ブロック内の ; を保持したまま SQL をステートメント単位に分割。

    asyncpg はprepared statementに複数文を渡せないため、個別実行が必要。
    scripts/migrate_phase1.py と同じロジック。
    """
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
    """複数文SQLを DO $$ ブロックを保持しつつ1文ずつ実行する。"""
    for stmt in _split_sql_preserving_do_blocks(sql):
        stmt = stmt.strip()
        if stmt:
            await conn.execute(text(stmt))


async def apply_public_migration(engine, filename: str) -> None:
    """public schema 対象の migration を適用（非テンプレート、1回きり）。"""
    sql_path = MIGRATIONS_DIR / filename
    sql = sql_path.read_text(encoding="utf-8")
    async with engine.begin() as conn:
        await _execute_multi_statement(conn, sql)
    logger.info("✓ public migration 適用: %s", filename)


async def get_active_tenants(engine) -> list[tuple[int, str]]:
    """有効なテナント一覧を返す。"""
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT id, tenant_code FROM public.tenants WHERE is_active = true ORDER BY id")
        )
        return [(row.id, row.tenant_code) for row in result]


def build_tenant_sql(filename: str, tenant_id: int) -> str:
    """テンプレートSQLに schema 等を埋め込む。"""
    template = (MIGRATIONS_DIR / filename).read_text(encoding="utf-8")
    schema_name = f"tenant_{tenant_id:03d}"
    return template.format(
        schema=schema_name,
        schema_raw=schema_name,
        tenant_id=tenant_id,
    )


async def apply_tenant_migration(engine, tenant_id: int, filename: str) -> None:
    """
    テナント単位でテンプレート migration を適用。

    セッションに search_path と app.tenant_id を設定するのは、021 で行う
    role_permissions の INSERT が RLS 有効な {schema}.roles を SELECT するため。
    設定していないと current_setting('app.tenant_id', true)::INTEGER が NULL
    となり、USING 句で全行が不可視になり、INSERT が空振りする。
    scripts/migrate_phase1.py の seed_system_roles() と同じ対応。
    """
    sql = build_tenant_sql(filename, tenant_id)
    schema_name = f"tenant_{tenant_id:03d}"
    async with engine.begin() as conn:
        await conn.execute(text(f"SET search_path = {schema_name}, public"))
        await conn.execute(text(f"SET app.tenant_id = '{tenant_id}'"))
        await _execute_multi_statement(conn, sql)
    logger.info("  ✓ tenant_%03d に %s 適用完了", tenant_id, filename)


async def main() -> None:
    logger.info("=" * 72)
    logger.info("Phase 1 再設計マイグレーション開始")
    logger.info("対象 migration: 014 / 018 (public) + 015-017, 019-022 (tenant テンプレート)")
    logger.info("=" * 72)

    engine = create_async_engine(DATABASE_URL, echo=False)
    try:
        # === Step 1: public schema 対象 ===
        logger.info("[Step 1] public schema 対象 migration を適用")
        for filename in PUBLIC_MIGRATIONS:
            await apply_public_migration(engine, filename)

        # === Step 2: 全テナントにテンプレート適用 ===
        tenants = await get_active_tenants(engine)
        logger.info("[Step 2] 有効テナント %d 件: %s", len(tenants), [t[1] for t in tenants])

        for tenant_id, tenant_code in tenants:
            logger.info("--- tenant_%03d (%s) への適用開始 ---", tenant_id, tenant_code)
            for filename in TENANT_TEMPLATE_MIGRATIONS:
                await apply_tenant_migration(engine, tenant_id, filename)
            logger.info("--- tenant_%03d 完了 ---", tenant_id)

        logger.info("=" * 72)
        logger.info("✓ Phase 1 再設計マイグレーション完了")
        logger.info("=" * 72)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
