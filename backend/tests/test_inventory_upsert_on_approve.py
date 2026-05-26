"""F11 AC11.3: F6 approve 時に public.inventory へ UPSERT されることを検証 (実 PG)。

カバレッジ対象: app/services/inventory_movements.py の条件 4 (UPSERT 分岐)
  - condition 指定あり → public.inventory に INSERT
  - 同一 approve を再実行 → DO UPDATE で既存行を更新
  - condition 指定なし → UPSERT skip (backward compat)
"""

from __future__ import annotations

import json
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


async def _migration_081_ready(engine) -> bool:
    """public.inventory テーブルが存在するか確認 (migration 081 適用済みチェック)。"""
    from sqlalchemy import text

    async with engine.connect() as conn:
        exists = (
            await conn.execute(
                text(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema='public' AND table_name='inventory'"
                )
            )
        ).scalar_one_or_none()
    return exists is not None


async def _fetch_inventory_row(engine, supplier_id: int, product_id: int, condition: str):
    """public.inventory から該当行を取得して dict で返す。なければ None。"""
    from sqlalchemy import text

    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT quantity, unit_price, status, source "
                    "FROM public.inventory "
                    "WHERE supplier_id=:sid AND product_id=:pid AND condition=:cond"
                ),
                {"sid": supplier_id, "pid": product_id, "cond": condition},
            )
        ).mappings().one_or_none()
    return dict(row) if row else None


async def _seed_fixtures(engine, tag: str):
    """テスト用 supplier / product / discord_inbound_message を作成し ID を返す。"""
    from sqlalchemy import text

    async with engine.begin() as conn:
        # テナント
        await conn.execute(
            text(
                "INSERT INTO public.tenants (id, tenant_code, company_name, is_active) "
                "VALUES (6, 'sprint6_test_t6', 'sprint6_test', TRUE) "
                "ON CONFLICT (id) DO NOTHING"
            )
        )
        try:
            await conn.execute(
                text(
                    "INSERT INTO public.tenant_settings (tenant_id, spreadsheet_phase) "
                    "VALUES (6, 'B') "
                    "ON CONFLICT (tenant_id) DO UPDATE SET spreadsheet_phase='B'"
                )
            )
        except Exception:
            pass

        sup_id = (
            await conn.execute(
                text(
                    "INSERT INTO public.suppliers (name, supplier_type, default_language) "
                    "VALUES (:n, 'corporate', 'ja') RETURNING id"
                ),
                {"n": f"inv_upsert_sup_{tag}"},
            )
        ).scalar_one()

        product_id = (
            await conn.execute(
                text(
                    "INSERT INTO public.products "
                    "(tenant_id, product_code, name, stock_quantity) "
                    "VALUES (6, :code, :name, 0) RETURNING id"
                ),
                {"code": f"UPSERT-{tag}", "name": f"UPSERT-{tag}"},
            )
        ).scalar_one()

        msg_id = f"upsert_msg_{tag}"
        inbound_id = (
            await conn.execute(
                text(
                    """
                    INSERT INTO public.discord_inbound_messages
                        (discord_message_id, discord_channel_id, supplier_id,
                         raw_content, parse_status, parse_engine,
                         parse_result_json, received_at, version)
                    VALUES (:mid, :ch, :sid, :raw, 'parsed_rule_only', 'rule_v1',
                            CAST(:prj AS JSONB), NOW(), 0)
                    RETURNING id
                    """
                ),
                {
                    "mid": msg_id,
                    "ch": f"ch_{tag}",
                    "sid": sup_id,
                    "raw": "upsert_test",
                    "prj": json.dumps({"items": []}),
                },
            )
        ).scalar_one()

    return int(sup_id), int(product_id), int(inbound_id)


async def _cleanup(engine, sup_id: int, product_id: int, inbound_id: int) -> None:
    from sqlalchemy import text

    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM public.inventory WHERE supplier_id=:sid"),
            {"sid": sup_id},
        )
        await conn.execute(
            text("DELETE FROM public.inventory_movements WHERE source_id=:iid"),
            {"iid": inbound_id},
        )
        await conn.execute(
            text("DELETE FROM public.discord_inbound_messages WHERE id=:iid"),
            {"iid": inbound_id},
        )
        await conn.execute(
            text("DELETE FROM public.products WHERE id=:pid"),
            {"pid": product_id},
        )
        await conn.execute(
            text("DELETE FROM public.suppliers WHERE id=:sid"),
            {"sid": sup_id},
        )


async def test_inventory_upsert_insert_on_approve(engine):
    """condition 指定あり approve → public.inventory に行が INSERT される。"""
    if not await _migration_081_ready(engine):
        pytest.skip("migration 081 未適用 (public.inventory テーブルなし)")

    from tests.test_parse_review_approve import _client_with_overrides

    tag = uuid.uuid4().hex[:8]
    sup_id, product_id, inbound_id = await _seed_fixtures(engine, tag)

    try:
        client, app = _client_with_overrides(engine, super_admin_id=9060)
        try:
            async with client as c:
                r = await c.post(
                    f"/api/v1/super-admin/parse-review/{inbound_id}/approve",
                    json={
                        "version": 0,
                        "items": [
                            {
                                "product_id": product_id,
                                "delta_qty": 5,
                                "condition": "Sealed box",
                                "quantity_offered": 5,
                                "unit_price": 1000,
                            }
                        ],
                        "skipped_indices": [],
                        "operator_comment": "upsert insert test",
                    },
                )
                assert r.status_code == 200, r.text
        finally:
            app.dependency_overrides.clear()

        row = await _fetch_inventory_row(engine, sup_id, product_id, "Sealed box")
        assert row is not None, "public.inventory に行が INSERT されていない"
        assert row["quantity"] == 5
        assert row["unit_price"] == 1000
        assert row["status"] == "in_stock"
        assert row["source"] == "f6_approved"
    finally:
        await _cleanup(engine, sup_id, product_id, inbound_id)


