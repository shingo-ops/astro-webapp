"""inventory.visibility.* permission keys の存在検証 (AC1.8 / AC2.8 / AC7.9 基盤)。

Sprint 1 では permissions 行が public.permissions に挿入されることを検証する。
UI / API 側の権限フィルタリング動作は Sprint 2 / Sprint 7 で検証。

実 PostgreSQL 必須 (SQLite では migration 002 + 063 の通し適用が現実的でない)。
TEST_PG_URL 未設定時は全テスト skip。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

TEST_PG_URL = os.getenv("TEST_PG_URL") or os.getenv("RLS_TEST_DATABASE_URL")

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not TEST_PG_URL,
        reason="実 PostgreSQL 環境が必要 (TEST_PG_URL / RLS_TEST_DATABASE_URL 未設定)。",
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


async def test_inventory_visibility_keys_unique_and_descriptive(engine):
    """AC1.8: inventory.visibility.* 4 件が permissions テーブルに存在する。

    前提:
      - migration 002_add_permissions_master.sql が適用済み (production-shaped DB)
      - migration 063_tenant_rbac_extensions.sql の INSERT 部分が適用済み

    本テストは production-shaped DB を想定。fresh test DB の場合は skip。
    """
    from sqlalchemy import text

    async with engine.connect() as conn:
        exists = (await conn.execute(text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name='permissions'"
        ))).scalar_one_or_none()
    if not exists:
        pytest.skip(
            "public.permissions が未作成。migration 002 を先に適用すること。"
        )

    # 063 の INSERT を実行
    sql_063 = (MIGRATIONS_DIR / "063_tenant_rbac_extensions.sql").read_text("utf-8")
    async with engine.begin() as conn:
        for stmt in _split_sql_preserving_do_blocks(sql_063):
            s = stmt.strip()
            if s and "INSERT INTO public.permissions" in s:
                await conn.exec_driver_sql(s)

    # 4 件の inventory.visibility.* キーを assert
    async with engine.connect() as conn:
        result = await conn.execute(text(
            "SELECT key, resource, action, category FROM public.permissions "
            "WHERE key LIKE 'inventory.visibility.%' "
            "   OR key = 'tenant.inventory_visibility.edit' "
            "ORDER BY key"
        ))
        rows = list(result)

    keys = [r.key for r in rows]
    assert "inventory.visibility.full" in keys
    assert "inventory.visibility.staff" in keys
    assert "inventory.visibility.viewer" in keys
    assert "tenant.inventory_visibility.edit" in keys

    # 全行 category = '在庫'
    for r in rows:
        assert r.category == "在庫", f"category 不正: {r.key}={r.category}"


async def test_idempotent_reapply_permissions(engine):
    """063 の permissions INSERT を 2 回実行しても件数は変わらない (ON CONFLICT DO NOTHING)。"""
    from sqlalchemy import text

    async with engine.connect() as conn:
        exists = (await conn.execute(text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name='permissions'"
        ))).scalar_one_or_none()
    if not exists:
        pytest.skip("public.permissions が未作成")

    sql_063 = (MIGRATIONS_DIR / "063_tenant_rbac_extensions.sql").read_text("utf-8")

    # 1 回目
    async with engine.begin() as conn:
        for stmt in _split_sql_preserving_do_blocks(sql_063):
            s = stmt.strip()
            if s and "INSERT INTO public.permissions" in s:
                await conn.exec_driver_sql(s)

    async with engine.connect() as conn:
        count_first = (await conn.execute(text(
            "SELECT COUNT(*) FROM public.permissions "
            "WHERE key LIKE 'inventory.visibility.%' "
            "   OR key = 'tenant.inventory_visibility.edit'"
        ))).scalar_one()

    # 2 回目
    async with engine.begin() as conn:
        for stmt in _split_sql_preserving_do_blocks(sql_063):
            s = stmt.strip()
            if s and "INSERT INTO public.permissions" in s:
                await conn.exec_driver_sql(s)

    async with engine.connect() as conn:
        count_second = (await conn.execute(text(
            "SELECT COUNT(*) FROM public.permissions "
            "WHERE key LIKE 'inventory.visibility.%' "
            "   OR key = 'tenant.inventory_visibility.edit'"
        ))).scalar_one()

    assert count_first == count_second == 4, (
        f"冪等性違反: 1 回目={count_first} 2 回目={count_second}"
    )
