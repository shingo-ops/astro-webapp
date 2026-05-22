"""Sprint 6 (F6) parse review API の RBAC テスト。

AC6.8: 一般ユーザー / テナント admin (is_super_admin=false) が
       /api/v1/super-admin/parse-review/* に直接アクセスすると 403。
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


async def test_non_super_admin_gets_403_on_detail():
    """is_super_admin=false の user は detail endpoint で 403。"""
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    from app.auth.dependencies import get_current_user
    from app.models import User

    async def fake_non_super_admin() -> User:
        u = User()
        u.id = 100
        u.is_super_admin = False
        u.role = "admin"
        u.tenant_id = 6
        return u

    app.dependency_overrides[get_current_user] = fake_non_super_admin
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.get("/api/v1/super-admin/parse-review/9999")
            assert r.status_code == 403, r.text

            r2 = await client.post(
                "/api/v1/super-admin/parse-review/9999/approve",
                json={"version": 0, "items": [], "skipped_indices": []},
            )
            assert r2.status_code == 403, r2.text

            r3 = await client.post(
                "/api/v1/super-admin/parse-review/9999/reject",
                json={"version": 0, "exclude_reason": "x"},
            )
            assert r3.status_code == 403, r3.text
    finally:
        app.dependency_overrides.pop(get_current_user, None)
