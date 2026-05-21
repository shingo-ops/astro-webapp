#!/usr/bin/env python3
"""Inventory Sprint 2 (migrations 064-065) 用ランナー。

spec.md v1.1 Sprint 2 / F2 の migration バンドルを適用する。

順序（厳守）:
  1. 064_add_users_is_super_admin.sql       (public.users 列追加 + 初期 super_admin seed)
  2. 065_seed_central_admin_permissions.sql (public.permissions に central.* キー追加)

両方とも public schema のみで完結（テナント schema は触らない）。

冪等:
  - 064: ADD COLUMN IF NOT EXISTS, CREATE INDEX IF NOT EXISTS, 既存 email は UPDATE noop
  - 065: ON CONFLICT (key) DO NOTHING

実行方法（VPS 側）:
  docker compose exec -e TENANT_CODE=highlife-jpn -w /app backend \\
      python /app/scripts/migrate_inventory_sprint2.py

前提:
  - Sprint 1 (056〜063) が適用済み
  - DATABASE_URL が postgresql:// または postgresql+asyncpg:// 形式

関連:
  scripts/migrate_inventory_sprint1.py (Sprint 1 パターン踏襲)
  migrations/064_add_users_is_super_admin.sql
  migrations/065_seed_central_admin_permissions.sql
  .claude-pipeline/spec.md Sprint 2 / F2
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

PUBLIC_MIGRATIONS = [
    "064_add_users_is_super_admin.sql",
    "065_seed_central_admin_permissions.sql",
]


def _split_sql_preserving_do_blocks(sql: str) -> list[str]:
    """DO $$ ... $$ ブロック内のセミコロンを保ったまま SQL を分割する。

    migrate_inventory_sprint1.py からコピペ。
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


def _normalize_db_url(raw: str) -> str:
    """postgresql:// → postgresql+asyncpg:// に正規化（既存パターン踏襲）"""
    if raw.startswith("postgresql+asyncpg://"):
        return raw
    if raw.startswith("postgresql://"):
        return raw.replace("postgresql://", "postgresql+asyncpg://", 1)
    return raw


async def apply_migration(engine, filename: str) -> None:
    path = MIGRATIONS_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Migration file not found: {path}")
    sql = path.read_text("utf-8")
    statements = [
        s.strip() for s in _split_sql_preserving_do_blocks(sql) if s.strip()
    ]
    logger.info("migration %s: %d statements", filename, len(statements))
    async with engine.begin() as conn:
        for stmt in statements:
            await conn.execute(text(stmt))


async def main() -> int:
    raw = os.environ.get("DATABASE_URL", "")
    if not raw:
        logger.error("DATABASE_URL が未設定")
        return 1
    db_url = _normalize_db_url(raw)
    engine = create_async_engine(db_url, echo=False)
    try:
        for filename in PUBLIC_MIGRATIONS:
            try:
                await apply_migration(engine, filename)
                logger.info("OK: %s", filename)
            except Exception as exc:  # noqa: BLE001
                logger.exception("migration %s で例外: %s", filename, exc)
                return 2
    finally:
        await engine.dispose()
    logger.info("Sprint 2 migrations all applied")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
