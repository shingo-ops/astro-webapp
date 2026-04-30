"""
tenant_meta_config の RLS（Row Level Security）テスト。

PostgreSQL 専用機能のため、ローカル pytest（SQLite）では skip する。
CI で PostgreSQL を起動してテストする場合は環境変数 `RLS_TEST_DATABASE_URL`
（例: `postgresql+asyncpg://...`）を渡すと自動的にロードして実行する。

**重要: 非 SUPERUSER ロールで接続すること**

PostgreSQL の `FORCE ROW LEVEL SECURITY` はテーブル所有者にも RLS を適用するが、
SUPERUSER は常に RLS をバイパスする。CI では非 SUPERUSER ロール
(`jarvis_app` 等) で接続する `RLS_TEST_DATABASE_URL` を設定すること。

検証内容:
- tenant_isolation_tenant_meta_config ポリシーで、
  別テナントの行が SELECT で見えないこと
- 同じ tenant_id を SET LOCAL app.tenant_id すれば見えること

実行例:
    # SQLite では skip
    pytest backend/tests/test_rls_tenant_meta_config.py -v

    # CI で PostgreSQL 起動済の場合
    RLS_TEST_DATABASE_URL=postgresql+asyncpg://jarvis_app:apppass@localhost:5432/jarvis_test_db \
        pytest backend/tests/test_rls_tenant_meta_config.py -v

変更履歴:
    2026-04-30: Phase 1-D Sprint 2 初版（Sprint 1 Evaluator 指摘 #2 対応）
    2026-04-30: Phase 1-E F3-S2 v2 — fixture を AsyncConnection 化、
                SUPERUSER バイパス問題を解消、transaction 二重起動を修正
"""

from __future__ import annotations

import os
from typing import Optional

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine


_RLS_DB_URL: Optional[str] = os.getenv("RLS_TEST_DATABASE_URL")


