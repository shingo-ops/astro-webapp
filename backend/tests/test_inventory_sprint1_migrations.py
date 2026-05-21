"""Inventory Sprint 1 (migrations 056-063) の構造検証テスト (実 PostgreSQL)。

spec.md v1.1 Sprint 1 / F1 / AC1.1〜AC1.8 の自動検証。
SQLite モック禁止条項 (feedback_evaluator_gap_2026_05_15.md) に従い、
実 PostgreSQL 16 環境（docker-compose.test.yml or VPS tenant_006）で実行する。

実行方法:
  # ローカル: docker compose -f docker-compose.test.yml up -d postgres-test
  # その後、DATABASE_URL を test container 向けに設定して:
  TEST_PG_URL=postgresql+asyncpg://myapp_user:password@localhost:5432/myapp_db \\
    pytest backend/tests/test_inventory_sprint1_migrations.py -v

  # CI / VPS では tenant_006 環境を使用。
  TEST_PG_URL が未設定の場合は全テストが skip される（SQLite では検証不可能なため）。

検証対象:
  - AC1.1: migration 適用後のテーブル群存在確認
  - AC1.2: supplier_aliases UNIQUE 制約による 23505
  - AC1.6: discord_webhook_idempotency と {tenant_xxx}.meta_webhook_idempotency の構造一致
  - AC1.7: suppliers.supplier_type CHECK 制約による 23514
  - AC1.8: role_permissions に inventory.visibility.* が seed されている
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# 実 Postgres URL が指定されていない場合はモジュール全体を skip
TEST_PG_URL = os.getenv("TEST_PG_URL") or os.getenv("RLS_TEST_DATABASE_URL")

# pytest-asyncio
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not TEST_PG_URL,
        reason="実 PostgreSQL 環境が必要 (TEST_PG_URL / RLS_TEST_DATABASE_URL 未設定)。"
               "SQLite では migration / JSONB / search_path / CHECK 制約は検証できない。"
               "spec.md / feedback_evaluator_gap_2026_05_15.md 参照。",
    ),
]

BASE_DIR = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = BASE_DIR / "migrations"


def _split_sql_preserving_do_blocks(sql: str) -> list[str]:
    """scripts/migrate_inventory_sprint1.py の同名関数と同じ実装。"""
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
    """テスト用エンジン (function scope、各テストで独立した接続)。

    各テストは isolated にスキーマを準備するため、function scope。
    """
    from sqlalchemy.ext.asyncio import create_async_engine

    eng = create_async_engine(TEST_PG_URL, echo=False)
    yield eng
    await eng.dispose()


async def _apply_public_migrations(eng) -> None:
    """public 系 migration 056-062 を順に適用 (冪等)。"""
    public_files = [
        "056_add_suppliers_type_and_promote_public.sql",
        "057_create_supplier_aliases.sql",
        "058_create_knowledge_rules.sql",
        "059_create_discord_inbound_messages.sql",
        "060_create_supplier_discord_routing.sql",
        "061_create_tcg_and_dex_masters.sql",
        "062_create_inventory_movements_and_budget.sql",
    ]
    for fn in public_files:
        sql = (MIGRATIONS_DIR / fn).read_text("utf-8")
        async with eng.begin() as conn:
            for stmt in _split_sql_preserving_do_blocks(sql):
                stmt = stmt.strip()
                if stmt:
                    await conn.exec_driver_sql(stmt)


# ---------------------------------------------------------------------------
# AC1.1: テーブル存在確認
# ---------------------------------------------------------------------------

async def test_ac1_1_public_tables_exist(engine):
    """AC1.1: migrations 056-062 適用後、public schema に期待テーブルが揃う。"""
    from sqlalchemy import text

    await _apply_public_migrations(engine)

    expected_tables = {
        "suppliers",
        "supplier_aliases",
        "knowledge_rules",
        "discord_inbound_messages",
        "discord_webhook_idempotency",
        "supplier_discord_routing",
        "pokemon_dex",
        "trainer_dex",
        "tcg_series_master",
        "products",
        "inventory_movements",
        "tenant_llm_budgets",
    }
    async with engine.connect() as conn:
        result = await conn.execute(text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='public' AND table_type='BASE TABLE'"
        ))
        actual = {row.table_name for row in result}
    missing = expected_tables - actual
    assert not missing, f"public schema に未作成のテーブル: {missing}"


# ---------------------------------------------------------------------------
# AC1.2: supplier_aliases UNIQUE 制約
# ---------------------------------------------------------------------------

async def test_ac1_2_supplier_aliases_unique_constraint(engine):
    """AC1.2: (supplier_id, alias_text, 'ja') の重複 INSERT で 23505 (unique_violation)。"""
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    await _apply_public_migrations(engine)

    async with engine.begin() as conn:
        # supplier 1 行用意
        sup_id = (await conn.execute(text(
            "INSERT INTO public.suppliers (supplier_code, name, supplier_type, default_language) "
            "VALUES ('TEST-AC1-2', 'AC1.2 test supplier', 'corporate', 'ja') "
            "RETURNING id"
        ))).scalar_one()
        # 1 件目 OK
        await conn.execute(text(
            "INSERT INTO public.supplier_aliases (supplier_id, alias_text, language) "
            "VALUES (:sid, 'リザ eX SAR', 'ja')"
        ), {"sid": sup_id})

    # 2 件目（同一 supplier_id + alias_text + language）→ UNIQUE violation
    with pytest.raises(IntegrityError) as ei:
        async with engine.begin() as conn:
            await conn.execute(text(
                "INSERT INTO public.supplier_aliases (supplier_id, alias_text, language) "
                "VALUES (:sid, 'リザ eX SAR', 'ja')"
            ), {"sid": sup_id})
    # PostgreSQL の unique_violation は SQLSTATE 23505
    assert "23505" in str(ei.value) or "duplicate" in str(ei.value).lower()


# ---------------------------------------------------------------------------
# AC1.6: discord_webhook_idempotency 構造一致
# ---------------------------------------------------------------------------

async def test_ac1_6_discord_idempotency_structure(engine):
    """AC1.6: public.discord_webhook_idempotency の主要列が meta_webhook 系と同型。"""
    from sqlalchemy import text

    await _apply_public_migrations(engine)

    async with engine.connect() as conn:
        result = await conn.execute(text(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name='discord_webhook_idempotency' "
            "ORDER BY ordinal_position"
        ))
        cols = {row.column_name: row.data_type for row in result}

    # migration 013 ({tenant_xxx}.meta_messages.message_id VARCHAR(100)) と同型
    assert "message_id" in cols
    assert cols["message_id"] in ("character varying", "varchar")
    assert "received_at" in cols
    assert cols["received_at"] in ("timestamp with time zone", "timestamptz")


# ---------------------------------------------------------------------------
# AC1.7: suppliers.supplier_type CHECK 制約
# ---------------------------------------------------------------------------

async def test_ac1_7_supplier_type_check_constraint(engine):
    """AC1.7: supplier_type に不正値を入れると 23514 (check_violation)。"""
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    await _apply_public_migrations(engine)

    with pytest.raises(IntegrityError) as ei:
        async with engine.begin() as conn:
            await conn.execute(text(
                "INSERT INTO public.suppliers (supplier_code, name, supplier_type) "
                "VALUES ('TEST-AC1-7', 'invalid type test', 'unknown_type')"
            ))
    assert "23514" in str(ei.value) or "check" in str(ei.value).lower()


# ---------------------------------------------------------------------------
# AC1.8: inventory.visibility.* permission keys seed 済
# ---------------------------------------------------------------------------

async def test_ac1_8_inventory_visibility_permissions_seeded(engine):
    """AC1.8: migration 063 適用後、public.permissions に inventory.visibility.* が存在。

    Note: 063 は本来テナント schema (role_permissions) の seed も含むが、本テストは
    public.permissions への INSERT 部分のみを検証する。テナント schema (tenant_*)
    の seed は実 tenant_006 での integration test で別途確認 (Sprint 2 で UI 検証時)。
    """
    from sqlalchemy import text

    await _apply_public_migrations(engine)

    # public.permissions が存在しない環境 (fresh test DB) では skip
    async with engine.connect() as conn:
        exists = (await conn.execute(text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name='permissions'"
        ))).scalar_one_or_none()
    if not exists:
        pytest.skip(
            "public.permissions テーブルが未作成 (migration 002 が未適用)。"
            "本テストは production-shaped DB で実行すること。"
        )

    # 063 のうち public.permissions INSERT 部分だけを抽出して実行 (DO ブロック内の
    # tenant schema 操作は本テスト環境では tenant_NNN schema が無いため、INSERT 部
    # だけテスト目的で実行)
    sql_063 = (MIGRATIONS_DIR / "063_tenant_rbac_extensions.sql").read_text("utf-8")
    # INSERT INTO public.permissions ... の単一文だけを取り出す
    # (DO ブロックは tenant schema 走査だが、permissions INSERT は最上位文)
    async with engine.begin() as conn:
        # 全文を分割して INSERT INTO public.permissions ... を実行
        for stmt in _split_sql_preserving_do_blocks(sql_063):
            s = stmt.strip()
            if not s:
                continue
            if "INSERT INTO public.permissions" in s:
                await conn.exec_driver_sql(s)

    async with engine.connect() as conn:
        result = await conn.execute(text(
            "SELECT key FROM public.permissions "
            "WHERE key IN ("
            "  'inventory.visibility.full',"
            "  'inventory.visibility.staff',"
            "  'inventory.visibility.viewer',"
            "  'tenant.inventory_visibility.edit'"
            ")"
        ))
        keys = {row.key for row in result}
    assert "inventory.visibility.full" in keys
    assert "inventory.visibility.staff" in keys
    assert "inventory.visibility.viewer" in keys
    assert "tenant.inventory_visibility.edit" in keys


# ---------------------------------------------------------------------------
# 追加: inventory_movements 算術トリガ
# ---------------------------------------------------------------------------

async def test_inventory_movements_arithmetic_trigger(engine):
    """AC6.6 関連 (Sprint 1 で基盤投入): after_qty = before_qty + delta_qty が DB 制約。"""
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    await _apply_public_migrations(engine)

    async with engine.begin() as conn:
        # products に 1 行作成
        pid = (await conn.execute(text(
            "INSERT INTO public.products (name, stock_quantity) "
            "VALUES ('test product', 100) RETURNING id"
        ))).scalar_one()

        # 正しい算術 (before=100, delta=-3, after=97) → OK
        await conn.execute(text(
            "INSERT INTO public.inventory_movements "
            "(tenant_id, product_id, delta_qty, before_qty, after_qty, "
            " source_type, operator_id) "
            "VALUES (4, :pid, -3, 100, 97, 'manual_adjust', 1)"
        ), {"pid": pid})

    # 不正な算術 (before=100, delta=-3, after=99) → 例外
    with pytest.raises(DBAPIError):
        async with engine.begin() as conn:
            await conn.execute(text(
                "INSERT INTO public.inventory_movements "
                "(tenant_id, product_id, delta_qty, before_qty, after_qty, "
                " source_type, operator_id) "
                "VALUES (4, :pid, -3, 100, 99, 'manual_adjust', 1)"
            ), {"pid": pid})


# ---------------------------------------------------------------------------
# 追加: knowledge_rules pattern_type CHECK
# ---------------------------------------------------------------------------

async def test_knowledge_rules_pattern_type_check(engine):
    """knowledge_rules.pattern_type に許容外の値で 23514。"""
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    await _apply_public_migrations(engine)

    with pytest.raises(IntegrityError) as ei:
        async with engine.begin() as conn:
            await conn.execute(text(
                "INSERT INTO public.knowledge_rules "
                "(category, pattern_type, pattern, language) "
                "VALUES ('test', 'unknown_pattern_type', '.*', 'ja')"
            ))
    assert "23514" in str(ei.value) or "check" in str(ei.value).lower()
