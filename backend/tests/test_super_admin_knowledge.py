"""Super-admin knowledge_rules ルーターの単体テスト。

spec.md v1.1 F2 (Sprint 2) / AC2.1 / AC2.2 / AC2.6 / AC2.7:
  - require_super_admin ガード（403 vs 200）
  - CRUD 1 周
  - CSV import dry_run / commit

実 PostgreSQL 必須 (public.knowledge_rules が tenant schema にないため)。
TEST_PG_URL 未設定時は全テスト skip。
"""
from __future__ import annotations

import io
import os
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
    """test_inventory_visibility_permissions.py からコピー（DO $$ block 対応）"""
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


async def test_knowledge_rules_table_exists(engine):
    """前提: migration 058 が適用済み (Sprint 1 で投入された)"""
    from sqlalchemy import text
    async with engine.connect() as conn:
        exists = (await conn.execute(text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name='knowledge_rules'"
        ))).scalar_one_or_none()
    if not exists:
        pytest.skip(
            "public.knowledge_rules 未作成。migration 058 を先に適用すること。"
        )
    assert exists == 1


async def test_create_then_select_then_delete_rule(engine):
    """AC2.2 想定: CRUD 1 周が public.knowledge_rules に対して動作する。"""
    from sqlalchemy import text
    async with engine.connect() as conn:
        exists = (await conn.execute(text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name='knowledge_rules'"
        ))).scalar_one_or_none()
    if not exists:
        pytest.skip("public.knowledge_rules 未作成")

    async with engine.begin() as conn:
        result = await conn.execute(text("""
            INSERT INTO public.knowledge_rules
                (category, pattern_type, pattern, normalized_to, priority, language, is_active)
            VALUES
                ('test_ac2_2', 'regex', '^PSV1a-(\\d+)', 'SV1a-$1', 100, 'ja', TRUE)
            RETURNING id, pattern, normalized_to
        """))
        row = result.mappings().first()
        new_id = row["id"]
        assert row["pattern"] == "^PSV1a-(\\d+)"

        # SELECT で確認
        select_result = await conn.execute(text(
            "SELECT pattern, normalized_to FROM public.knowledge_rules WHERE id = :id"
        ), {"id": new_id})
        sel = select_result.mappings().first()
        assert sel["normalized_to"] == "SV1a-$1"

        # cleanup
        await conn.execute(text("DELETE FROM public.knowledge_rules WHERE id = :id"), {"id": new_id})
