#!/usr/bin/env python3
"""Phase 1-D Sprint 4 用マイグレーション。

実施内容:
  1. migration 041: 全テナントスキーマの meta_messages に列追加（recipient_id,
     messaging_type, message_tag, sent_by_staff_id, error_code, error_message,
     message_id, seen_at, seen_by_staff_id）+ インデックス 2 本

冪等:
  ADD COLUMN IF NOT EXISTS / CREATE INDEX IF NOT EXISTS のため何度実行しても
  副作用なし（追加件数 0 で完了）。

実行方法（VPS 側、しんごさん作業）:
  docker compose exec backend python /app/scripts/migrate_meta_inbox_phase1d_sprint4.py

前提:
  - Phase 1-D Sprint 1（migration 040 / 042）が適用済み
  - migration 012（meta_messages 本体）が適用済み（既存 Phase 2 で済んでいる前提）

変更履歴:
  2026-04-30: 初版（Phase 1-D Sprint 4）
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

    backend/app/services/tenant.py の同名関数および
    scripts/migrate_meta_inbox_phase1d.py と同じロジック。
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
        logger.info("=== Phase 1-D Sprint 4 マイグレーション開始 ===")

        async with engine.connect() as conn:
            r = await conn.execute(
                text(
                    "SELECT id, tenant_code FROM public.tenants "
                    "WHERE is_active = true ORDER BY id"
                )
            )
            tenants = [(row.id, row.tenant_code) for row in r]
        logger.info("対象テナント: %d", len(tenants))

        tmpl_041 = (MIGRATIONS_DIR / "041_extend_meta_messages.sql").read_text("utf-8")
        for tid, tc in tenants:
            schema = f"tenant_{tid:03d}"
            try:
                async with engine.begin() as conn:
                    # meta_messages テーブル自体が存在しないテナント
                    # （Phase 2 未通過の旧テナント）はスキップする
                    exists = await conn.execute(
                        text(
                            "SELECT 1 FROM pg_tables "
                            "WHERE schemaname = :schema AND tablename = 'meta_messages'"
                        ),
                        {"schema": schema},
                    )
                    if exists.first() is None:
                        logger.warning(
                            "⚠ %s (tenant_code=%s): meta_messages 未作成のためスキップ",
                            schema, tc,
                        )
                        continue
                    await _exec(
                        conn,
                        tmpl_041.format(schema=schema, schema_raw=schema, tenant_id=tid),
                    )
                logger.info("✓ %s (tenant_code=%s) meta_messages 拡張適用", schema, tc)
            except Exception as e:
                logger.error("✗ %s 失敗: %s", schema, e)
                raise

        logger.info("=== Phase 1-D Sprint 4 マイグレーション完了 ===")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
