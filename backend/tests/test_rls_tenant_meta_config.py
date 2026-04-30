"""
tenant_meta_config の RLS（Row Level Security）テスト。

PostgreSQL 専用機能のため、ローカル pytest（SQLite）では skip する。
CI で PostgreSQL を起動してテストする場合は環境変数 `RLS_TEST_DATABASE_URL`
（例: `postgresql+asyncpg://...`）を渡すと自動的にロードして実行する。

検証内容:
- tenant_isolation_tenant_meta_config ポリシーで、
  別テナントの行が SELECT で見えないこと
- 同じ tenant_id を SET LOCAL app.tenant_id すれば見えること

実行例:
    # SQLite では skip
    pytest backend/tests/test_rls_tenant_meta_config.py -v

    # CI で PostgreSQL 起動済の場合
    RLS_TEST_DATABASE_URL=postgresql+asyncpg://myapp_user:pwd@localhost:5432/myapp_db \
        pytest backend/tests/test_rls_tenant_meta_config.py -v

変更履歴:
    2026-04-30: Phase 1-D Sprint 2 初版（Sprint 1 Evaluator 指摘 #2 対応）
"""

from __future__ import annotations

import os
from typing import Optional

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker


_RLS_DB_URL: Optional[str] = os.getenv("RLS_TEST_DATABASE_URL")


pytestmark = pytest.mark.skipif(
    not _RLS_DB_URL,
    reason=(
        "PostgreSQL ベースの RLS テストは環境変数 RLS_TEST_DATABASE_URL が "
        "設定されたときだけ実行する（ローカル pytest は SQLite）"
    ),
)


@pytest_asyncio.fixture(scope="module")
async def pg_engine():
    assert _RLS_DB_URL  # mypy 用
    eng = create_async_engine(_RLS_DB_URL, echo=False, future=True)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def pg_session(pg_engine):
    Session = sessionmaker(pg_engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as s:
        yield s
        await s.rollback()


async def _ensure_two_tenant_schemas(s: AsyncSession) -> None:
    """テスト用 tenant_998 / tenant_999 スキーマと tenant_meta_config を用意する。

    本物の `_TENANT_TABLES_SQL` を呼ばずに、最小限の DDL だけを直接適用する
    （RLS ポリシーの動作検証だけが目的のため）。
    """
    for tid in (998, 999):
        schema = f"tenant_{tid:03d}"
        await s.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))
        # staff (FK 参照先のため最低限)
        await s.execute(text(f"""
            CREATE TABLE IF NOT EXISTS {schema}.staff (
                id SERIAL PRIMARY KEY,
                tenant_id INTEGER NOT NULL DEFAULT {tid},
                primary_email VARCHAR(255) NOT NULL
            )
        """))
        # tenant_meta_config 本体（migration 040 と同等）
        await s.execute(text(f"""
            CREATE TABLE IF NOT EXISTS {schema}.tenant_meta_config (
                id SERIAL PRIMARY KEY,
                tenant_id INTEGER NOT NULL DEFAULT {tid},
                page_id VARCHAR(50) NOT NULL,
                page_name VARCHAR(200) NOT NULL,
                page_access_token_encrypted BYTEA NOT NULL,
                page_token_expires_at TIMESTAMPTZ,
                instagram_business_account_id VARCHAR(50),
                instagram_username VARCHAR(100),
                subscribed_fields JSONB,
                connected_by_staff_id INTEGER REFERENCES {schema}.staff(id),
                connected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                last_token_refreshed_at TIMESTAMPTZ,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                deactivated_at TIMESTAMPTZ,
                notes TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        await s.execute(text(
            f"ALTER TABLE {schema}.tenant_meta_config ENABLE ROW LEVEL SECURITY"
        ))
        # FORCE して superuser でも RLS が効くようにする（テスト用）
        await s.execute(text(
            f"ALTER TABLE {schema}.tenant_meta_config FORCE ROW LEVEL SECURITY"
        ))
        # ポリシー再作成
        await s.execute(text(f"""
            DROP POLICY IF EXISTS tenant_isolation_tenant_meta_config
              ON {schema}.tenant_meta_config
        """))
        await s.execute(text(f"""
            CREATE POLICY tenant_isolation_tenant_meta_config
              ON {schema}.tenant_meta_config
              USING (tenant_id = current_setting('app.tenant_id', true)::INTEGER)
        """))
        # 既存データを掃除
        await s.execute(text(f"TRUNCATE {schema}.tenant_meta_config RESTART IDENTITY CASCADE"))

    await s.commit()


async def _insert_dummy(s: AsyncSession, tenant_id: int, page_id: str) -> None:
    schema = f"tenant_{tenant_id:03d}"
    await s.execute(text(f"SET LOCAL app.tenant_id = '{tenant_id}'"))
    await s.execute(text(f"""
        INSERT INTO {schema}.tenant_meta_config
            (tenant_id, page_id, page_name, page_access_token_encrypted)
        VALUES (:tid, :pid, :name, :tok)
    """), {
        "tid": tenant_id,
        "pid": page_id,
        "name": f"Page-{tenant_id}",
        "tok": b"dummy-encrypted-bytes",
    })


@pytest.mark.asyncio
async def test_rls_other_tenant_rows_invisible(pg_session):
    """テナント A の context で B の行が SELECT で見えない。"""
    await _ensure_two_tenant_schemas(pg_session)
    await _insert_dummy(pg_session, 998, "page-998-1")
    await _insert_dummy(pg_session, 999, "page-999-1")
    await pg_session.commit()

    # テナント 998 の context で tenant_999 のテーブルを見る
    await pg_session.execute(text("SET LOCAL app.tenant_id = '998'"))
    rows = (await pg_session.execute(text(
        "SELECT page_id FROM tenant_999.tenant_meta_config"
    ))).fetchall()
    assert rows == [], f"テナント 998 の context で 999 の行が見えてしまう: {rows}"

    # 自テナントは見える
    rows = (await pg_session.execute(text(
        "SELECT page_id FROM tenant_998.tenant_meta_config"
    ))).fetchall()
    assert any(r[0] == "page-998-1" for r in rows)


@pytest.mark.asyncio
async def test_rls_visible_when_app_tenant_id_matches(pg_session):
    """app.tenant_id を切り替えると、そのテナントの行が見えるようになる。"""
    await _ensure_two_tenant_schemas(pg_session)
    await _insert_dummy(pg_session, 999, "page-999-2")
    await pg_session.commit()

    await pg_session.execute(text("SET LOCAL app.tenant_id = '999'"))
    rows = (await pg_session.execute(text(
        "SELECT page_id FROM tenant_999.tenant_meta_config WHERE page_id = 'page-999-2'"
    ))).fetchall()
    assert len(rows) == 1
