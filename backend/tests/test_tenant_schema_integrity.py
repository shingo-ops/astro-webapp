"""
テナントスキーマ整合性テスト（ADR-036 Level 4）。

テストは 3 グループに分かれる:
  - TestComputeDiff   : 純 Python のユニットテスト。PostgreSQL 不要。常に実行。
  - TestSchemaInspection : PostgreSQL 上で information_schema を取得・比較するテスト。
  - TestRealTenantSchemas: 実テナントスキーマ間の整合性チェック。本番相当 DB が必要。

TestSchemaInspection / TestRealTenantSchemas は環境変数
`RLS_TEST_DATABASE_URL` が設定されている場合のみ実行する。

実行例:
    # TestComputeDiff のみ（SQLite 環境）
    pytest backend/tests/test_tenant_schema_integrity.py -v

    # 全テスト（PostgreSQL 起動済）
    RLS_TEST_DATABASE_URL=postgresql+asyncpg://jarvis_app:apppass@localhost:5432/jarvis_test_db \\
        pytest backend/tests/test_tenant_schema_integrity.py -v

変更履歴:
    2026-05-15: ADR-036 Level 4 初版
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

# project root を sys.path に追加（scripts パッケージを import するため）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# sync_tenant_schema.py のヘルパー関数を再利用
from scripts.db.sync_tenant_schema import (  # noqa: E402
    ColumnInfo,
    _compute_diff,
    _get_rls_enabled_count,
    _get_role_permission_count,
    _get_schema_columns,
    _get_trigger_count,
    _split_sql_preserving_do_blocks,
)

_RLS_DB_URL: Optional[str] = os.getenv("RLS_TEST_DATABASE_URL")

_SKIP_NO_PG = pytest.mark.skipif(
    not _RLS_DB_URL,
    reason=(
        "PostgreSQL ベースのスキーマ整合性テストは環境変数 RLS_TEST_DATABASE_URL が "
        "設定されたときだけ実行する（ローカル pytest は SQLite）"
    ),
)

# テスト用の一時スキーマ名（テスト後にドロップする）
_SCHEMA_A = "test_schema_integrity_a"
_SCHEMA_B = "test_schema_integrity_b"

_MINIMAL_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS {schema}.sample_table (
    id         SERIAL PRIMARY KEY,
    tenant_id  INTEGER NOT NULL,
    name       VARCHAR(100) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
"""


@pytest_asyncio.fixture(scope="module")
async def pg_engine():
    assert _RLS_DB_URL, "RLS_TEST_DATABASE_URL が未設定"
    eng = create_async_engine(_RLS_DB_URL, echo=False, future=True)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture(scope="module")
async def test_schemas(pg_engine):
    """テスト用スキーマを作成し、テスト後にドロップする。"""
    async with pg_engine.begin() as conn:
        await conn.execute(text(f"DROP SCHEMA IF EXISTS {_SCHEMA_A} CASCADE"))
        await conn.execute(text(f"DROP SCHEMA IF EXISTS {_SCHEMA_B} CASCADE"))
        await conn.execute(text(f"CREATE SCHEMA {_SCHEMA_A}"))
        await conn.execute(text(f"CREATE SCHEMA {_SCHEMA_B}"))

        for schema in (_SCHEMA_A, _SCHEMA_B):
            sql = _MINIMAL_TABLES_SQL.format(schema=schema)
            for stmt in _split_sql_preserving_do_blocks(sql):
                stmt = stmt.strip()
                if stmt:
                    await conn.execute(text(stmt))

    yield _SCHEMA_A, _SCHEMA_B

    async with pg_engine.begin() as conn:
        await conn.execute(text(f"DROP SCHEMA IF EXISTS {_SCHEMA_A} CASCADE"))
        await conn.execute(text(f"DROP SCHEMA IF EXISTS {_SCHEMA_B} CASCADE"))


# ---------------------------------------------------------------------------
# TestComputeDiff: 純 Python、DB 不要、常に実行
# ---------------------------------------------------------------------------

