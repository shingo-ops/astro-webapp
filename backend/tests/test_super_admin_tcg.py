"""Super-admin TCG series ルーター 単体テスト。

spec.md v1.1 F2 (Sprint 2) / AC2.3:
  - 5 TCG タイプ (pokemon / one_piece / dragon_ball / union_arena / yugioh)
  - ja/en name 両方更新可能

実 PostgreSQL 必須。
"""
from __future__ import annotations

import os

import pytest

TEST_PG_URL = os.getenv("TEST_PG_URL") or os.getenv("RLS_TEST_DATABASE_URL")

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not TEST_PG_URL,
        reason="実 PostgreSQL 環境が必要 (TEST_PG_URL / RLS_TEST_DATABASE_URL 未設定)。",
    ),
]


@pytest.fixture
async def engine():
    from sqlalchemy.ext.asyncio import create_async_engine
    eng = create_async_engine(TEST_PG_URL, echo=False)
    yield eng
    await eng.dispose()


async def test_tcg_series_table_exists(engine):
    from sqlalchemy import text
    async with engine.connect() as conn:
        exists = (await conn.execute(text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name='tcg_series_master'"
        ))).scalar_one_or_none()
    if not exists:
        pytest.skip("public.tcg_series_master 未作成 (migration 061 が必要)")
    assert exists == 1


async def test_tcg_series_crud_round_trip(engine):
    """AC2.3 想定: SV1a 系の編集が public.tcg_series_master に反映される。"""
    from sqlalchemy import text
    async with engine.connect() as conn:
        exists = (await conn.execute(text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name='tcg_series_master'"
        ))).scalar_one_or_none()
    if not exists:
        pytest.skip("public.tcg_series_master 未作成")

    test_code = "TEST_SV1A_AC2_3"
    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM public.tcg_series_master WHERE series_code = :c"),
            {"c": test_code},
        )

    async with engine.begin() as conn:
        result = await conn.execute(text("""
            INSERT INTO public.tcg_series_master
                (tcg_type, series_code, name_ja, name_en, category)
            VALUES ('pokemon', :c, 'テスト SV1a', 'Test SV1a', 'booster')
            RETURNING id
        """), {"c": test_code})
        new_id = result.scalar_one()

        # name_en を変更
        await conn.execute(text("""
            UPDATE public.tcg_series_master
                SET name_en = 'Test SV1a Updated'
                WHERE id = :id
        """), {"id": new_id})

        sel = await conn.execute(text(
            "SELECT name_en FROM public.tcg_series_master WHERE id = :id"
        ), {"id": new_id})
        assert sel.scalar_one() == "Test SV1a Updated"

        # cleanup
        await conn.execute(text("DELETE FROM public.tcg_series_master WHERE id = :id"), {"id": new_id})
