#!/usr/bin/env python3
"""Inventory Sprint 9 (migration 070) 用ランナー。

spec.md v1.2 Sprint 9 / F9 の migration バンドルを適用する。

順序:
  1. 070_add_spreadsheet_phase.sql  (public.tenant_settings 新設 + 既存テナント seed)

migration 070 は `public.tenant_settings` テーブルを作り、同時に
public.permissions に phase.switch を seed する（1 ファイルで完結）。

実行方法 (VPS 側):
  docker compose exec -e TENANT_CODE=highlife-jpn -w /app backend \
      python /app/scripts/migrate_inventory_sprint9.py

前提:
  - Sprint 1-8 (056〜069) が適用済み
  - DATABASE_URL が postgresql:// または postgresql+asyncpg:// 形式

冪等:
  - 070: CREATE TABLE IF NOT EXISTS / ADD COLUMN IF NOT EXISTS /
        ON CONFLICT (key|tenant_id) DO NOTHING

関連:
  scripts/migrate_inventory_sprint1.py (パターン踏襲)
  scripts/migrate_inventory_sprint8.py (パターン踏襲)
  migrations/070_add_spreadsheet_phase.sql
  .claude-pipeline/spec.md Sprint 9 / F9 (v1.2)
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

SPRINT9_MIGRATIONS = [
    "070_add_spreadsheet_phase.sql",
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
    statements = [s.strip() for s in _split_sql_preserving_do_blocks(sql) if s.strip()]
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
        for filename in SPRINT9_MIGRATIONS:
            try:
                await apply_migration(engine, filename)
                logger.info("OK: %s", filename)
            except Exception as exc:  # noqa: BLE001
                logger.exception("migration %s で例外: %s", filename, exc)
                return 2
    finally:
        await engine.dispose()
    logger.info("Sprint 9 migrations all applied")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
