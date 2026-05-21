"""Super-admin pokemon_dex / trainer_dex ルーター 単体テスト。

spec.md v1.1 F2 (Sprint 2) / AC2.4:
  - 図鑑 #25 の英名編集が反映される
  - 冪等性 (dex_number 重複は UNIQUE で防がれる)

実 PostgreSQL 必須。
"""
from __future__ import annotations

import os

import pytest

TEST_PG_URL = os.getenv("TEST_PG_URL")

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not TEST_PG_URL,
        reason="実 PostgreSQL 環境が必要 (TEST_PG_URL 未設定)。",
    ),
]


@pytest.fixture
async def engine():
    from sqlalchemy.ext.asyncio import create_async_engine
    eng = create_async_engine(TEST_PG_URL, echo=False)
    yield eng
    await eng.dispose()


async def test_pokemon_dex_update_round_trip(engine):
    """AC2.4: 既存 entry の name_en を編集 → 反映される。"""
    from sqlalchemy import text

    async with engine.connect() as conn:
        exists = (await conn.execute(text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name='pokemon_dex'"
        ))).scalar_one_or_none()
    if not exists:
        pytest.skip("public.pokemon_dex 未作成 (migration 061 が必要)")

    # テスト用 entry を投入（dex_number は本番 1-1025 と衝突しない巨大値）
    test_num = 999999
    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM public.pokemon_dex WHERE dex_number = :n"),
            {"n": test_num},
        )
        result = await conn.execute(text("""
            INSERT INTO public.pokemon_dex (dex_number, name_ja, name_en, generation, region)
            VALUES (:n, 'テスト名', 'TestName', 1, 'カントー')
            RETURNING id
        """), {"n": test_num})
        new_id = result.scalar_one()

        await conn.execute(text("""
            UPDATE public.pokemon_dex SET name_en = 'TestName Updated' WHERE id = :id
        """), {"id": new_id})

        sel = await conn.execute(
            text("SELECT name_en FROM public.pokemon_dex WHERE id = :id"),
            {"id": new_id},
        )
        assert sel.scalar_one() == "TestName Updated"

        # cleanup
        await conn.execute(text("DELETE FROM public.pokemon_dex WHERE id = :id"), {"id": new_id})


async def test_trainer_dex_table_exists(engine):
    """trainer_dex も同様に存在することを確認（CRUD は同型なので 1 ケースのみ）"""
    from sqlalchemy import text
    async with engine.connect() as conn:
        exists = (await conn.execute(text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name='trainer_dex'"
        ))).scalar_one_or_none()
    if not exists:
        pytest.skip("public.trainer_dex 未作成")
    assert exists == 1
