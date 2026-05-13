#!/usr/bin/env python3
"""ADR-026 / Migration 052 用マイグレーションランナー。

実施内容:
  全 active tenant の `tenant_NNN.meta_messages.message_id` を
  `VARCHAR(100)` → `TEXT` に拡張する。
  Instagram の mid（base64 多重エンコードで 150〜200 文字超）が
  既存定義で truncation エラーになる事象（2026-05-13 切り分け済）の解消。

冪等:
  information_schema.columns で `data_type='text'` を事前確認し、
  既に TEXT 化されているテナントは skip。複数回実行しても安全。

実行方法:

  本適用（VPS 側、Hitoshi 作業）:
    docker compose exec backend python /app/scripts/migrate_meta_messages_message_id_to_text.py

  dry-run（適用対象テナント一覧と現在の data_type を表示するのみ）:
    docker compose exec backend python /app/scripts/migrate_meta_messages_message_id_to_text.py --dry-run

前提:
  - migration 013 + 041（meta_messages.message_id 列の作成・拡張）が全テナントに
    適用済み
  - DATABASE_URL が postgresql:// または postgresql+asyncpg:// 形式

確定済み判断（ADR-026 Open Question / Hitoshi 即決 2026-05-13）:
  - Q-026.1: 型 → TEXT
  - Q-026.2: down で長さ超過行 → 失敗させる（truncate しない）
  - Q-026.3: 冪等性 → information_schema で data_type='text' 確認、TEXT なら skip
"""
from __future__ import annotations

import argparse
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
MIGRATION_SQL = MIGRATIONS_DIR / "052_alter_meta_messages_message_id_to_text.sql"


def _split_sql_preserving_do_blocks(sql: str) -> list[str]:
    """DO $$ ... $$ ブロック内のセミコロンを保ったまま SQL を分割する。

    backend/app/services/tenant.py / scripts/migrate_meta_page_routing.py /
    scripts/migrate_adr021_remove_confirmed_status.py の同名関数と同じロジック。
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
            await conn.exec_driver_sql(stmt)


async def _fetch_current_data_type(conn, schema: str) -> str | None:
    """指定 schema の meta_messages.message_id 列の data_type を返す。

    存在しない場合は None。
    """
    r = await conn.execute(
        text(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_schema = :schema "
            "  AND table_name = 'meta_messages' "
            "  AND column_name = 'message_id'"
        ),
        {"schema": schema},
    )
    row = r.first()
    return row[0] if row else None


async def _list_active_tenants(engine) -> list[tuple[int, str]]:
    async with engine.connect() as conn:
        r = await conn.execute(
            text(
                "SELECT id, tenant_code FROM public.tenants "
                "WHERE is_active = true ORDER BY id"
            )
        )
        return [(row.id, row.tenant_code) for row in r]


async def main_async(dry_run: bool) -> int:
    url = os.getenv("DATABASE_URL")
    if not url:
        logger.error("DATABASE_URL not set")
        return 1
    if url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://"):]

    if not MIGRATION_SQL.exists():
        logger.error("migration SQL not found: %s", MIGRATION_SQL)
        return 1

    tmpl = MIGRATION_SQL.read_text("utf-8")
    engine = create_async_engine(url, echo=False)
    exit_code = 0

    try:
        mode = "DRY-RUN" if dry_run else "APPLY"
        logger.info("=== ADR-026 / Migration 052 (%s) 開始 ===", mode)

        tenants = await _list_active_tenants(engine)
        logger.info("対象テナント: %d", len(tenants))

        for tid, tc in tenants:
            schema = f"tenant_{tid:03d}"
            try:
                # 1) 現在の data_type を確認
                async with engine.connect() as conn:
                    current_type = await _fetch_current_data_type(conn, schema)

                if current_type is None:
                    logger.warning(
                        "- %s (tenant_code=%s) skip: meta_messages.message_id 列が存在しない",
                        schema, tc,
                    )
                    continue

                if current_type == "text":
                    logger.info(
                        "- %s (tenant_code=%s) skip: 既に TEXT (data_type=%s)",
                        schema, tc, current_type,
                    )
                    continue

                if dry_run:
                    logger.info(
                        "[dry-run] %s (tenant_code=%s): 適用予定 (data_type=%s → text)",
                        schema, tc, current_type,
                    )
                    continue

                # 2) 実適用
                logger.info(
                    "→ %s (tenant_code=%s): ALTER (data_type=%s → text)",
                    schema, tc, current_type,
                )
                async with engine.begin() as conn:
                    await _exec(conn, tmpl.replace("{schema}", schema))

                # 3) 適用後の data_type を再取得・検証
                async with engine.connect() as conn:
                    new_type = await _fetch_current_data_type(conn, schema)

                if new_type != "text":
                    logger.error(
                        "✗ %s (tenant_code=%s) 適用後検証失敗: data_type=%s (expected 'text')",
                        schema, tc, new_type,
                    )
                    exit_code = 1
                else:
                    logger.info(
                        "✓ %s (tenant_code=%s) message_id TEXT 化完了",
                        schema, tc,
                    )
            except Exception as e:
                logger.error("✗ %s 失敗: %s", schema, e)
                exit_code = 1
                raise

        logger.info("=== ADR-026 / Migration 052 (%s) 完了 (exit=%d) ===", mode, exit_code)
        return exit_code
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "ADR-026 / Migration 052: meta_messages.message_id を "
            "VARCHAR(100) → TEXT に拡張するランナー。"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "適用対象テナント一覧と現在の data_type を出力するのみで、"
            "実際の ALTER は実行しない。"
        ),
    )
    args = parser.parse_args()
    exit_code = asyncio.run(main_async(dry_run=args.dry_run))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
