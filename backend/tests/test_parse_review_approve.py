"""Sprint 6 (F6) parse review approve エンドポイントの E2E (実 Postgres)。

AC6.1: POST /api/v1/super-admin/parse-review/{id}/approve で
       inventory_movements 行追加 + products.stock_quantity が delta_qty だけ動く
AC6.2: parse_status='approved' / operator_comment / operator_id 保存
AC6.3: skipped_indices が parse_result_json.skipped[] に保存される
AC6.6: SUM(delta_qty WHERE product_id=X) == products.stock_quantity 不変条件

SQLite モック禁止 (memory: feedback_evaluator_gap_2026_05_15)。
TEST_PG_URL 未設定時は skip。
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


@pytest.fixture
async def seed_inbound_with_product(engine):
    """1 件の inbound + 1 件 supplier + 2 件 products を seed。

    Returns:
      dict with inbound_id, supplier_id, product_ids (list of 2), channel_id
    """
    from sqlalchemy import text

    tag = uuid.uuid4().hex[:8]
    sup_name = f"sprint6_sup_{tag}"
    channel_id = f"c_review_{tag}"
    msg_id = f"sprint6_msg_{tag}"
    prod_codes = [f"S6-PROD-A-{tag}", f"S6-PROD-B-{tag}"]
    product_ids: list[int] = []

    async with engine.begin() as conn:
        exists = (
            await conn.execute(
                text(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema='public' AND table_name='discord_inbound_messages'"
                )
            )
        ).scalar_one_or_none()
        if not exists:
            pytest.skip("public.discord_inbound_messages 未作成 (migration 059)")

        # migration 067 が適用済か確認
        version_col = (
            await conn.execute(
                text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_schema='public' AND table_name='discord_inbound_messages' "
                    "AND column_name='version'"
                )
            )
        ).scalar_one_or_none()
        if not version_col:
            pytest.skip("migration 067 未適用 (version 列なし)")

        sup_id = (
            await conn.execute(
                text(
                    "INSERT INTO public.suppliers (name, supplier_type, default_language) "
                    "VALUES (:n, 'corporate', 'ja') RETURNING id"
                ),
                {"n": sup_name},
            )
        ).scalar_one()

        for code in prod_codes:
            pid = (
                await conn.execute(
                    text(
                        "INSERT INTO public.products (tenant_id, product_code, name, stock_quantity) "
                        "VALUES (6, :code, :name, 0) RETURNING id"
                    ),
                    {"code": code, "name": code},
                )
            ).scalar_one()
            product_ids.append(int(pid))

        # inbound seed: parse_result_json に items 2 件
        parse_result = {
            "items": [
                {"product_id": product_ids[0], "delta_qty": 3, "alias_text": "AAA"},
                {"product_id": product_ids[1], "delta_qty": 5, "alias_text": "BBB"},
            ],
            "excludes": [],
            "unparsed": [],
        }
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
                    "ch": channel_id,
                    "sid": sup_id,
                    "raw": "test raw",
                    "prj": json.dumps(parse_result),
                },
            )
        ).scalar_one()

    yield {
        "inbound_id": int(inbound_id),
        "supplier_id": int(sup_id),
        "product_ids": product_ids,
        "channel_id": channel_id,
    }

    # cleanup
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "DELETE FROM public.inventory_movements WHERE source_id = :iid AND source_type = 'discord_inbound_review'"
            ),
            {"iid": inbound_id},
        )
        await conn.execute(
            text("DELETE FROM public.discord_inbound_messages WHERE id = :iid"),
            {"iid": inbound_id},
        )
        for pid in product_ids:
            await conn.execute(
                text("DELETE FROM public.products WHERE id = :pid"), {"pid": pid}
            )
        await conn.execute(
            text("DELETE FROM public.suppliers WHERE id = :sid"), {"sid": sup_id}
        )


def _client_with_overrides(engine, *, super_admin_id: int = 9001):
    """ASGITransport クライアントを返し、get_db を PG engine 経由に差し替える。

    既存 conftest が SQLite を強制するので、本テストでは get_db を override し
    実 PG セッションを yield することで API ハンドラ内 SQL を PG で実行する。
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    from app.database import get_db
    from app.auth.dependencies import require_super_admin
    from app.models import User

    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    async def override_get_db():
        async with SessionLocal() as session:
            yield session

    async def fake_super_admin() -> User:
        u = User()
        u.id = super_admin_id
        u.is_super_admin = True
        u.role = "admin"
        u.tenant_id = 6
        return u

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_super_admin] = fake_super_admin

    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test"), app


