"""Super-admin suppliers + supplier_discord_routing CRUD テスト。

spec.md v1.1 F2 (Sprint 2) / AC2.5:
  - supplier_type 切替 (individual / corporate)
  - discord_routing 紐付け
  - UNIQUE(discord_guild_id, discord_channel_id) 検証

実 PostgreSQL 必須。
"""
from __future__ import annotations

import os
import uuid

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


async def test_supplier_type_check_constraint(engine):
    """AC1.7 + AC2.5: 不正な supplier_type は CHECK 制約で 23514。"""
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    async with engine.connect() as conn:
        exists = (await conn.execute(text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name='suppliers'"
        ))).scalar_one_or_none()
    if not exists:
        pytest.skip("public.suppliers 未作成 (migration 056 が必要)")

    raised = False
    try:
        async with engine.begin() as conn:
            await conn.execute(text("""
                INSERT INTO public.suppliers (name, supplier_type, default_language)
                VALUES ('test_invalid_type', 'INVALID', 'ja')
            """))
    except IntegrityError as exc:
        raised = True
        # check_violation = 23514
        assert "23514" in str(exc.orig) or "check" in str(exc.orig).lower()
    assert raised


async def test_supplier_discord_routing_unique(engine):
    """AC2.5: UNIQUE(discord_guild_id, discord_channel_id) で重複不可。"""
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    async with engine.connect() as conn:
        exists = (await conn.execute(text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name='supplier_discord_routing'"
        ))).scalar_one_or_none()
    if not exists:
        pytest.skip("public.supplier_discord_routing 未作成 (migration 060 が必要)")

    # supplier 用意
    sup_name = f"test_supplier_ac2_5_{uuid.uuid4().hex[:6]}"
    async with engine.begin() as conn:
        result = await conn.execute(text("""
            INSERT INTO public.suppliers (name, supplier_type, default_language)
            VALUES (:n, 'corporate', 'ja')
            RETURNING id
        """), {"n": sup_name})
        sup_id = result.scalar_one()

    g_id = f"g_{uuid.uuid4().hex[:10]}"
    c_id = f"c_{uuid.uuid4().hex[:10]}"

    async with engine.begin() as conn:
        await conn.execute(text("""
            INSERT INTO public.supplier_discord_routing
                (supplier_id, discord_guild_id, discord_channel_id, is_active)
            VALUES (:sid, :g, :c, TRUE)
        """), {"sid": sup_id, "g": g_id, "c": c_id})

    raised = False
    try:
        async with engine.begin() as conn:
            # 同じ supplier、同じ guild/channel で再 insert → UNIQUE 違反
            await conn.execute(text("""
                INSERT INTO public.supplier_discord_routing
                    (supplier_id, discord_guild_id, discord_channel_id, is_active)
                VALUES (:sid, :g, :c, TRUE)
            """), {"sid": sup_id, "g": g_id, "c": c_id})
    except IntegrityError as exc:
        raised = True
        assert "23505" in str(exc.orig) or "duplicate" in str(exc.orig).lower()

    assert raised, "UNIQUE 制約が動作していない"

    # cleanup
    async with engine.begin() as conn:
        await conn.execute(text(
            "DELETE FROM public.supplier_discord_routing WHERE supplier_id = :sid"
        ), {"sid": sup_id})
        await conn.execute(text(
            "DELETE FROM public.suppliers WHERE id = :sid"
        ), {"sid": sup_id})