pytestmark = pytest.mark.skipif(
    not _RLS_DB_URL,
    reason=(
        "PostgreSQL ベースの RLS テストは環境変数 RLS_TEST_DATABASE_URL が "
        "設定されたときだけ実行する（ローカル pytest は SQLite）"
    ),
)


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def pg_engine():
    assert _RLS_DB_URL  # mypy 用
    eng = create_async_engine(_RLS_DB_URL, echo=False, future=True)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def setup_schemas(pg_engine):
    """tenant_998 / tenant_999 schema + tenant_meta_config + RLS を 1 回だけ作る。

    本物の `_TENANT_TABLES_SQL` を呼ばずに、最小限の DDL だけを直接適用する
    （RLS ポリシーの動作検証だけが目的のため）。

    各テスト前に行を TRUNCATE するため、テスト間で行が混在しない。
    """
    async with pg_engine.begin() as conn:
        for tid in (998, 999):
            schema = f"tenant_{tid:03d}"
            await conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))
            # staff (FK 参照先のため最低限)
            await conn.execute(text(f"""
                CREATE TABLE IF NOT EXISTS {schema}.staff (
                    id SERIAL PRIMARY KEY,
                    tenant_id INTEGER NOT NULL DEFAULT {tid},
                    primary_email VARCHAR(255) NOT NULL
                )
            """))
            # tenant_meta_config 本体（migration 040 と同等）
            await conn.execute(text(f"""
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
            await conn.execute(text(
                f"ALTER TABLE {schema}.tenant_meta_config ENABLE ROW LEVEL SECURITY"
            ))
            # FORCE: テーブル所有者にも RLS 適用
            # 注意: SUPERUSER は FORCE でもバイパスされるため、CI で非 SUPERUSER
            # ロールを使うこと（test.yml で jarvis_app を作成）。
            await conn.execute(text(
                f"ALTER TABLE {schema}.tenant_meta_config FORCE ROW LEVEL SECURITY"
            ))
            # ポリシー再作成
            await conn.execute(text(f"""
                DROP POLICY IF EXISTS tenant_isolation_tenant_meta_config
                  ON {schema}.tenant_meta_config
            """))
            await conn.execute(text(f"""
                CREATE POLICY tenant_isolation_tenant_meta_config
                  ON {schema}.tenant_meta_config
                  USING (tenant_id = current_setting('app.tenant_id', true)::INTEGER)
            """))

    yield

    # cleanup: テスト用 schema を完全削除
    async with pg_engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA IF EXISTS tenant_998 CASCADE"))
        await conn.execute(text("DROP SCHEMA IF EXISTS tenant_999 CASCADE"))


@pytest_asyncio.fixture(loop_scope="session")
async def pg_conn(pg_engine, setup_schemas):
    """各テストごとに独立 AsyncConnection。

    AsyncSession ではなく AsyncConnection を使うのは、
    `cannot use Connection.transaction() in a manually started transaction`
    を避けるため（AsyncSession の savepoint 自動挿入が DDL/SET LOCAL と衝突する）。

    各テストで TRUNCATE → INSERT → SELECT で完結させる。
    """
    async with pg_engine.connect() as conn:
        # テストデータ初期化（FK 制約 CASCADE で staff も一掃）
        async with conn.begin():
            await conn.execute(text("TRUNCATE tenant_998.tenant_meta_config RESTART IDENTITY CASCADE"))
            await conn.execute(text("TRUNCATE tenant_999.tenant_meta_config RESTART IDENTITY CASCADE"))
        yield conn


async def _insert_dummy(conn: AsyncConnection, tenant_id: int, page_id: str) -> None:
    """RLS ポリシー下で INSERT するため、対象テナントの context にした上で INSERT。"""
    schema = f"tenant_{tenant_id:03d}"
    await conn.execute(text(f"SET LOCAL app.tenant_id = '{tenant_id}'"))
    await conn.execute(text(f"""
        INSERT INTO {schema}.tenant_meta_config
            (tenant_id, page_id, page_name, page_access_token_encrypted)
        VALUES (:tid, :pid, :name, :tok)
    """), {
        "tid": tenant_id,
        "pid": page_id,
        "name": f"Page-{tenant_id}",
        "tok": b"dummy-encrypted-bytes",
    })


@pytest.mark.asyncio(loop_scope="session")
async def test_rls_other_tenant_rows_invisible(pg_conn):
    """テナント A の context で B の行が SELECT で見えない。"""
    # データ投入: 各テナントを 1 件ずつ
    async with pg_conn.begin():
        await _insert_dummy(pg_conn, 998, "page-998-1")

    async with pg_conn.begin():
        await _insert_dummy(pg_conn, 999, "page-999-1")

    # 検証: テナント 998 の context で tenant_999 のテーブルを見る
    async with pg_conn.begin():
        await pg_conn.execute(text("SET LOCAL app.tenant_id = '998'"))
        rows = (await pg_conn.execute(text(
            "SELECT page_id FROM tenant_999.tenant_meta_config"
        ))).fetchall()
        assert rows == [], f"テナント 998 の context で 999 の行が見えてしまう: {rows}"

        # 自テナントは見える
        rows = (await pg_conn.execute(text(
            "SELECT page_id FROM tenant_998.tenant_meta_config"
        ))).fetchall()
        assert any(r[0] == "page-998-1" for r in rows)


@pytest.mark.asyncio(loop_scope="session")
async def test_rls_visible_when_app_tenant_id_matches(pg_conn):
    """app.tenant_id を切り替えると、そのテナントの行が見えるようになる。"""
    async with pg_conn.begin():
        await _insert_dummy(pg_conn, 999, "page-999-2")

    async with pg_conn.begin():
        await pg_conn.execute(text("SET LOCAL app.tenant_id = '999'"))
        rows = (await pg_conn.execute(text(
            "SELECT page_id FROM tenant_999.tenant_meta_config WHERE page_id = 'page-999-2'"
        ))).fetchall()
        assert len(rows) == 1, f"自テナントの行が見えない: {rows}"


@pytest.mark.asyncio(loop_scope="session")
async def test_rls_no_app_tenant_id_returns_empty(pg_conn):
    """app.tenant_id 未設定なら何も見えない（NULL → INTEGER 比較で false）。"""
    async with pg_conn.begin():
        await _insert_dummy(pg_conn, 998, "page-998-3")
        await _insert_dummy(pg_conn, 999, "page-999-3")

    async with pg_conn.begin():
        # app.tenant_id をリセット
        await pg_conn.execute(text("RESET app.tenant_id"))
        # current_setting('app.tenant_id', true) が NULL を返し、INTEGER cast で NULL
        # → tenant_id = NULL は NULL（true でない）→ 0 行
        rows_998 = (await pg_conn.execute(text(
            "SELECT page_id FROM tenant_998.tenant_meta_config"
        ))).fetchall()
        rows_999 = (await pg_conn.execute(text(
            "SELECT page_id FROM tenant_999.tenant_meta_config"
        ))).fetchall()
        assert rows_998 == [], f"app.tenant_id 未設定で 998 の行が見える: {rows_998}"
        assert rows_999 == [], f"app.tenant_id 未設定で 999 の行が見える: {rows_999}"
