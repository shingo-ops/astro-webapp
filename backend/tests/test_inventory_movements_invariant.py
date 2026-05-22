"""Sprint 6 (F6) AC6.6 不変条件テスト (実 Postgres)。

AC6.6: SUM(inventory_movements.delta_qty WHERE product_id=X) ==
       public.products.stock_quantity (X) が常に成立する。

検証戦略:
  - 開発フェーズの開始点: products.stock_quantity=0、movements 0 件 → 両方 0 で OK
  - 2 件の inbound を連続 approve、それぞれ複数の product に delta_qty を振る
  - 各 approve 後に SUM vs stock を assert
  - reject は無効果（products 不変）を assert
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


async def _check_invariant(engine, product_ids: list[int]) -> None:
    """AC6.6: 全 product 毎に SUM(delta_qty) == stock_quantity を assert。"""
    from sqlalchemy import text

    async with engine.connect() as conn:
        for pid in product_ids:
            stock = (
                await conn.execute(
                    text(
                        "SELECT COALESCE(stock_quantity, 0) FROM public.products WHERE id = :pid"
                    ),
                    {"pid": pid},
                )
            ).scalar_one()
            dsum = (
                await conn.execute(
                    text(
                        "SELECT COALESCE(SUM(delta_qty), 0) "
                        "FROM public.inventory_movements WHERE product_id = :pid"
                    ),
                    {"pid": pid},
                )
            ).scalar_one()
            assert stock == dsum, (
                f"AC6.6 不変条件違反 product_id={pid}: "
                f"stock_quantity={stock} SUM(delta_qty)={dsum}"
            )


async def test_invariant_holds_across_multiple_approves(engine):
    """連続 approve / reject 後も SUM(delta_qty) == stock_quantity を保つ。"""
    from sqlalchemy import text

    from tests.test_parse_review_approve import _client_with_overrides

    tag = uuid.uuid4().hex[:8]
    product_ids: list[int] = []
    inbound_ids: list[int] = []
    sup_id: int | None = None

    async with engine.begin() as conn:
        # 事前 migration / column チェック
        exists_ver = (
            await conn.execute(
                text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_schema='public' AND table_name='discord_inbound_messages' "
                    "AND column_name='version'"
                )
            )
        ).scalar_one_or_none()
        if not exists_ver:
            pytest.skip("migration 067 未適用")

        # Sprint 9 / F9 v1.2: AC6.6 不変条件 (SUM=stock) は Phase B 想定。
        # Phase A だと stock_quantity 更新 skip で破綻するので明示的に B。
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
                {"n": f"inv_sup_{tag}"},
            )
        ).scalar_one()

        # 3 products at stock=0
        for i in range(3):
            pid = (
                await conn.execute(
                    text(
                        "INSERT INTO public.products (tenant_id, product_code, name, stock_quantity) "
                        "VALUES (6, :code, :name, 0) RETURNING id"
                    ),
                    {"code": f"INV-{tag}-{i}", "name": f"INV-{tag}-{i}"},
                )
            ).scalar_one()
            product_ids.append(int(pid))

        # 3 inbound seed
        for i in range(3):
            mid = f"inv_msg_{tag}_{i}"
            iid = (
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
                        "mid": mid,
                        "ch": f"ch_{tag}",
                        "sid": sup_id,
                        "raw": "inv",
                        "prj": json.dumps({"items": []}),
                    },
                )
            ).scalar_one()
            inbound_ids.append(int(iid))

    try:
        # 不変条件: 開始時点 0 == 0
        await _check_invariant(engine, product_ids)

        client, app = _client_with_overrides(engine, super_admin_id=9050)
        try:
            async with client as c:
                # 1 件目: pid0 += 10, pid1 += 5
                r = await c.post(
                    f"/api/v1/super-admin/parse-review/{inbound_ids[0]}/approve",
                    json={
                        "version": 0,
                        "items": [
                            {"product_id": product_ids[0], "delta_qty": 10},
                            {"product_id": product_ids[1], "delta_qty": 5},
                        ],
                        "skipped_indices": [],
                        "operator_comment": "round 1",
                    },
                )
                assert r.status_code == 200, r.text
                await _check_invariant(engine, product_ids)

                # 2 件目: pid0 -= 3 (出庫), pid2 += 7
                r = await c.post(
                    f"/api/v1/super-admin/parse-review/{inbound_ids[1]}/approve",
                    json={
                        "version": 0,
                        "items": [
                            {"product_id": product_ids[0], "delta_qty": -3},
                            {"product_id": product_ids[2], "delta_qty": 7},
                        ],
                        "skipped_indices": [],
                        "operator_comment": "round 2",
                    },
                )
                assert r.status_code == 200, r.text
                await _check_invariant(engine, product_ids)

                # 3 件目: reject (products 不変)
                r = await c.post(
                    f"/api/v1/super-admin/parse-review/{inbound_ids[2]}/reject",
                    json={"version": 0, "exclude_reason": "テスト差戻し"},
                )
                assert r.status_code == 200, r.text
                await _check_invariant(engine, product_ids)

                # 最終的に: pid0=10-3=7, pid1=5, pid2=7
                async with engine.connect() as conn:
                    stocks = {}
                    for pid in product_ids:
                        s = (
                            await conn.execute(
                                text(
                                    "SELECT stock_quantity FROM public.products WHERE id = :pid"
                                ),
                                {"pid": pid},
                            )
                        ).scalar_one()
                        stocks[pid] = int(s)
                assert stocks[product_ids[0]] == 7
                assert stocks[product_ids[1]] == 5
                assert stocks[product_ids[2]] == 7
        finally:
            app.dependency_overrides.clear()
    finally:
        # cleanup
        async with engine.begin() as conn:
            for iid in inbound_ids:
                await conn.execute(
                    text(
                        "DELETE FROM public.inventory_movements WHERE source_id = :iid"
                    ),
                    {"iid": iid},
                )
                await conn.execute(
                    text("DELETE FROM public.discord_inbound_messages WHERE id = :iid"),
                    {"iid": iid},
                )
            for pid in product_ids:
                await conn.execute(
                    text("DELETE FROM public.products WHERE id = :pid"), {"pid": pid}
                )
            if sup_id is not None:
                await conn.execute(
                    text("DELETE FROM public.suppliers WHERE id = :sid"),
                    {"sid": sup_id},
                )
