#!/usr/bin/env python3
"""Phase 1-D Sprint 1 用マイグレーション。

実施内容:
  1. migration 040: 全テナントスキーマに tenant_meta_config テーブルを作成
  2. migration 042: public.permissions に Meta Inbox 系 4 権限を投入し、
     既存テナントの owner/admin に紐付け

冪等:
  両 migration とも IF NOT EXISTS / ON CONFLICT DO NOTHING を使うため、
  何度実行しても副作用は発生しない（INSERT 件数が 0 になるだけ）。

実行方法（VPS 側、しんごさん作業）:
  docker compose exec backend python /app/scripts/migrate_meta_inbox_phase1d.py
  もしくは
  docker compose exec -e DATABASE_URL=... backend \
      python -m scripts.migrate_meta_inbox_phase1d

前提:
  - 既存 Phase 1-A 〜 Phase 1-C の migration が適用済み（roles / role_permissions / staff 等）
  - DATABASE_URL が postgresql:// または postgresql+asyncpg:// 形式で設定されている

変更履歴:
  2026-04-30: 初版（しんごさん依頼、Phase 1-D Sprint 1）
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

    backend/app/services/tenant.py の同名関数と同じロジック。
    """
    # ドル引用タグ（$$ または $tag$ 形式）に対応
    statements: list[str] = []
    buf: list[str] = []
    i = 0
    in_dollar = False
    dollar_tag = ""

    while i < len(sql):
        # ドル引用の開始/終了を検出
        if sql[i] == "$":
            # $tag$ 形式または $$ 形式のタグ抽出
            j = i + 1
            while j < len(sql) and (sql[j].isalnum() or sql[j] == "_"):
                j += 1
            if j < len(sql) and sql[j] == "$":
                tag = sql[i : j + 1]  # $...$
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
        logger.info("=== Phase 1-D Sprint 1 マイグレーション開始 ===")

        # 1. migration 040: per-tenant スキーマに tenant_meta_config を作成
        async with engine.connect() as conn:
            r = await conn.execute(
                text(
                    "SELECT id, tenant_code FROM public.tenants "
                    "WHERE is_active = true ORDER BY id"
                )
            )
            tenants = [(row.id, row.tenant_code) for row in r]
        logger.info("対象テナント: %d", len(tenants))

        tmpl_040 = (MIGRATIONS_DIR / "040_create_tenant_meta_config.sql").read_text("utf-8")
        for tid, tc in tenants:
            schema = f"tenant_{tid:03d}"
            try:
                async with engine.begin() as conn:
                    await _exec(
                        conn,
                        tmpl_040.format(schema=schema, schema_raw=schema, tenant_id=tid),
                    )
                logger.info("✓ %s (tenant_code=%s) tenant_meta_config 適用", schema, tc)
            except Exception as e:
                logger.error("✗ %s 失敗: %s", schema, e)
                raise

        # 2. migration 042: permissions seed + owner/admin への紐付け（public スキーマ）
        sql_042 = (MIGRATIONS_DIR / "042_seed_meta_inbox_permissions.sql").read_text("utf-8")
        async with engine.begin() as conn:
            await _exec(conn, sql_042)
        logger.info("✓ migration 042 (Meta Inbox permissions seed) 適用完了")

        logger.info("=== Phase 1-D Sprint 1 マイグレーション完了 ===")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