async def test_approve_writes_inventory_and_updates_stock(
    engine, seed_inbound_with_product
):
    """AC6.1 / AC6.2 / AC6.6: approve で movements + products + 不変条件 OK。"""
    from sqlalchemy import text

    ctx = seed_inbound_with_product
    inbound_id = ctx["inbound_id"]
    product_ids = ctx["product_ids"]

    client, app = _client_with_overrides(engine, super_admin_id=9001)
    try:
        async with client as c:
            payload = {
                "version": 0,
                "items": [
                    {"product_id": product_ids[0], "delta_qty": 3},
                    {"product_id": product_ids[1], "delta_qty": 5},
                ],
                "skipped_indices": [],
                "operator_comment": "ok by tester",
            }
            r = await c.post(
                f"/api/v1/super-admin/parse-review/{inbound_id}/approve",
                json=payload,
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["parse_status"] == "approved"
            assert body["version"] == 1
            assert len(body["movements"]) == 2

        # === DB 検証 ===
        async with engine.connect() as conn:
            # AC6.2: parse_status / operator_id / operator_comment
            inbound = (
                (
                    await conn.execute(
                        text(
                            "SELECT parse_status, operator_id, operator_comment, version, approved_at "
                            "FROM public.discord_inbound_messages WHERE id = :id"
                        ),
                        {"id": inbound_id},
                    )
                )
                .mappings()
                .first()
            )
            assert inbound["parse_status"] == "approved"
            assert inbound["operator_id"] == 9001
            assert inbound["operator_comment"] == "ok by tester"
            assert inbound["version"] == 1
            assert inbound["approved_at"] is not None

            # AC6.1: inventory_movements 2 行追加 + products stock_quantity 反映
            mov_rows = (
                (
                    await conn.execute(
                        text(
                            "SELECT product_id, delta_qty, before_qty, after_qty, source_type, source_id "
                            "FROM public.inventory_movements WHERE source_id = :iid "
                            "ORDER BY product_id"
                        ),
                        {"iid": inbound_id},
                    )
                )
                .mappings()
                .all()
            )
            assert len(mov_rows) == 2
            assert all(m["source_type"] == "discord_inbound_review" for m in mov_rows)

            # products.stock_quantity
            for pid, expected_delta in zip(product_ids, [3, 5]):
                stock = (
                    await conn.execute(
                        text(
                            "SELECT stock_quantity FROM public.products WHERE id = :pid"
                        ),
                        {"pid": pid},
                    )
                ).scalar_one()
                assert stock == expected_delta, (
                    f"product {pid} stock expected {expected_delta} got {stock}"
                )

                # AC6.6: SUM(delta_qty) == stock_quantity
                dsum = (
                    await conn.execute(
                        text(
                            "SELECT COALESCE(SUM(delta_qty), 0) "
                            "FROM public.inventory_movements WHERE product_id = :pid"
                        ),
                        {"pid": pid},
                    )
                ).scalar_one()
                assert dsum == stock, (
                    f"AC6.6 invariant violated for product {pid}: "
                    f"SUM={dsum} stock={stock}"
                )
    finally:
        app.dependency_overrides.clear()


async def test_approve_records_skipped_indices(engine, seed_inbound_with_product):
    """AC6.3: skipped_indices が parse_result_json.skipped[] に保存される。"""
    from sqlalchemy import text

    ctx = seed_inbound_with_product
    inbound_id = ctx["inbound_id"]

    client, app = _client_with_overrides(engine)
    try:
        async with client as c:
            payload = {
                "version": 0,
                "items": [],  # 全 skip 想定
                "skipped_indices": [0, 1],
                "operator_comment": "全 skip",
            }
            r = await c.post(
                f"/api/v1/super-admin/parse-review/{inbound_id}/approve",
                json=payload,
            )
            assert r.status_code == 200, r.text

        async with engine.connect() as conn:
            prj = (
                await conn.execute(
                    text(
                        "SELECT parse_result_json FROM public.discord_inbound_messages WHERE id = :id"
                    ),
                    {"id": inbound_id},
                )
            ).scalar_one()
            # JSONB は dict で返る (asyncpg)
            if isinstance(prj, str):
                prj = json.loads(prj)
            assert "skipped" in prj
            assert sorted(prj["skipped"]) == [0, 1]
    finally:
        app.dependency_overrides.clear()
