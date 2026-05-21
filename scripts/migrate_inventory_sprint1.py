#!/usr/bin/env python3
"""Inventory Sprint 1 (migrations 056-063) 用ランナー。

spec.md v1.1 Sprint 1 / F1 の migration バンドルを適用する。

順序（厳守）:
  1. public schema 系（056〜062）: 全体で 1 回のみ実行（マーケットプレイス型 A6）
  2. tenant_xxx schema 系（063）: 全テナントに対し各 1 回実行

冪等:
  全 migration が CREATE TABLE IF NOT EXISTS / ADD COLUMN IF NOT EXISTS /
  INSERT ... ON CONFLICT DO NOTHING で構成されているため、何度実行しても安全。

実行方法（VPS 側）:
  docker compose exec -e TENANT_CODE=highlife-jpn -w /app backend \\
      python /app/scripts/migrate_inventory_sprint1.py

  もしくは GitHub Actions の run-*-migration.yml 経由。

前提:
  - migration 055 までが全テナントに適用済み
  - DATABASE_URL が postgresql:// または postgresql+asyncpg:// 形式

関連:
  scripts/migrate_adr015_lead_foundation.py (パターン踏襲)
  migrations/056_add_suppliers_type_and_promote_public.sql 〜 063_*.sql
  .claude-pipeline/spec.md Sprint 1 / F1
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

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = BASE_DIR / "migrations"

# public schema migrations: 一括で 1 回のみ
PUBLIC_MIGRATIONS = [
    "056_add_suppliers_type_and_promote_public.sql",
    "057_create_supplier_aliases.sql",
    "058_create_knowledge_rules.sql",
    "059_create_discord_inbound_messages.sql",
    "060_create_supplier_discord_routing.sql",
    "061_create_tcg_and_dex_masters.sql",
    "062_create_inventory_movements_and_budget.sql",
]
# tenant_xxx schema migrations: 全テナントループ
TENANT_MIGRATIONS = [
    "063_tenant_rbac_extensions.sql",
]


def _split_sql_preserving_do_blocks(sql: str) -> list[str]:
    """DO $$ ... $$ ブロック内のセミコロンを保ったまま SQL を分割する。

    migrate_adr015_lead_foundation.py からコピペ。
    """
    statements: list[str] = []
    buf: list[str] = []
    i = 0
    in_dollar = False
    dollar_tag = ""

    while i < len(sql):
        if sql[i] == "$":
            j = i + 1
            while j < len(sql) and (sql[j].isalnum() or sql[j] == "_"):
                j += 1
            if j < len(sql) and sql[j] == "$":
                tag = sql[i : j + 1]
                if not in_dollar:
                    in_dollar = True
                    dollar_tag = tag
                    buf.append(tag)
                    i = j + 1
                    continue
                elif tag == dollar_tag:
                    in_dollar = False
                    dollar_tag = ""
                    buf.append(tag)
                    i = j + 1
                    continue

        if sql[i] == ";" and not in_dollar:
            statements.append("".join(buf))
            buf = []
        else:
            buf.append(sql[i])
        i += 1

    if buf:
        statements.append("".join(buf))
    return statements


async def _exec(conn, sql: str) -> None:
    for stmt in _split_sql_preserving_do_blocks(sql):
        stmt = stmt.strip()
        if stmt:
            # exec_driver_sql で SQLAlchemy のバインドパラメータ解釈を回避
            # （SQL コメント内の `:true` 等で誤検知が起きる）
            await conn.exec_driver_sql(stmt)


async def _apply_public_migration(engine, filename: str) -> None:
    path = MIGRATIONS_DIR / filename
    sql = path.read_text("utf-8")
    async with engine.begin() as conn:
        await _exec(conn, sql)
    logger.info("✓ public migration 適用: %s", filename)


async def _apply_tenant_migration(engine, filename: str, tenants: list[tuple[int, str]]) -> None:
    path = MIGRATIONS_DIR / filename
    tmpl = path.read_text("utf-8")
    # migrate_adr015 と同じく {schema} / {schema_raw} / {tenant_id} プレースホルダ
    # 形式の場合は置換、それ以外（DO ブロック内で pg_namespace 走査する）はそのまま実行。
    if "{schema}" in tmpl or "{schema_raw}" in tmpl or "{tenant_id}" in tmpl:
        for tid, tc in tenants:
            schema = f"tenant_{tid:03d}"
            try:
                async with engine.begin() as conn:
                    await _exec(
                        conn,
                        tmpl.replace("{schema}", schema)
                        .replace("{schema_raw}", schema)
                        .replace("{tenant_id}", str(tid)),
                    )
                logger.info("✓ %s (tenant_code=%s) %s 適用", schema, tc, filename)
            except Exception as e:
                logger.error("✗ %s %s 失敗: %s", schema, filename, e)
                raise
    else:
        # pg_namespace 走査型の migration は 1 回だけ実行（全テナント自走）
        async with engine.begin() as conn:
            await _exec(conn, tmpl)
        logger.info("✓ tenant-loop migration 適用 (pg_namespace 走査型): %s", filename)


async def main() -> None:
    url = os.getenv("DATABASE_URL")
    if not url:
        logger.error("DATABASE_URL not set")
        sys.exit(1)
    if url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://"):]
    engine = create_async_engine(url, echo=False)

    try:
        logger.info("=== Inventory Sprint 1 (056-063) 開始 ===")

        async with engine.connect() as conn:
            r = await conn.execute(
                text(
                    "SELECT id, tenant_code FROM public.tenants "
                    "WHERE is_active = true ORDER BY id"
                )
            )
            tenants = [(row.id, row.tenant_code) for row in r]
        logger.info("対象テナント: %d", len(tenants))

        # Step 1: public schema migrations
        logger.info("--- Step 1: public schema migrations (1 回のみ) ---")
        for fn in PUBLIC_MIGRATIONS:
            await _apply_public_migration(engine, fn)

        # Step 2: tenant_xxx schema migrations
        logger.info("--- Step 2: tenant_xxx schema migrations (全テナントループ) ---")
        for fn in TENANT_MIGRATIONS:
            await _apply_tenant_migration(engine, fn, tenants)

        logger.info("=== Inventory Sprint 1 完了 ===")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