class TestComputeDiff:
    """_compute_diff のユニットテスト（PostgreSQL 不要）。"""

    def test_no_diff_when_schemas_identical(self):
        col = ColumnInfo(
            table_name="t1",
            column_name="id",
            data_type="integer",
            is_nullable="NO",
            column_default=None,
            character_maximum_length=None,
            numeric_precision=32,
        )
        ref = {"t1": {"id": col}}
        diff = _compute_diff(ref, {"t1": {"id": col}}, "schema_x")
        assert not diff.has_diff()

    def test_detects_missing_table(self):
        col = ColumnInfo("t1", "id", "integer", "NO", None, None, 32)
        diff = _compute_diff({"t1": {"id": col}}, {}, "schema_x")
        assert diff.missing_tables == ["t1"]
        assert not diff.missing_columns

    def test_detects_missing_column(self):
        col_id = ColumnInfo("t1", "id", "integer", "NO", None, None, 32)
        col_name = ColumnInfo("t1", "name", "text", "YES", None, None, None)
        ref = {"t1": {"id": col_id, "name": col_name}}
        diff = _compute_diff(ref, {"t1": {"id": col_id}}, "schema_x")
        assert len(diff.missing_columns) == 1
        assert diff.missing_columns[0].column_name == "name"

    def test_detects_type_mismatch(self):
        ref_col = ColumnInfo("t1", "msg", "text", "YES", None, None, None)
        tgt_col = ColumnInfo("t1", "msg", "character varying", "YES", None, 100, None)
        diff = _compute_diff({"t1": {"msg": ref_col}}, {"t1": {"msg": tgt_col}}, "schema_x")
        assert len(diff.type_mismatches) == 1
        _, col, ref_type, actual_type = diff.type_mismatches[0]
        assert col == "msg"
        assert ref_type == "text"
        assert actual_type == "character varying"


# ---------------------------------------------------------------------------
# TestSchemaInspection: PostgreSQL 必須
# ---------------------------------------------------------------------------

@_SKIP_NO_PG
class TestSchemaInspection:
    """PostgreSQL 上での information_schema 取得テスト。"""

    @pytest.mark.asyncio
    async def test_get_schema_columns_returns_tables(self, pg_engine, test_schemas):
        schema_a, _ = test_schemas
        async with pg_engine.connect() as conn:
            cols = await _get_schema_columns(conn, schema_a)
        assert "sample_table" in cols
        assert "id" in cols["sample_table"]
        assert "name" in cols["sample_table"]
        assert "created_at" in cols["sample_table"]

    @pytest.mark.asyncio
    async def test_identical_schemas_have_no_diff(self, pg_engine, test_schemas):
        schema_a, schema_b = test_schemas
        async with pg_engine.connect() as conn:
            ref_cols = await _get_schema_columns(conn, schema_a)
            tgt_cols = await _get_schema_columns(conn, schema_b)
        diff = _compute_diff(ref_cols, tgt_cols, schema_b)
        assert not diff.has_diff(), (
            f"同一スキーマ間で差分が検出された: "
            f"missing_tables={diff.missing_tables}, "
            f"missing_columns={[c.column_name for c in diff.missing_columns]}"
        )

    @pytest.mark.asyncio
    async def test_detects_added_column_in_one_schema(self, pg_engine, test_schemas):
        """schema_a にカラムを追加した場合、schema_b との差分が検出される。"""
        schema_a, schema_b = test_schemas
        async with pg_engine.begin() as conn:
            await conn.execute(
                text(
                    f"ALTER TABLE {schema_a}.sample_table "
                    f"ADD COLUMN IF NOT EXISTS extra_col TEXT"
                )
            )
        async with pg_engine.connect() as conn:
            ref_cols = await _get_schema_columns(conn, schema_a)
            tgt_cols = await _get_schema_columns(conn, schema_b)
        diff = _compute_diff(ref_cols, tgt_cols, schema_b)
        missing_names = [c.column_name for c in diff.missing_columns]
        assert "extra_col" in missing_names

    @pytest.mark.asyncio
    async def test_get_trigger_count_returns_integer(self, pg_engine, test_schemas):
        schema_a, _ = test_schemas
        async with pg_engine.connect() as conn:
            count = await _get_trigger_count(conn, schema_a)
        assert isinstance(count, int) and count >= 0

    @pytest.mark.asyncio
    async def test_get_rls_enabled_count_returns_integer(self, pg_engine, test_schemas):
        schema_a, _ = test_schemas
        async with pg_engine.connect() as conn:
            count = await _get_rls_enabled_count(conn, schema_a)
        assert isinstance(count, int) and count >= 0

    @pytest.mark.asyncio
    async def test_get_role_permission_count_returns_minus_one_when_no_table(
        self, pg_engine, test_schemas
    ):
        """role_permissions テーブルが存在しないスキーマでは -1 を返す。"""
        schema_a, _ = test_schemas
        async with pg_engine.connect() as conn:
            count = await _get_role_permission_count(conn, schema_a)
        assert count == -1


