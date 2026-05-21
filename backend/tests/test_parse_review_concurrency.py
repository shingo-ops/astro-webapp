"""Sprint 6 (F6) parse review 楽観ロック / 同時承認テスト (実 Postgres)。

AC6.5: 同一 inbound を別 admin が同時に承認 → 後発が 409 Conflict
       version カウンタ mismatch で UPDATE が 0 行 → 409 返却
"""

from __future__ import annotations

import asyncio
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


from tests.test_parse_review_approve import (  # noqa: E402, F401
    _client_with_overrides,
    engine,
    seed_inbound_with_product,
)


async def test_second_approve_with_same_version_returns_409(
    engine, seed_inbound_with_product
):
    """AC6.5: 先発 approve が成功 → 後発が同 version で叩いて 409 を受け取る。

    Note:
      - 真の並行ではなく逐次（1 リクエストが完全に成功した後で 2 つ目を投げる）。
      - これだけで version mismatch は確定的に再現する。
      - 真の race (timing window) は別途 lock_probe テストでカバーされる。
    """
    ctx = seed_inbound_with_product
    inbound_id = ctx["inbound_id"]
    product_ids = ctx["product_ids"]

    client, app = _client_with_overrides(engine)
    try:
        async with client as c:
            base_payload = {
                "version": 0,
                "items": [{"product_id": product_ids[0], "delta_qty": 1}],
                "skipped_indices": [],
                "operator_comment": "first",
            }
            r1 = await c.post(
                f"/api/v1/super-admin/parse-review/{inbound_id}/approve",
                json=base_payload,
            )
            assert r1.status_code == 200, r1.text

            # 同じ version=0 を再送 → 409
            r2 = await c.post(
                f"/api/v1/super-admin/parse-review/{inbound_id}/approve",
                json=base_payload,
            )
            assert r2.status_code == 409, r2.text
            assert "version mismatch" in r2.text or "already approved" in r2.text
    finally:
        app.dependency_overrides.clear()


async def test_concurrent_approve_only_one_wins(engine, seed_inbound_with_product):
    """AC6.5 真の並行: 2 つの approve リクエストを同時投げ、1 つだけ 200 で他は 409。

    実 Postgres で SELECT ... FOR UPDATE + version mismatch UPDATE のロック挙動を
    確認する。同一 version=0 を 2 並行で投げ、片方は 200、もう片方は 409。
    """
    ctx = seed_inbound_with_product
    inbound_id = ctx["inbound_id"]
    product_ids = ctx["product_ids"]

    payload = {
        "version": 0,
        "items": [{"product_id": product_ids[0], "delta_qty": 1}],
        "skipped_indices": [],
        "operator_comment": "concurrent test",
    }

    client, app = _client_with_overrides(engine)
    try:
        async with client as c:
            r1, r2 = await asyncio.gather(
                c.post(
                    f"/api/v1/super-admin/parse-review/{inbound_id}/approve",
                    json=payload,
                ),
                c.post(
                    f"/api/v1/super-admin/parse-review/{inbound_id}/approve",
                    json=payload,
                ),
                return_exceptions=False,
            )
            statuses = sorted([r1.status_code, r2.status_code])
            # 片方 200、もう片方 409
            assert statuses == [200, 409], (
                f"concurrent approve: expected [200, 409] got {statuses}; "
                f"r1={r1.status_code} body1={r1.text[:200]}; "
                f"r2={r2.status_code} body2={r2.text[:200]}"
            )
    finally:
        app.dependency_overrides.clear()
