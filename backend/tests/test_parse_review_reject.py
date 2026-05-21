"""Sprint 6 (F6) parse review reject エンドポイントの E2E (実 Postgres)。

AC6.4: reject 操作で parse_status='rejected' + exclude_reason 必須 (空白は 400)、
       products は無変化
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


# fixtures は conftest 的に再エクスポート。collection 時に PG 接続しないよう、
# `import` は関数内に閉じこめてもよいが pytest fixture 解決は module top-level の
# 同名関数を要求するため、ここで lazy import + 再公開する。
def _import_shared():
    """Helper: PG が無い環境でも collection を壊さないよう関数内 import。"""
    from tests.test_parse_review_approve import (
        _client_with_overrides,
        engine as eng_fixture,
        seed_inbound_with_product as seed_fixture,
    )

    return _client_with_overrides, eng_fixture, seed_fixture


# pytest fixture として shared な engine / seed を再公開。
# 直接 import すると collection 時に DB 接続を走らせる関数があるが、
# fixture 自体は async / pytest が呼ぶまで遅延される。
from tests.test_parse_review_approve import (  # noqa: E402
    _client_with_overrides,
    engine,  # noqa: F401  (re-export as fixture)
    seed_inbound_with_product,  # noqa: F401  (re-export as fixture)
)


async def test_reject_sets_rejected_status_and_exclude_reason(
    engine, seed_inbound_with_product
):
    """AC6.4: reject 経路で parse_status / exclude_reason 設定、products 不変。"""
    from sqlalchemy import text

    ctx = seed_inbound_with_product
    inbound_id = ctx["inbound_id"]
    product_ids = ctx["product_ids"]

    client, app = _client_with_overrides(engine, super_admin_id=9002)
    try:
        async with client as c:
            payload = {"version": 0, "exclude_reason": "重複受信のため差戻し"}
            r = await c.post(
                f"/api/v1/super-admin/parse-review/{inbound_id}/reject",
                json=payload,
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["parse_status"] == "rejected"
            assert body["version"] == 1
            assert body["exclude_reason"] == "重複受信のため差戻し"

        async with engine.connect() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            "SELECT parse_status, exclude_reason, operator_id, version "
                            "FROM public.discord_inbound_messages WHERE id = :id"
                        ),
                        {"id": inbound_id},
                    )
                )
                .mappings()
                .first()
            )
            assert row["parse_status"] == "rejected"
            assert row["exclude_reason"] == "重複受信のため差戻し"
            assert row["operator_id"] == 9002
            assert row["version"] == 1

            # products 不変
            for pid in product_ids:
                stock = (
                    await conn.execute(
                        text(
                            "SELECT stock_quantity FROM public.products WHERE id = :pid"
                        ),
                        {"pid": pid},
                    )
                ).scalar_one()
                assert stock == 0, f"reject 後に product {pid} が変動した"

            # inventory_movements も 0 件
            mov_count = (
                await conn.execute(
                    text(
                        "SELECT COUNT(*) FROM public.inventory_movements WHERE source_id = :iid"
                    ),
                    {"iid": inbound_id},
                )
            ).scalar_one()
            assert mov_count == 0
    finally:
        app.dependency_overrides.clear()


async def test_reject_requires_exclude_reason_blank_400(
    engine, seed_inbound_with_product
):
    """AC6.4: exclude_reason が空白のみ → 400。"""
    ctx = seed_inbound_with_product
    inbound_id = ctx["inbound_id"]

    client, app = _client_with_overrides(engine)
    try:
        async with client as c:
            # 完全空文字 → Pydantic min_length=1 で 422
            r = await c.post(
                f"/api/v1/super-admin/parse-review/{inbound_id}/reject",
                json={"version": 0, "exclude_reason": ""},
            )
            assert r.status_code in (400, 422), r.text

            # 空白のみ → 400 (アプリ層 strip 検証)
            r2 = await c.post(
                f"/api/v1/super-admin/parse-review/{inbound_id}/reject",
                json={"version": 0, "exclude_reason": "   "},
            )
            assert r2.status_code == 400, r2.text
    finally:
        app.dependency_overrides.clear()
