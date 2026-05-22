#!/usr/bin/env python3
"""Inventory Sprint 5/6/7 (migrations 066/067/068) 用 catch-up ランナー。

経緯:
  PR #510 で `migrate_inventory_sprint2.py` の deploy.yml 追記が漏れた
  パターンの再発として、Sprint 5/6/7 の migration 実行ステップが
  `.github/workflows/deploy.yml` から漏れていた。
  Sprint 8 (069) のみは `migrate_inventory_sprint8.py` が deploy.yml に
  存在したため適用済だが、066/067/068 が本番 DB 未適用のまま放置。

  本ランナーは 1 本で 066→067→068 を順序適用し、Sprint 8 の前段に
  挿入することで spec.md の論理順序 (056→063→064→065→066→067→068→069→070)
  を deploy.yml 上でも維持する。Sprint 9 (070) は既存
  `migrate_inventory_sprint9.py` を Sprint 8 の後段に追加して適用する。

順序（厳守）:
  1. 066_add_tenant_llm_budgets_notification_dedupe.sql
        public.tenant_llm_budgets.last_hard_stop_notified_at 列 +
        tenant_004 / tenant_006 seed (Sprint 4 申し送り対応)
  2. 067_add_inbound_review_version_and_permissions.sql
        public.discord_inbound_messages.version 列 +
        central.parse_review.{approve,reject} permissions seed
  3. 068_add_inventory_search_indexes.sql
        pg_trgm extension + 12 GIN indexes (検索 API p95 ≤ 500ms)

全 3 migration が public schema のみ完結（テナント schema は触らない）。

冪等:
  - 066: ADD COLUMN IF NOT EXISTS, INSERT ON CONFLICT (tenant_id) DO NOTHING
  - 067: ADD COLUMN IF NOT EXISTS, INSERT ON CONFLICT (key) DO NOTHING
  - 068: CREATE EXTENSION IF NOT EXISTS pg_trgm, CREATE INDEX IF NOT EXISTS
         （pg_trgm 作成権限が無ければ DO ブロックで graceful skip）

実行方法（VPS 側）:
  docker exec -w /app astro-webapp-backend-1 \\
      python /app/scripts/migrate_inventory_sprint5_to_7.py

前提:
  - Sprint 1-4 (056〜065) が適用済み
  - DATABASE_URL が postgresql:// または postgresql+asyncpg:// 形式

関連:
  scripts/migrate_inventory_sprint2.py (パターン踏襲: public schema 連続適用)
  scripts/migrate_inventory_sprint8.py (Sprint 8 単独ランナー、本ランナーの後段)
  scripts/migrate_inventory_sprint9.py (Sprint 9 単独ランナー、Sprint 8 の後段)
  migrations/066_add_tenant_llm_budgets_notification_dedupe.sql
  migrations/067_add_inbound_review_version_and_permissions.sql
  migrations/068_add_inventory_search_indexes.sql
  PR #518 (Sprint 2 deploy.yml 追記漏れ hotfix、同パターン)
  .claude-pipeline/spec.md F5 / F6 / F7

作成日: 2026-05-22
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

# Sprint 5/6/7 の public schema migrations を順序適用
PUBLIC_MIGRATIONS = [
    "066_add_tenant_llm_budgets_notification_dedupe.sql",
    "067_add_inbound_review_version_and_permissions.sql",
    "068_add_inventory_search_indexes.sql",
]


def _split_sql_preserving_do_blocks(sql: str) -> list[str]:
    """DO $$ ... $$ ブロック内のセミコロンを保ったまま SQL を分割する。

    migrate_inventory_sprint2.py からコピペ。
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
    logger.info("Sprint 5/6/7 migrations all applied (066/067/068)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
