"""Super-admin supplier_aliases ルーターのテスト。

spec.md v1.1 F1 AC1.2 / F2 AC2.6:
  - UNIQUE(supplier_id, alias_text, language) で 23505 が返ることを確認

実 PostgreSQL 必須。
"""
from __future__ import annotations

import os
from pathlib import Path

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


async def test_supplier_aliases_unique_constraint(engine):
    """AC1.2 確認: 同一 (supplier_id, alias_text, language) は重複不可。"""
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    async with engine.connect() as conn:
        exists = (await conn.execute(text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name='supplier_aliases'"
        ))).scalar_one_or_none()
    if not exists:
        pytest.skip("public.supplier_aliases 未作成 (migration 057 が必要)")

    # 任意の supplier を 1 行用意 / なければ skip
    async with engine.connect() as conn:
        sup = (await conn.execute(text(
            "SELECT id FROM public.suppliers WHERE is_active = TRUE LIMIT 1"
        ))).scalar_one_or_none()
    if not sup:
        pytest.skip("public.suppliers が空。Sprint 1 seed が未走行か?")

    test_alias = "TEST_AC1_2_RIZA_eX_SAR"

    # cleanup: 既存があれば消す
    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM public.supplier_aliases WHERE alias_text = :a"),
            {"a": test_alias},
        )

    async with engine.begin() as conn:
        await conn.execute(text("""
            INSERT INTO public.supplier_aliases
                (supplier_id, alias_text, language, source)
            VALUES (:sid, :alias, 'ja', 'manual')
        """), {"sid": sup, "alias": test_alias})

    # 同じ supplier_id × alias × language で再 INSERT → IntegrityError
    raised = False
    try:
        async with engine.begin() as conn:
            await conn.execute(text("""
                INSERT INTO public.supplier_aliases
                    (supplier_id, alias_text, language, source)
                VALUES (:sid, :alias, 'ja', 'manual')
            """), {"sid": sup, "alias": test_alias})
    except IntegrityError as exc:
        raised = True
        assert "23505" in str(exc.orig) or "duplicate" in str(exc.orig).lower()

    assert raised, "UNIQUE 制約が動作していない"

    # cleanup
    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM public.supplier_aliases WHERE alias_text = :a"),
            {"a": test_alias},
        )


async def test_supplier_aliases_different_language_allowed(engine):
    """同じ alias_text でも language が異なれば許容される（en 版と ja 版を共存）。"""
    from sqlalchemy import text

    async with engine.connect() as conn:
        exists = (await conn.execute(text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name='supplier_aliases'"
        ))).scalar_one_or_none()
    if not exists:
        pytest.skip("public.supplier_aliases 未作成")

    async with engine.connect() as conn:
        sup = (await conn.execute(text(
            "SELECT id FROM public.suppliers WHERE is_active = TRUE LIMIT 1"
        ))).scalar_one_or_none()
    if not sup:
        pytest.skip("public.suppliers が空")

    test_alias = "TEST_AC2_LANG_SPLIT"

    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM public.supplier_aliases WHERE alias_text = :a"),
            {"a": test_alias},
        )

    async with engine.begin() as conn:
        await conn.execute(text("""
            INSERT INTO public.supplier_aliases
                (supplier_id, alias_text, language, source)
            VALUES (:sid, :alias, 'ja', 'manual')
        """), {"sid": sup, "alias": test_alias})
        # 同じ alias、 en 版は OK
        await conn.execute(text("""
            INSERT INTO public.supplier_aliases
                (supplier_id, alias_text, language, source)
            VALUES (:sid, :alias, 'en', 'manual')
        """), {"sid": sup, "alias": test_alias})

    async with engine.connect() as conn:
        cnt = (await conn.execute(
            text("SELECT COUNT(*) FROM public.supplier_aliases WHERE alias_text = :a"),
            {"a": test_alias},
        )).scalar_one()
    assert cnt == 2, "ja と en が両方挿入されているはず"

    # cleanup
    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM public.supplier_aliases WHERE alias_text = :a"),
            {"a": test_alias},
        )