async def test_inventory_upsert_update_on_second_approve(engine):
    """condition 指定あり approve を2回実行 → DO UPDATE で quantity/unit_price が更新される。"""
    if not await _migration_081_ready(engine):
        pytest.skip("migration 081 未適用 (public.inventory テーブルなし)")

    from sqlalchemy import text
    from tests.test_parse_review_approve import _client_with_overrides

    tag = uuid.uuid4().hex[:8]
    sup_id, product_id, inbound_id = await _seed_fixtures(engine, tag)

    # 2 件目用 inbound
    async with engine.begin() as conn:
        inbound_id2 = (
            await conn.execute(
                text(
                    """
                    INSERT INTO public.discord_inbound_messages
                        (discord_message_id, discord_channel_id, supplier_id,
                         raw_content, parse_status, parse_engine,
                         parse_result_json, received_at, version)
                    VALUES (:mid, :ch, :sid, :raw, 'parsed_rule_only', 'rule_v1',
                            CAST(:prj AS JSONB), NOW(), 0)
                    RETURNING id
                    """
                ),
                {
                    "mid": f"upsert_msg2_{tag}",
                    "ch": f"ch_{tag}",
                    "sid": sup_id,
                    "raw": "upsert_test2",
                    "prj": json.dumps({"items": []}),
                },
            )
        ).scalar_one()

    try:
        client, app = _client_with_overrides(engine, super_admin_id=9061)
        try:
            async with client as c:
                # 1 回目: qty=5, price=1000
                r = await c.post(
                    f"/api/v1/super-admin/parse-review/{inbound_id}/approve",
                    json={
                        "version": 0,
                        "items": [
                            {
                                "product_id": product_id,
                                "delta_qty": 5,
                                "condition": "Sealed box",
                                "quantity_offered": 5,
                                "unit_price": 1000,
                            }
                        ],
                        "skipped_indices": [],
                        "operator_comment": "upsert round 1",
                    },
                )
                assert r.status_code == 200, r.text

                # 2 回目: qty=10, price=1200 → DO UPDATE で上書き
                r = await c.post(
                    f"/api/v1/super-admin/parse-review/{inbound_id2}/approve",
                    json={
                        "version": 0,
                        "items": [
                            {
                                "product_id": product_id,
                                "delta_qty": 5,
                                "condition": "Sealed box",
                                "quantity_offered": 10,
                                "unit_price": 1200,
                            }
                        ],
                        "skipped_indices": [],
                        "operator_comment": "upsert round 2",
                    },
                )
                assert r.status_code == 200, r.text
        finally:
            app.dependency_overrides.clear()

        row = await _fetch_inventory_row(engine, sup_id, product_id, "Sealed box")
        assert row is not None
        assert row["quantity"] == 10, f"UPSERT 後 quantity が更新されていない: {row}"
        assert row["unit_price"] == 1200, f"UPSERT 後 unit_price が更新されていない: {row}"
    finally:
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM public.inventory_movements WHERE source_id=:iid"),
                {"iid": inbound_id2},
            )
            await conn.execute(
                text("DELETE FROM public.discord_inbound_messages WHERE id=:iid"),
                {"iid": inbound_id2},
            )
        await _cleanup(engine, sup_id, product_id, inbound_id)


async def test_inventory_upsert_skip_without_condition(engine):
    """condition 指定なし approve → public.inventory 行は作成されない (backward compat)。"""
    if not await _migration_081_ready(engine):
        pytest.skip("migration 081 未適用 (public.inventory テーブルなし)")

    from tests.test_parse_review_approve import _client_with_overrides

    tag = uuid.uuid4().hex[:8]
    sup_id, product_id, inbound_id = await _seed_fixtures(engine, tag)

    try:
        client, app = _client_with_overrides(engine, super_admin_id=9062)
        try:
            async with client as c:
                r = await c.post(
                    f"/api/v1/super-admin/parse-review/{inbound_id}/approve",
                    json={
                        "version": 0,
                        "items": [{"product_id": product_id, "delta_qty": 3}],
                        "skipped_indices": [],
                        "operator_comment": "no condition backward compat",
                    },
                )
                assert r.status_code == 200, r.text
        finally:
            app.dependency_overrides.clear()

        # condition なし → UPSERT skip → 行が存在しない
        from sqlalchemy import text

        async with engine.connect() as conn:
            count = (
                await conn.execute(
                    text(
                        "SELECT COUNT(*) FROM public.inventory WHERE supplier_id=:sid"
                    ),
                    {"sid": sup_id},
                )
            ).scalar_one()
        assert count == 0, f"condition 未指定なのに inventory 行が作成された: count={count}"
    finally:
        await _cleanup(engine, sup_id, product_id, inbound_id)
