#!/usr/bin/env python3
"""Phase 1-E Follow-up F16-S6 用マイグレーション。

実施内容:
  1. migration 043: public.meta_page_routing テーブル作成（公開ルーティング表）
  2. migration 044: 全テナントスキーマに同期トリガ + backfill

冪等:
  - 043 は CREATE TABLE / INDEX IF NOT EXISTS
  - 044 は CREATE OR REPLACE FUNCTION / DROP+CREATE TRIGGER / INSERT ... ON CONFLICT
  何度実行しても副作用は発生しない。

実行方法（VPS 側、しんごさん作業）:
  docker compose exec backend python /app/scripts/migrate_meta_page_routing.py

前提:
  - migration 040 (tenant_meta_config) が全テナントに適用済み
  - DATABASE_URL が postgresql:// または postgresql+asyncpg:// 形式
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

BASE_DIR = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = BASE_DIR / "migrations"


def _split_sql_preserving_do_blocks(sql: str) -> list[str]:
    """DO $$ ... $$ ブロック内のセミコロンを保ったまま SQL を分割する。

    backend/app/services/tenant.py / scripts/migrate_meta_inbox_phase1d.py の同名関数と同じロジック。
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
            await conn.execute(text(stmt))


async def main() -> None:
    url = os.getenv("DATABASE_URL")
    if not url:
        logger.error("DATABASE_URL not set")
        sys.exit(1)
    if url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://"):]
    engine = create_async_engine(url, echo=False)

    try:
        logger.info("=== Phase 1-E F16-S6 マイグレーション開始 ===")

        # 1. migration 043: public.meta_page_routing テーブル作成
        sql_043 = (MIGRATIONS_DIR / "043_create_meta_page_routing.sql").read_text("utf-8")
        async with engine.begin() as conn:
            await _exec(conn, sql_043)
        logger.info("✓ migration 043 (public.meta_page_routing) 適用完了")

        # 2. migration 044: 全テナントへトリガ + backfill
        async with engine.connect() as conn:
            r = await conn.execute(
                text(
                    "SELECT id, tenant_code FROM public.tenants "
                    "WHERE is_active = true ORDER BY id"
                )
            )
            tenants = [(row.id, row.tenant_code) for row in r]
        logger.info("対象テナント: %d", len(tenants))

        tmpl_044 = (MIGRATIONS_DIR / "044_create_meta_page_routing_trigger.sql").read_text("utf-8")
        for tid, tc in tenants:
            schema = f"tenant_{tid:03d}"
            try:
                async with engine.begin() as conn:
                    await _exec(
                        conn,
                        tmpl_044.format(schema=schema, schema_raw=schema, tenant_id=tid),
                    )
                logger.info("✓ %s (tenant_code=%s) トリガ + backfill 適用", schema, tc)
            except Exception as e:
                logger.error("✗ %s 失敗: %s", schema, e)
                raise

        logger.info("=== Phase 1-E F16-S6 マイグレーション完了 ===")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
