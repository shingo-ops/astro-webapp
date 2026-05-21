"""Inventory Sprint 8 (migration 069) の構造検証テスト (実 PostgreSQL)。

spec.md v1.1 Sprint 8 / F8 / AC8.7 の自動検証。
SQLite モック禁止条項 (feedback_evaluator_gap_2026_05_15.md) に従い、
実 PostgreSQL 16 環境で実行する。

実行方法:
  TEST_PG_URL=postgresql+asyncpg://user:pw@localhost:5432/jarvis_test_db \\
    pytest backend/tests/test_inventory_sprint8_migrations.py -v

TEST_PG_URL 未設定 → 全テスト skip。
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

TEST_PG_URL = os.getenv("TEST_PG_URL") or os.getenv("RLS_TEST_DATABASE_URL")

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not TEST_PG_URL,
        reason="実 PostgreSQL 環境が必要 (TEST_PG_URL 未設定)。"
               "SQLite では DO ブロック / pg_namespace / pg_constraint は検証不可。",
    ),
]

BASE_DIR = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = BASE_DIR / "migrations"


def _split_sql_preserving_do_blocks(sql: str) -> list[str]:
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


@pytest.fixture
async def engine():
    from sqlalchemy.ext.asyncio import create_async_engine
    eng = create_async_engine(TEST_PG_URL, echo=False)
    yield eng
    await eng.dispose()


async def _apply_migration(eng, filename: str) -> None:
    from sqlalchemy import text
    sql = (MIGRATIONS_DIR / filename).read_text("utf-8")
    statements = [s.strip() for s in _split_sql_preserving_do_blocks(sql) if s.strip()]
    async with eng.begin() as conn:
        for stmt in statements:
            await conn.execute(text(stmt))


async def test_migration_069_creates_tenant_profile_table(engine):
    """migration 069 適用後、tenant_profile が存在する。"""
    from sqlalchemy import text

    await _apply_migration(engine, "069_create_tenant_profile.sql")

    async with engine.connect() as conn:
        # 任意の tenant_xxx schema を 1 つ拾う
        sr = await conn.execute(text(
            "SELECT nspname FROM pg_namespace WHERE nspname ~ '^tenant_\\d+$' "
            "ORDER BY nspname LIMIT 1"
        ))
        row = sr.first()
        if not row:
            pytest.skip("tenant_xxx schema が存在しない (seed 必要)")
        schema = row[0]

        col_check = await conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = :s AND table_name = 'tenant_profile' "
            "ORDER BY ordinal_position"
        ), {"s": schema})
        cols = [r[0] for r in col_check.all()]
        assert "company_name" in cols
        assert "address" in cols
        assert "default_language" in cols
        assert "seal_image_url" in cols


async def test_migration_069_seeds_default_row(engine):
    """各テナントに既定行 1 行が seed される (冪等)。"""
    from sqlalchemy import text

    await _apply_migration(engine, "069_create_tenant_profile.sql")
    # 冪等性: 2 回目適用も 1 行のまま
    await _apply_migration(engine, "069_create_tenant_profile.sql")

    async with engine.connect() as conn:
        sr = await conn.execute(text(
            "SELECT nspname FROM pg_namespace WHERE nspname ~ '^tenant_\\d+$' "
            "ORDER BY nspname LIMIT 1"
        ))
        row = sr.first()
        if not row:
            pytest.skip("tenant_xxx schema が存在しない")
        schema = row[0]

        count = (await conn.execute(text(
            f"SELECT COUNT(*) FROM {schema}.tenant_profile"
        ))).scalar()
        assert count == 1


async def test_migration_069_seeds_permissions(engine):
    """public.permissions に tenant.profile.* が追加される。"""
    from sqlalchemy import text

    await _apply_migration(engine, "069_create_tenant_profile.sql")

    async with engine.connect() as conn:
        result = await conn.execute(text(
            "SELECT key FROM public.permissions "
            "WHERE key IN ('tenant.profile.view', 'tenant.profile.edit')"
        ))
        keys = {r[0] for r in result.all()}
        assert "tenant.profile.view" in keys
        assert "tenant.profile.edit" in keys


async def test_migration_069_default_language_check_constraint(engine):
    """default_language CHECK 制約: 'fr' は弾かれる。"""
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    await _apply_migration(engine, "069_create_tenant_profile.sql")

    async with engine.connect() as conn:
        sr = await conn.execute(text(
            "SELECT nspname FROM pg_namespace WHERE nspname ~ '^tenant_\\d+$' "
            "ORDER BY nspname LIMIT 1"
        ))
        row = sr.first()
        if not row:
            pytest.skip("tenant_xxx schema が存在しない")
        schema = row[0]

        with pytest.raises(IntegrityError):
            async with engine.begin() as wconn:
                await wconn.execute(text(
                    f"INSERT INTO {schema}.tenant_profile (default_language) VALUES ('fr')"
                ))
