#!/usr/bin/env python3
"""Migration 009 runner: 全テナントに Phase 4 テーブルを追加。

追加テーブル:
  - notification_channels  (通知チャネル設定)
  - notification_logs      (通知送信ログ)
  - staff_reports          (スタッフレポート)
  - archives               (アーカイブ)

冪等:
  CREATE TABLE IF NOT EXISTS + INSERT ON CONFLICT DO NOTHING で保証。

実行方法（VPS 側）:
  docker exec -w /app astro-webapp-backend-1 python scripts/migrate_009_phase4_tenant_tables.py

備考:
  - tenant_006 は 2026-05-15 に手動適用済み（スキップされる）
  - 新テナント作成は scripts/setup_tenant.py 経由で自動適用
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

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

MIGRATION_SQL = _APP_ROOT / "migrations" / "009_add_phase4_tenant_tables.sql"


def _make_engine():
    raw = os.environ["DATABASE_URL"]
    url = raw.replace("postgresql://", "postgresql+asyncpg://", 1)
    return create_async_engine(url, echo=False)


def split_sql(sql: str) -> list[str]:
    """Split SQL into individual statements, respecting dollar-quoted blocks ($$...$$)."""
    statements: list[str] = []
    buf: list[str] = []
    in_dollar_quote = False
    i = 0
    while i < len(sql):
        two = sql[i : i + 2]
        if two == "$$":
            in_dollar_quote = not in_dollar_quote
            buf.append("$$")
            i += 2
        elif sql[i] == ";" and not in_dollar_quote:
            stmt = "".join(buf).strip()
            if stmt:
                statements.append(stmt)
            buf = []
            i += 1
        else:
            buf.append(sql[i])
            i += 1
    # trailing statement without semicolon
    stmt = "".join(buf).strip()
    if stmt:
        statements.append(stmt)
    return statements


async def run() -> None:
    engine = _make_engine()
    tmpl = MIGRATION_SQL.read_text()

    async with engine.begin() as conn:
        rows = await conn.execute(
            text("SELECT id FROM public.tenants WHERE is_active = TRUE ORDER BY id")
        )
        tenant_ids = [row[0] for row in rows.fetchall()]

    for tid in tenant_ids:
        schema = f"tenant_{tid:03d}"
        sql = (
            tmpl.replace("{schema}", schema)
                .replace("{schema_raw}", schema)
                .replace("{tenant_id}", str(tid))
        )
        try:
            async with engine.begin() as conn:
                for stmt in split_sql(sql):
                    if stmt.startswith("--"):
                        continue
                    try:
                        await conn.execute(text(stmt))
                    except Exception as e:
                        msg = str(e).lower()
                        if "already exists" in msg or "duplicate" in msg:
                            pass
                        else:
                            raise
            log.info("✓ %s migration 009 applied", schema)
        except Exception as exc:
            log.error("✗ %s migration 009 FAILED: %s", schema, exc)
            raise

    await engine.dispose()
    log.info("Done. %d tenants processed.", len(tenant_ids))


if __name__ == "__main__":
    asyncio.run(run())
