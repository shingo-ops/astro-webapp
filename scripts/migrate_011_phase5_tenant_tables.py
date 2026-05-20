#!/usr/bin/env python3
"""Migration 011 runner: 全テナントに Phase 5 拡張機能テーブルを追加。

追加テーブル (per-tenant schema):
  - shifts             (シフト管理)
  - buddy_pairs        (Buddy ペアリング)
  - buddy_feedbacks    (Buddy フィードバック)
  - badge_definitions  (バッジ定義)
  - user_badges        (ユーザーバッジ獲得)
  - erp_sync_logs      (ERP 連携ログ)

すべて RLS (tenant_isolation_* policy) 設定済。

冪等:
  CREATE TABLE IF NOT EXISTS + CREATE POLICY 内で pg_policies 存在確認 で保証。

実行方法（VPS 側、backend コンテナ内）:
  docker exec -w /app astro-webapp-backend-1 python scripts/migrate_011_phase5_tenant_tables.py

なぜ必要か:
  migration 011 は Phase 5 (2026-04-17) で起案されたが、
  deploy.yml に展開 runner ステップが追加されておらず、新規テナント作成時の
  catch-up migration (scripts/setup_tenant.py の tenant_migrations リスト)
  にも入っていなかった。結果、全テナントで `shifts` テーブルが不在となり、
  `/api/v1/shifts` 等の Phase 5 API が HTTP 500 ("relation \"shifts\" does
  not exist") を返す状態が継続していた。本 runner は遅延 catch-up として
  全 active テナントに migration 011 を冪等適用する。

備考:
  - migrate_009_phase4_tenant_tables.py と同パターン (split_sql で `$$`
    dollar-quoted block を保護、`already exists` / `duplicate` は黙殺)
  - tenant_006 (Meta App Review 用) を含む全 active テナントに適用される
  - 新規テナント作成は scripts/setup_tenant.py 経由で同じ migration が
    自動適用される (本 PR で tenant_migrations リストに 011 を追加)
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

MIGRATION_SQL = _APP_ROOT / "migrations" / "011_add_phase5_tenant_tables.sql"


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
                    try:
                        await conn.execute(text(stmt))
                    except Exception as e:
                        msg = str(e).lower()
                        if "already exists" in msg or "duplicate" in msg:
                            pass
                        else:
                            raise
            log.info("✓ %s migration 011 applied", schema)
        except Exception as exc:
            log.error("✗ %s migration 011 FAILED: %s", schema, exc)
            raise

    await engine.dispose()
    log.info("Done. %d tenants processed.", len(tenant_ids))


if __name__ == "__main__":
    asyncio.run(run())
