"""Sprint 11 / F11 AC11.3: apply_inbound_items が public.inventory に UPSERT する挙動の検証 (実 PostgreSQL)。

spec.md v1.3 F11 AC11.3:
  - Phase B/C + supplier_id 指定 + items.condition 指定 の場合のみ
    public.inventory (supplier_id × product_id × condition UNIQUE) を UPSERT する
  - condition 未指定なら inventory UPSERT は skip (後方互換)
  - quantity_offered 未指定なら after_qty で代替
  - unit_price 未指定なら 0 で記録

SQLite モック禁止 (memory: feedback_evaluator_gap_2026_05_15)。
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


async def _ensure_tenant(engine, tenant_code: str) -> int:
    from sqlalchemy import text

    async with engine.begin() as conn:
        row = (
            await conn.execute(
                text("SELECT id FROM public.tenants WHERE tenant_code = :code"),
                {"code": tenant_code},
            )
        ).first()
        if row is not None:
            return int(row[0])
        row = (
            await conn.execute(
                text(
                    "INSERT INTO public.tenants (tenant_code, company_name, is_active) "
                    "VALUES (:c, :n, TRUE) RETURNING id"
                ),
                {"c": tenant_code, "n": f"f11_test_{tenant_code}"},
            )
        ).first()
        if row is None:
            raise RuntimeError("tenants INSERT failed")
        return int(row[0])


async def _create_supplier(engine, tag: str) -> int:
    from sqlalchemy import text

    async with engine.begin() as conn:
        row = (
            await conn.execute(
                text(
                    "INSERT INTO public.suppliers (supplier_code, name, type, language) "
                    "VALUES (:code, :name, 'individual', 'ja') RETURNING id"
                ),
                {"code": f"F11-S-{tag}", "name": f"f11_supplier_{tag}"},
            )
        ).first()
        if row is None:
            raise RuntimeError("suppliers INSERT failed")
        return int(row[0])


async def _create_inbound(engine, tag: str) -> int:
    from sqlalchemy import text

    async with engine.begin() as conn:
        row = (
            await conn.execute(
                text(
                    """
                    INSERT INTO public.discord_inbound_messages
                        (discord_message_id, discord_channel_id, supplier_id,
                         raw_content, parse_status, parse_engine,
                         parse_result_json, received_at, version)
                    VALUES (:mid, :ch, NULL, 'f11_test', 'parsed_rule_only', 'rule_v1',
                            CAST('{}' AS JSONB), NOW(), 0)
                    RETURNING id
                    """
                ),
                {"mid": f"f11_msg_{tag}", "ch": f"f11_ch_{tag}"},
            )
        ).first()
        if row is None:
            raise RuntimeError("discord_inbound_messages INSERT failed")
        return int(row[0])


async def _cleanup(engine, *, pid: int, iid: int, tenant_id: int, supplier_id: int):
    from sqlalchemy import text

    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM public.inventory WHERE product_id = :pid"),
            {"pid": pid},
        )
        await conn.execute(
            text("DELETE FROM public.inventory_movements WHERE product_id = :pid"),
            {"pid": pid},
        )
        await conn.execute(
            text("DELETE FROM public.products WHERE id = :pid"),
            {"pid": pid},
        )
        await conn.execute(
            text("DELETE FROM public.discord_inbound_messages WHERE id = :iid"),
            {"iid": iid},
        )
        await conn.execute(
            text("DELETE FROM public.suppliers WHERE id = :sid"),
            {"sid": supplier_id},
        )
        await conn.execute(
            text("DELETE FROM public.tenant_settings WHERE tenant_id = :tid"),
            {"tid": tenant_id},
        )


async def test_f11_upsert_inserts_when_condition_specified(engine):
    """AC11.3: Phase B + supplier_id + condition 指定 → public.inventory に INSERT される。"""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.services.inventory_movements import apply_inbound_items

    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    tag = uuid.uuid4().hex[:8]
    tenant_id = await _ensure_tenant(engine, f"f11_ins_{tag}")
    supplier_id = await _create_supplier(engine, tag)

    async with engine.begin() as conn:
        pid = (
            await conn.execute(
                text(
                    "INSERT INTO public.products (tenant_id, product_code, name, stock_quantity) "
                    "VALUES (:tid, :code, :n, 0) RETURNING id"
                ),
                {"tid": tenant_id, "code": f"F11P-{tag}", "n": f"f11_product_{tag}"},
            )
        ).scalar_one()
    iid = await _create_inbound(engine, tag)

    try:
        async with SessionLocal() as db:
            result = await apply_inbound_items(
                db,
                inbound_id=iid,
                items=[
                    {
                        "product_id": int(pid),
                        "delta_qty": 5,
                        "condition": "new",
                        "quantity_offered": 12,
                        "unit_price": 4500,
                    }
                ],
                operator_id=9101,
                supplier_id=supplier_id,
                phase="B",
            )
            await db.commit()

        assert result.phase == "B"
        assert result.stock_updates_applied == 1
        assert len(result.movements) == 1

        async with engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT supplier_id, product_id, condition, quantity, unit_price, "
                        "       status, source "
                        "FROM public.inventory "
                        "WHERE supplier_id = :sid AND product_id = :pid AND condition = 'new'"
                    ),
                    {"sid": supplier_id, "pid": int(pid)},
                )
            ).mappings().first()
            assert row is not None, "public.inventory に INSERT されること"
            assert row["quantity"] == 12, f"quantity_offered 反映 (期待 12、実 {row['quantity']})"
            assert row["unit_price"] == 4500
            assert row["status"] == "in_stock"
            assert row["source"] == "f6_approved"
    finally:
        await _cleanup(
            engine,
            pid=int(pid),
            iid=iid,
            tenant_id=tenant_id,
            supplier_id=supplier_id,
        )


async def test_f11_upsert_updates_on_conflict(engine):
    """AC11.3: 同一 supplier × product × condition の 2 回目 approve で UPDATE (UPSERT)。"""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.services.inventory_movements import apply_inbound_items

    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    tag = uuid.uuid4().hex[:8]
    tenant_id = await _ensure_tenant(engine, f"f11_upd_{tag}")
    supplier_id = await _create_supplier(engine, tag)

    async with engine.begin() as conn:
        pid = (
            await conn.execute(
                text(
                    "INSERT INTO public.products (tenant_id, product_code, name, stock_quantity) "
                    "VALUES (:tid, :code, :n, 0) RETURNING id"
                ),
                {"tid": tenant_id, "code": f"F11U-{tag}", "n": f"f11_upd_{tag}"},
            )
        ).scalar_one()
    iid1 = await _create_inbound(engine, f"{tag}_a")
    iid2 = await _create_inbound(engine, f"{tag}_b")

    try:
        # 1 回目: quantity=10, price=3000
        async with SessionLocal() as db:
            await apply_inbound_items(
                db,
                inbound_id=iid1,
                items=[
                    {
                        "product_id": int(pid),
                        "delta_qty": 10,
                        "condition": "used_a",
                        "quantity_offered": 10,
                        "unit_price": 3000,
                    }
                ],
                operator_id=9102,
                supplier_id=supplier_id,
                phase="B",
            )
            await db.commit()

        # 2 回目: quantity=25, price=2800 で同じ supplier×product×condition
        async with SessionLocal() as db:
            await apply_inbound_items(
                db,
                inbound_id=iid2,
                items=[
                    {
                        "product_id": int(pid),
                        "delta_qty": 15,
                        "condition": "used_a",
                        "quantity_offered": 25,
                        "unit_price": 2800,
                    }
                ],
                operator_id=9102,
                supplier_id=supplier_id,
                phase="B",
            )
            await db.commit()

        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT quantity, unit_price FROM public.inventory "
                        "WHERE supplier_id = :sid AND product_id = :pid "
                        "  AND condition = 'used_a'"
                    ),
                    {"sid": supplier_id, "pid": int(pid)},
                )
            ).all()
            assert len(rows) == 1, "UNIQUE 制約により 1 行のみ存在"
            assert rows[0][0] == 25, f"quantity が UPDATE される (期待 25、実 {rows[0][0]})"
            assert rows[0][1] == 2800
    finally:
        for iid in (iid1, iid2):
            async with engine.begin() as conn:
                await conn.execute(
                    text("DELETE FROM public.discord_inbound_messages WHERE id = :iid"),
                    {"iid": iid},
                )
        await _cleanup(
            engine,
            pid=int(pid),
            iid=iid1,  # already deleted, but cleanup is idempotent
            tenant_id=tenant_id,
            supplier_id=supplier_id,
        )


async def test_f11_upsert_skipped_when_condition_missing(engine):
    """AC11.3: condition 未指定 → public.inventory に行が作られない (後方互換)。"""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.services.inventory_movements import apply_inbound_items

    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    tag = uuid.uuid4().hex[:8]
    tenant_id = await _ensure_tenant(engine, f"f11_skip_{tag}")
    supplier_id = await _create_supplier(engine, tag)

    async with engine.begin() as conn:
        pid = (
            await conn.execute(
                text(
                    "INSERT INTO public.products (tenant_id, product_code, name, stock_quantity) "
                    "VALUES (:tid, :code, :n, 0) RETURNING id"
                ),
                {"tid": tenant_id, "code": f"F11S-{tag}", "n": f"f11_skip_{tag}"},
            )
        ).scalar_one()
    iid = await _create_inbound(engine, tag)

    try:
        async with SessionLocal() as db:
            await apply_inbound_items(
                db,
                inbound_id=iid,
                items=[
                    {"product_id": int(pid), "delta_qty": 3},  # condition なし
                ],
                operator_id=9103,
                supplier_id=supplier_id,
                phase="B",
            )
            await db.commit()

        async with engine.connect() as conn:
            cnt = (
                await conn.execute(
                    text(
                        "SELECT COUNT(*) FROM public.inventory "
                        "WHERE supplier_id = :sid AND product_id = :pid"
                    ),
                    {"sid": supplier_id, "pid": int(pid)},
                )
            ).scalar_one()
            assert cnt == 0, "condition 未指定 → inventory への UPSERT は skip される"
    finally:
        await _cleanup(
            engine,
            pid=int(pid),
            iid=iid,
            tenant_id=tenant_id,
            supplier_id=supplier_id,
        )


async def test_f11_upsert_skipped_when_supplier_id_none(engine):
    """AC11.3: supplier_id=None → condition 指定でも inventory に行が作られない。"""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.services.inventory_movements import apply_inbound_items

    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    tag = uuid.uuid4().hex[:8]
    tenant_id = await _ensure_tenant(engine, f"f11_ns_{tag}")

    async with engine.begin() as conn:
        pid = (
            await conn.execute(
                text(
                    "INSERT INTO public.products (tenant_id, product_code, name, stock_quantity) "
                    "VALUES (:tid, :code, :n, 0) RETURNING id"
                ),
                {"tid": tenant_id, "code": f"F11NS-{tag}", "n": f"f11_ns_{tag}"},
            )
        ).scalar_one()
    iid = await _create_inbound(engine, tag)

    try:
        async with SessionLocal() as db:
            await apply_inbound_items(
                db,
                inbound_id=iid,
                items=[
                    {
                        "product_id": int(pid),
                        "delta_qty": 2,
                        "condition": "new",
                        "quantity_offered": 2,
                        "unit_price": 1000,
                    }
                ],
                operator_id=9104,
                supplier_id=None,  # ← AC11.3 の前提条件不成立
                phase="B",
            )
            await db.commit()

        async with engine.connect() as conn:
            cnt = (
                await conn.execute(
                    text(
                        "SELECT COUNT(*) FROM public.inventory WHERE product_id = :pid"
                    ),
                    {"pid": int(pid)},
                )
            ).scalar_one()
            assert cnt == 0, "supplier_id=None → inventory UPSERT 不可"
    finally:
        from sqlalchemy import text as _text
        async with engine.begin() as conn:
            await conn.execute(
                _text("DELETE FROM public.inventory_movements WHERE product_id = :pid"),
                {"pid": int(pid)},
            )
            await conn.execute(
                _text("DELETE FROM public.products WHERE id = :pid"),
                {"pid": int(pid)},
            )
            await conn.execute(
                _text("DELETE FROM public.discord_inbound_messages WHERE id = :iid"),
                {"iid": iid},
            )
            await conn.execute(
                _text("DELETE FROM public.tenant_settings WHERE tenant_id = :tid"),
                {"tid": tenant_id},
            )


async def test_f11_upsert_skipped_in_phase_a(engine):
    """AC11.3: Phase A → products も inventory も更新しない (stock_quantity skip と一貫)。"""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.services.inventory_movements import apply_inbound_items

    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    tag = uuid.uuid4().hex[:8]
    tenant_id = await _ensure_tenant(engine, f"f11_pa_{tag}")
    supplier_id = await _create_supplier(engine, tag)

    async with engine.begin() as conn:
        pid = (
            await conn.execute(
                text(
                    "INSERT INTO public.products (tenant_id, product_code, name, stock_quantity) "
                    "VALUES (:tid, :code, :n, 0) RETURNING id"
                ),
                {"tid": tenant_id, "code": f"F11PA-{tag}", "n": f"f11_pa_{tag}"},
            )
        ).scalar_one()
    iid = await _create_inbound(engine, tag)

    try:
        async with SessionLocal() as db:
            result = await apply_inbound_items(
                db,
                inbound_id=iid,
                items=[
                    {
                        "product_id": int(pid),
                        "delta_qty": 4,
                        "condition": "new",
                        "quantity_offered": 4,
                        "unit_price": 500,
                    }
                ],
                operator_id=9105,
                supplier_id=supplier_id,
                phase="A",  # ← Phase A 明示
            )
            await db.commit()

        assert result.phase == "A"
        assert result.stock_updates_skipped == 1
        assert result.stock_updates_applied == 0

        async with engine.connect() as conn:
            cnt = (
                await conn.execute(
                    text(
                        "SELECT COUNT(*) FROM public.inventory "
                        "WHERE supplier_id = :sid AND product_id = :pid"
                    ),
                    {"sid": supplier_id, "pid": int(pid)},
                )
            ).scalar_one()
            assert cnt == 0, "Phase A → inventory UPSERT も skip"
    finally:
        await _cleanup(
            engine,
            pid=int(pid),
            iid=iid,
            tenant_id=tenant_id,
            supplier_id=supplier_id,
        )
