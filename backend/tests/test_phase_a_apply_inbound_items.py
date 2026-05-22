"""Sprint 9 / F9 v1.2: Phase A 並走時の apply_inbound_items 挙動テスト (実 PostgreSQL)。

spec.md v1.2 F9 / AC9.1:
  - Phase A: inventory_movements には記録、products.stock_quantity は **更新しない**
  - 返り値 ApplyResult.stock_quantity_skipped = True
  - 返り値 ApplyResult.phase = "A"

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
                {"c": tenant_code, "n": f"pa_test_{tenant_code}"},
            )
        ).first()
        if row is None:
            raise RuntimeError("tenants INSERT failed")
        return int(row[0])


async def test_phase_a_records_movement_but_skips_stock(engine):
    """AC9.1: Phase A で apply_inbound_items 実行 →
    inventory_movements には行が追加、products.stock_quantity は不変、
    返り値 stock_quantity_skipped=True / phase='A'。
    """
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.services.inventory_movements import apply_inbound_items

    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    tag = uuid.uuid4().hex[:8]
    tenant_id = await _ensure_tenant(engine, f"pa_apply_{tag}")

    # tenant_settings を Phase=A に
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO public.tenant_settings (tenant_id, spreadsheet_phase) "
                "VALUES (:tid, 'A') "
                "ON CONFLICT (tenant_id) DO UPDATE SET spreadsheet_phase='A'"
            ),
            {"tid": tenant_id},
        )

        # product 作成、stock_quantity=100 で開始
        pid = (
            await conn.execute(
                text(
                    "INSERT INTO public.products (tenant_id, product_code, name, stock_quantity) "
                    "VALUES (:tid, :code, :n, 100) RETURNING id"
                ),
                {"tid": tenant_id, "code": f"PA-{tag}", "n": f"PA-{tag}"},
            )
        ).scalar_one()
        # discord_inbound_messages 1 件 seed
        iid = (
            await conn.execute(
                text(
                    """
                    INSERT INTO public.discord_inbound_messages
                        (discord_message_id, discord_channel_id, supplier_id,
                         raw_content, parse_status, parse_engine,
                         parse_result_json, received_at, version)
                    VALUES (:mid, :ch, NULL, 'phase_a_test', 'parsed_rule_only', 'rule_v1',
                            CAST('{}' AS JSONB), NOW(), 0)
                    RETURNING id
                    """
                ),
                {"mid": f"pa_msg_{tag}", "ch": f"pa_ch_{tag}"},
            )
        ).scalar_one()

    try:
        async with SessionLocal() as db:
            result = await apply_inbound_items(
                db,
                inbound_id=int(iid),
                items=[{"product_id": int(pid), "delta_qty": 10}],
                operator_id=9001,
                supplier_id=None,
            )
            await db.commit()

        assert result.phase == "A", f"phase 期待 'A'、実 {result.phase!r}"
        assert result.stock_quantity_skipped is True, "Phase A で skip フラグが立つこと"
        assert result.stock_updates_applied == 0
        assert result.stock_updates_skipped == 1
        assert len(result.movements) == 1
        assert result.movements[0].delta_qty == 10
        assert result.movements[0].before_qty == 100
        assert result.movements[0].after_qty == 110  # 計算上は after = before + delta

        # DB 検証
        async with engine.connect() as conn:
            stock = (
                await conn.execute(
                    text("SELECT stock_quantity FROM public.products WHERE id = :pid"),
                    {"pid": int(pid)},
                )
            ).scalar_one()
            assert stock == 100, (
                f"Phase A: products.stock_quantity は不変 (期待 100、実 {stock})"
            )

            mov_count = (
                await conn.execute(
                    text(
                        "SELECT COUNT(*) FROM public.inventory_movements "
                        "WHERE product_id = :pid"
                    ),
                    {"pid": int(pid)},
                )
            ).scalar_one()
            assert mov_count == 1, "inventory_movements には記録される"

    finally:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "DELETE FROM public.inventory_movements WHERE product_id = :pid"
                ),
                {"pid": int(pid)},
            )
            await conn.execute(
                text("DELETE FROM public.products WHERE id = :pid"),
                {"pid": int(pid)},
            )
            await conn.execute(
                text("DELETE FROM public.discord_inbound_messages WHERE id = :iid"),
                {"iid": int(iid)},
            )
            await conn.execute(
                text("DELETE FROM public.tenant_settings WHERE tenant_id = :tid"),
                {"tid": tenant_id},
            )


async def test_explicit_phase_b_overrides_tenant_settings(engine):
    """phase='B' 明示渡し → tenant_settings の 'A' を上書きして stock 更新する。"""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.services.inventory_movements import apply_inbound_items

    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    tag = uuid.uuid4().hex[:8]
    tenant_id = await _ensure_tenant(engine, f"pa_override_{tag}")

    async with engine.begin() as conn:
        # tenant_settings は Phase=A
        await conn.execute(
            text(
                "INSERT INTO public.tenant_settings (tenant_id, spreadsheet_phase) "
                "VALUES (:tid, 'A') "
                "ON CONFLICT (tenant_id) DO UPDATE SET spreadsheet_phase='A'"
            ),
            {"tid": tenant_id},
        )
        pid = (
            await conn.execute(
                text(
                    "INSERT INTO public.products (tenant_id, product_code, name, stock_quantity) "
                    "VALUES (:tid, :code, :n, 50) RETURNING id"
                ),
                {"tid": tenant_id, "code": f"PA-OV-{tag}", "n": f"PA-OV-{tag}"},
            )
        ).scalar_one()
        iid = (
            await conn.execute(
                text(
                    """
                    INSERT INTO public.discord_inbound_messages
                        (discord_message_id, discord_channel_id, supplier_id,
                         raw_content, parse_status, parse_engine,
                         parse_result_json, received_at, version)
                    VALUES (:mid, :ch, NULL, 'override', 'parsed_rule_only', 'rule_v1',
                            CAST('{}' AS JSONB), NOW(), 0)
                    RETURNING id
                    """
                ),
                {"mid": f"ov_msg_{tag}", "ch": f"ov_ch_{tag}"},
            )
        ).scalar_one()

    try:
        async with SessionLocal() as db:
            # 明示 phase='B' で apply
            result = await apply_inbound_items(
                db,
                inbound_id=int(iid),
                items=[{"product_id": int(pid), "delta_qty": 7}],
                operator_id=9002,
                supplier_id=None,
                phase="B",
            )
            await db.commit()

        assert result.phase == "B"
        assert result.stock_quantity_skipped is False
        assert result.stock_updates_applied == 1

        async with engine.connect() as conn:
            stock = (
                await conn.execute(
                    text("SELECT stock_quantity FROM public.products WHERE id = :pid"),
                    {"pid": int(pid)},
                )
            ).scalar_one()
            assert stock == 57, f"明示 Phase='B' で stock 更新されること (50+7=57、実 {stock})"

    finally:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "DELETE FROM public.inventory_movements WHERE product_id = :pid"
                ),
                {"pid": int(pid)},
            )
            await conn.execute(
                text("DELETE FROM public.products WHERE id = :pid"),
                {"pid": int(pid)},
            )
            await conn.execute(
                text("DELETE FROM public.discord_inbound_messages WHERE id = :iid"),
                {"iid": int(iid)},
            )
            await conn.execute(
                text("DELETE FROM public.tenant_settings WHERE tenant_id = :tid"),
                {"tid": tenant_id},
            )