# ---------------------------------------------------------------------------
# TestRealTenantSchemas: PostgreSQL 必須、実テナント相当 DB がある場合のみ
# ---------------------------------------------------------------------------

@_SKIP_NO_PG
class TestRealTenantSchemas:
    """アクティブな全テナントスキーマの整合性チェック。

    public.tenants と tenant_004 スキーマが存在しない場合は自動スキップ。
    """

    @pytest.mark.asyncio
    async def test_active_tenants_have_consistent_schema(self, pg_engine):
        """全テナントのテーブル数・カラム数・RLS 有効数が tenant_004 と一致すること。"""
        async with pg_engine.connect() as conn:
            try:
                rows = await conn.execute(
                    text(
                        "SELECT id FROM public.tenants "
                        "WHERE is_active = TRUE ORDER BY id"
                    )
                )
                tenant_ids = [row[0] for row in rows]
            except Exception:
                pytest.skip("public.tenants が存在しないためスキップ")
                return

            if len(tenant_ids) < 2:
                pytest.skip("テナントが 2 つ未満のためスキップ")
                return

            ref_row = await conn.execute(
                text("SELECT 1 FROM pg_namespace WHERE nspname = 'tenant_004'")
            )
            if not ref_row.first():
                pytest.skip("tenant_004 が存在しないためスキップ")
                return

            ref_cols = await _get_schema_columns(conn, "tenant_004")
            ref_table_count = len(ref_cols)
            ref_col_count = sum(len(v) for v in ref_cols.values())
            ref_rls = await _get_rls_enabled_count(conn, "tenant_004")

        failures: list[str] = []
        for tid in tenant_ids:
            schema = f"tenant_{tid:03d}"
            if schema == "tenant_004":
                continue

            async with pg_engine.connect() as conn:
                tgt_cols = await _get_schema_columns(conn, schema)
                if not tgt_cols:
                    continue
                tgt_table_count = len(tgt_cols)
                tgt_col_count = sum(len(v) for v in tgt_cols.values())
                rls_count = await _get_rls_enabled_count(conn, schema)

            if tgt_table_count != ref_table_count:
                failures.append(
                    f"{schema}: テーブル数 {tgt_table_count} != ref {ref_table_count}"
                )
            if tgt_col_count != ref_col_count:
                failures.append(
                    f"{schema}: カラム数 {tgt_col_count} != ref {ref_col_count}"
                )
            if rls_count != ref_rls:
                failures.append(
                    f"{schema}: RLS有効テーブル {rls_count} != ref {ref_rls}"
                )

        assert not failures, (
            "テナントスキーマ間に整合性の問題が検出されました:\n"
            + "\n".join(failures)
            + "\n\n→ scripts/db/sync_tenant_schema.py を実行して差分を解消してください。"
        )
