"""
Phase 1-E F6-S2: meta_inbox.py 各 endpoint の 401/403 統合テスト。

Sprint 2 Generator Known Limitations で持ち越し。

カバー:
- 4 endpoint × 2 (auth missing → 401, perm missing → 403) = 8 ケース
- POST /meta/connect/start (channels.manage)
- GET /meta/connect/callback (channels.manage)
- DELETE /meta/connect/{page_id} (channels.manage)
- GET /meta/channels (channels.view)

設計判断:
- FastAPI 0.115+ の HTTPBearer は credentials missing → 401 を返す
- require_permission は permission missing → 403 を返す
- なので「auth missing」は 401、「perm missing」は 403 になる。
- 既存 test_meta_oauth_endpoints.py は permission 全付与 + user override で
  正常系を扱うため、本ファイルは permission/user override せずに 403 を確認する。
"""

from __future__ import annotations

import os
from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

# DATABASE_URL を SQLite に必ず差し替え
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.auth.dependencies import (
    get_current_tenant,
    get_current_user,
)
from app.database import get_db
from app.routers import meta_inbox


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def app_no_auth():
    """auth dependency を override しない FastAPI app。

    リクエスト時に Authorization header が無いため、HTTPBearer が
    HTTPException(401, "Not authenticated") を返す（FastAPI 0.115+ の挙動）。
    """
    app = FastAPI()
    app.include_router(meta_inbox.router, prefix="/api/v1")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def app_no_perm(monkeypatch):
    """user / tenant は override するが permission を空にする app。

    require_permission のチェックで HTTPException(403, "Permission ...") が返る。
    """
    from unittest.mock import MagicMock

    def _user():
        u = MagicMock()
        u.id = 1
        u.tenant_id = 999
        u.email = "noperm@example.com"
        return u

    app = FastAPI()
    app.include_router(meta_inbox.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_current_tenant] = lambda: 999

    # DB session も最小モック
    async def _db():
        yield None  # 各テストは permission チェックで弾かれる、DB に到達しない

    app.dependency_overrides[get_db] = _db

    transport = ASGITransport(app=app)
    with ExitStack() as stack:
        # load_user_permissions が空 set を返す → 全 permission チェックで 403
        stack.enter_context(patch(
            "app.auth.dependencies.load_user_permissions",
            new=AsyncMock(return_value=set()),
        ))
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 401/403 テスト（4 endpoint × 2 シナリオ = 8 ケース）
# ---------------------------------------------------------------------------


# POST /api/v1/meta/connect/start (channels.manage)
@pytest.mark.asyncio
async def test_connect_start_no_auth_returns_401(app_no_auth):
    res = await app_no_auth.post("/api/v1/meta/connect/start")
    # FastAPI 0.115+ は認証ヘッダー未送信時に 401 を返す（旧 403 から変更）
    assert res.status_code == 401, f"expected 401 (no auth), got {res.status_code}"
    assert "authenticated" in res.json().get("detail", "").lower() or \
           res.json().get("detail") == "Not authenticated"


@pytest.mark.asyncio
async def test_connect_start_no_perm_returns_403(app_no_perm):
    res = await app_no_perm.post("/api/v1/meta/connect/start")
    assert res.status_code == 403, f"expected 403 (no perm), got {res.status_code}"


# GET /api/v1/meta/connect/callback (channels.manage)
@pytest.mark.asyncio
async def test_connect_callback_no_auth_returns_401(app_no_auth):
    res = await app_no_auth.get("/api/v1/meta/connect/callback?code=x&state=y")
    assert res.status_code == 401, f"expected 401 (no auth), got {res.status_code}"


@pytest.mark.asyncio
async def test_connect_callback_no_perm_returns_403(app_no_perm):
    res = await app_no_perm.get("/api/v1/meta/connect/callback?code=x&state=y")
    assert res.status_code == 403, f"expected 403 (no perm), got {res.status_code}"


# DELETE /api/v1/meta/connect/{page_id} (channels.manage)
@pytest.mark.asyncio
async def test_connect_delete_no_auth_returns_401(app_no_auth):
    res = await app_no_auth.delete("/api/v1/meta/connect/123456")
    assert res.status_code == 401, f"expected 401 (no auth), got {res.status_code}"


@pytest.mark.asyncio
async def test_connect_delete_no_perm_returns_403(app_no_perm):
    res = await app_no_perm.delete("/api/v1/meta/connect/123456")
    assert res.status_code == 403, f"expected 403 (no perm), got {res.status_code}"


# GET /api/v1/meta/channels (channels.view)
@pytest.mark.asyncio
async def test_channels_list_no_auth_returns_401(app_no_auth):
    res = await app_no_auth.get("/api/v1/meta/channels")
    assert res.status_code == 401, f"expected 401 (no auth), got {res.status_code}"


@pytest.mark.asyncio
async def test_channels_list_no_perm_returns_403(app_no_perm):
    res = await app_no_perm.get("/api/v1/meta/channels")
    assert res.status_code == 403, f"expected 403 (no perm), got {res.status_code}"


# ---------------------------------------------------------------------------
# Sanity: ANY permission を持つ app では同じ endpoint が 403 を返さない
# (test_meta_oauth_endpoints.py で正常系をテスト済のため、ここでは省略)
# ---------------------------------------------------------------------------
