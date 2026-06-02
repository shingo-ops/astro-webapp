"""Discord OAuth2 Bot Invite エンドポイント (discord_oauth.py) のテスト

POST /api/v1/discord/oauth/start  — Invite URL 発行（認証必須）
GET  /api/v1/discord/oauth/callback — Discord コールバック（公開）

oauth_state (Redis) と DB upsert はモックし、エンドポイントのルーティング・
パラメータ検証・リダイレクト URL の正しさを検証する。

実行:
    pytest backend/tests/test_discord_oauth.py -v
"""

from __future__ import annotations

import os
from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.auth.dependencies import (
    get_current_tenant,
    get_current_user,
)
from app.database import get_db
from app.models import User


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

_ALL_PERMS = {"channels.view", "channels.manage"}


async def _mock_load_user_permissions(db, tenant_id, user_id):
    return _ALL_PERMS


def _mock_user() -> User:
    user = User()
    user.id = 42
    user.tenant_id = 7
    user.username = "testuser"
    user.email = "test@example.com"
    user.role = "admin"
    user.is_active = True
    return user


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    @event.listens_for(eng.sync_engine, "connect")
    def _setup(dbapi_conn, _):
        dbapi_conn.create_function("NOW", 0, lambda: "2026-06-02 00:00:00+00:00")
        dbapi_conn.execute("PRAGMA foreign_keys = ON")

    @event.listens_for(eng.sync_engine, "before_cursor_execute", retval=True)
    def _rewrite(conn, cursor, statement, parameters, context, executemany):
        if "public.tenant_discord_config" in statement:
            statement = statement.replace(
                "public.tenant_discord_config", "tenant_discord_config"
            )
        return statement, parameters

    async with eng.begin() as conn:
        await conn.execute(
            text("""
            CREATE TABLE IF NOT EXISTS tenant_discord_config (
                tenant_id INTEGER PRIMARY KEY,
                guild_id  VARCHAR(32) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        )

    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db_session(engine):
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def app_client(db_session):
    """discord_oauth ルーターを含む最小 FastAPI アプリでテスト用 AsyncClient を返す。"""
    from app.routers import discord_oauth
    from fastapi import Depends, FastAPI

    app = FastAPI()
    app.include_router(discord_oauth.router, prefix="/api/v1")

    mock_user = _mock_user()

    async def override_get_db():
        yield db_session

    async def override_get_current_user():
        return mock_user

    async def override_get_current_tenant():
        return mock_user.tenant_id

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_current_tenant] = override_get_current_tenant

    transport = ASGITransport(app=app)
    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "app.auth.dependencies.load_user_permissions",
                _mock_load_user_permissions,
            )
        )
        stack.enter_context(
            patch(
                "app.routers.discord_oauth.record_audit_log",
                AsyncMock(return_value=None),
            )
        )
        stack.enter_context(
            patch(
                "app.routers.discord_oauth.reset_tenant_context",
                AsyncMock(return_value=None),
            )
        )
        async with AsyncClient(
            transport=transport, base_url="http://test", follow_redirects=False
        ) as ac:
            yield ac


@pytest_asyncio.fixture
async def unauth_client(db_session):
    """認証 dependency を override しない（未認証テスト用）。"""
    from app.routers import discord_oauth
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(discord_oauth.router, prefix="/api/v1")

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", follow_redirects=False
    ) as ac:
        yield ac


# ---------------------------------------------------------------------------
# POST /api/v1/discord/oauth/start
# ---------------------------------------------------------------------------


class TestDiscordOAuthStart:
    """POST /api/v1/discord/oauth/start のテスト。"""

    @pytest.mark.asyncio
    async def test_start_returns_invite_url_and_state(self, app_client):
        """認証済みユーザーが呼ぶと invite_url と state が返る。"""
        mock_issued = {
            "state": "test-random-state-abc123",
            "ttl_seconds": 600,
            "expires_at": "2026-06-02T00:10:00+00:00",
        }
        with patch(
            "app.routers.discord_oauth.oauth_state.issue_state",
            AsyncMock(return_value=mock_issued),
        ):
            res = await app_client.post("/api/v1/discord/oauth/start")

        assert res.status_code == 200
        body = res.json()
        assert "invite_url" in body
        assert "state" in body
        assert "expires_at" in body
        assert body["state"] == "test-random-state-abc123"
        assert "discord.com/oauth2/authorize" in body["invite_url"]
        assert "state=test-random-state-abc123" in body["invite_url"]

    @pytest.mark.asyncio
    async def test_start_unauthenticated_returns_error(self, unauth_client):
        """未認証だと 401 または 403 が返る。"""
        res = await unauth_client.post("/api/v1/discord/oauth/start")
        assert res.status_code in (401, 403, 422)


# ---------------------------------------------------------------------------
# GET /api/v1/discord/oauth/callback
# ---------------------------------------------------------------------------

_FRONTEND_BASE = "https://app.salesanchor.jp"


class TestDiscordOAuthCallback:
    """GET /api/v1/discord/oauth/callback のテスト。"""

    @pytest.mark.asyncio
    async def test_callback_valid_state_and_guild_id_redirects_connected(
        self, app_client
    ):
        """有効な state と guild_id があると guild_id が保存されて
        app.salesanchor.jp/channels?discord_status=connected にリダイレクトされる。
        """
        mock_payload = {
            "tenant_id": 7,
            "staff_id": 42,
            "created_at": "2026-06-02T00:00:00+00:00",
            "nonce": "abc",
        }
        with patch(
            "app.routers.discord_oauth.oauth_state.consume_state",
            AsyncMock(return_value=mock_payload),
        ):
            res = await app_client.get(
                "/api/v1/discord/oauth/callback",
                params={"state": "valid-state", "guild_id": "123456789"},
            )

        assert res.status_code in (302, 307)
        location = res.headers["location"]
        assert location == f"{_FRONTEND_BASE}/channels?discord_status=connected"
        # _FRONTEND_BASE_URL が空文字でないことの回帰テスト
        assert location.startswith("https://app.salesanchor.jp")

    @pytest.mark.asyncio
    async def test_callback_missing_state_redirects_error(self, app_client):
        """state なしで呼ぶと discord_status=error&reason=missing_state にリダイレクトされる。"""
        res = await app_client.get("/api/v1/discord/oauth/callback")

        assert res.status_code in (302, 307)
        location = res.headers["location"]
        assert "discord_status=error" in location
        assert "reason=missing_state" in location

    @pytest.mark.asyncio
    async def test_callback_invalid_state_redirects_error(self, app_client):
        """無効な state（改ざん・期限切れ）では
        discord_status=error&reason=invalid_state にリダイレクトされる。
        """
        with patch(
            "app.routers.discord_oauth.oauth_state.consume_state",
            AsyncMock(return_value=None),
        ):
            res = await app_client.get(
                "/api/v1/discord/oauth/callback",
                params={"state": "tampered-state", "guild_id": "123456789"},
            )

        assert res.status_code in (302, 307)
        location = res.headers["location"]
        assert "discord_status=error" in location
        assert "reason=invalid_state" in location

    @pytest.mark.asyncio
    async def test_callback_missing_guild_id_redirects_error(self, app_client):
        """guild_id なしで呼ぶと discord_status=error&reason=missing_guild_id にリダイレクトされる。"""
        res = await app_client.get(
            "/api/v1/discord/oauth/callback",
            params={"state": "some-state"},
        )

        assert res.status_code in (302, 307)
        location = res.headers["location"]
        assert "discord_status=error" in location
        assert "reason=missing_guild_id" in location
