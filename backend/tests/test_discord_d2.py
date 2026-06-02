"""
Sprint D2 Discord resilience layer / role sync / guild config のテスト。

カバー:
- discord_rest.DiscordAPIError: 基本動作
- discord_rest.discord_api_request: 成功・429・5xx・ネットワークエラー (httpx mock)
- discord_role_sync.sync_lead_discord_role: token未設定・guild未設定・scale unmapped
- discord_guild_config API: GET / PUT (SQLite in-memory)
"""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.auth.dependencies import get_current_tenant, get_current_user
from app.database import get_db
from app.routers import discord_guild_config as dgc_router
from app.services.discord_rest import DiscordAPIError, discord_api_request
from app.services.discord_role_sync import sync_lead_discord_role


# ---------------------------------------------------------------------------
# SQLite in-memory fixtures
# ---------------------------------------------------------------------------

_DDL = """
CREATE TABLE IF NOT EXISTS tenant_discord_config (
    tenant_id INTEGER PRIMARY KEY,
    guild_id  VARCHAR(32) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

TEST_TENANT_ID = 999
TEST_USER_ID = 1


@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    @event.listens_for(engine.sync_engine, "before_cursor_execute", retval=True)
    def _rewrite_sqlite(conn, cursor, statement, parameters, context, executemany):
        statement = statement.replace("public.tenant_discord_config", "tenant_discord_config")
        statement = statement.replace("NOW()", "CURRENT_TIMESTAMP")
        return statement, parameters

    async with engine.begin() as conn:
        await conn.execute(text(_DDL))
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    factory = sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest_asyncio.fixture
async def app_client(db_engine):
    factory = sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    async def override_db():
        async with factory() as s:
            yield s

    def override_tenant():
        return TEST_TENANT_ID

    def override_user():
        u = MagicMock()
        u.id = TEST_USER_ID
        u.role = "admin"
        return u

    # stub reset_tenant_context
    with patch("app.routers.discord_guild_config.reset_tenant_context", new=AsyncMock()):
        with patch("app.routers.discord_guild_config.record_audit_log", new=AsyncMock()):
            app = FastAPI()
            app.include_router(dgc_router.router, prefix="/api/v1")
            app.dependency_overrides[get_db] = override_db
            app.dependency_overrides[get_current_tenant] = override_tenant
            app.dependency_overrides[get_current_user] = override_user

            # stub require_permission
            from app.auth.dependencies import require_permission
            app.dependency_overrides[require_permission("tenant.profile.view")] = lambda: None
            app.dependency_overrides[require_permission("tenant.profile.edit")] = lambda: None

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                yield client


# ---------------------------------------------------------------------------
# discord_rest: DiscordAPIError
# ---------------------------------------------------------------------------

class TestDiscordAPIError:
    def test_message_and_status(self):
        err = DiscordAPIError("テストエラー", status_code=429)
        assert str(err) == "テストエラー"
        assert err.status_code == 429

    def test_default_status_none(self):
        err = DiscordAPIError("失敗")
        assert err.status_code is None


# ---------------------------------------------------------------------------
# discord_rest: discord_api_request
# ---------------------------------------------------------------------------

class TestDiscordApiRequest:
    @pytest.mark.asyncio
    async def test_success_200(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "123"}

        with patch("app.services.discord_rest.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.request.return_value = mock_response
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await discord_api_request(
                method="GET",
                path="/guilds/123/roles",
                bot_token="fake-token",
                expected_statuses=(200,),
            )
        assert result == {"id": "123"}

    @pytest.mark.asyncio
    async def test_success_204_returns_none(self):
        mock_response = MagicMock()
        mock_response.status_code = 204

        with patch("app.services.discord_rest.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.request.return_value = mock_response
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await discord_api_request(
                method="PUT",
                path="/guilds/1/members/2/roles/3",
                bot_token="fake-token",
                expected_statuses=(204,),
            )
        assert result is None

    @pytest.mark.asyncio
    async def test_non_retryable_error_raises(self):
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.text = "Forbidden"

        with patch("app.services.discord_rest.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.request.return_value = mock_response
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            with pytest.raises(DiscordAPIError) as exc_info:
                await discord_api_request(
                    method="GET",
                    path="/guilds/1/roles",
                    bot_token="fake-token",
                )
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_rate_limit_exhaust_raises(self):
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.json.return_value = {"retry_after": 0.001}

        with patch("app.services.discord_rest.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.request.return_value = mock_response
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("app.services.discord_rest.asyncio.sleep", new=AsyncMock()):
                with pytest.raises(DiscordAPIError) as exc_info:
                    await discord_api_request(
                        method="POST",
                        path="/guilds/1/roles",
                        bot_token="fake-token",
                        expected_statuses=(200,),
                    )
        assert exc_info.value.status_code == 429

    @pytest.mark.asyncio
    async def test_5xx_exhaust_raises(self):
        mock_response = MagicMock()
        mock_response.status_code = 503
        mock_response.text = "Service Unavailable"

        with patch("app.services.discord_rest.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.request.return_value = mock_response
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("app.services.discord_rest.asyncio.sleep", new=AsyncMock()):
                with pytest.raises(DiscordAPIError) as exc_info:
                    await discord_api_request(
                        method="GET",
                        path="/guilds/1/roles",
                        bot_token="fake-token",
                    )
        assert exc_info.value.status_code == 503


# ---------------------------------------------------------------------------
# discord_role_sync: sync_lead_discord_role — skip paths
# ---------------------------------------------------------------------------

class TestSyncLeadDiscordRole:
    @pytest.mark.asyncio
    async def test_skip_empty_discord_user_id(self):
        """discord_user_id が空文字列なら何もしない (AC2.6)。"""
        with patch("app.services.discord_role_sync.discord_api_request") as mock_req:
            await sync_lead_discord_role(
                tenant_id=4,
                lead_id=1,
                discord_user_id="",
                new_scale="Large",
            )
        mock_req.assert_not_called()

    @pytest.mark.asyncio
    async def test_skip_unmapped_scale(self):
        """Medium など未マッピングの scale はスキップ。"""
        with patch("app.services.discord_role_sync.discord_api_request") as mock_req:
            await sync_lead_discord_role(
                tenant_id=4,
                lead_id=1,
                discord_user_id="111222333",
                new_scale="Medium",
            )
        mock_req.assert_not_called()

    @pytest.mark.asyncio
    async def test_skip_no_bot_token(self):
        """Bot Token 未設定のとき discord API を叩かず sync_status=failed を記録。"""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DISCORD_BOT_TOKEN_4", None)
            with patch("app.services.discord_role_sync._update_sync_status", new=AsyncMock()) as mock_upd:
                with patch("app.services.discord_role_sync.discord_api_request") as mock_req:
                    await sync_lead_discord_role(
                        tenant_id=4,
                        lead_id=1,
                        discord_user_id="111222333",
                        new_scale="Large",
                    )
            mock_req.assert_not_called()
            mock_upd.assert_called_once_with(4, 1, "failed")

    @pytest.mark.asyncio
    async def test_skip_no_guild_id(self):
        """guild_id 未設定のとき silent skip (ログのみ)。"""
        with patch.dict(os.environ, {"DISCORD_BOT_TOKEN_4": "fake-token"}):
            with patch("app.services.discord_role_sync._get_guild_and_role_names", new=AsyncMock(return_value=(None, "Member", "Partner"))):
                with patch("app.services.discord_role_sync.discord_api_request") as mock_req:
                    await sync_lead_discord_role(
                        tenant_id=4,
                        lead_id=1,
                        discord_user_id="111222333",
                        new_scale="Large",
                    )
            mock_req.assert_not_called()


# ---------------------------------------------------------------------------
# discord_guild_config API: GET / PUT
# ---------------------------------------------------------------------------

class TestDiscordGuildConfigAPI:
    @pytest.mark.asyncio
    async def test_get_returns_null_when_no_config(self, app_client):
        resp = await app_client.get("/api/v1/admin/discord-config")
        assert resp.status_code == 200
        body = resp.json()
        assert body["guild_id"] is None
        assert body["role_member"] == "Member"
        assert body["role_partner"] == "Partner"

    @pytest.mark.asyncio
    async def test_put_saves_guild_id(self, app_client):
        resp = await app_client.put(
            "/api/v1/admin/discord-config",
            json={"guild_id": "1288437029213835356"},
        )
        assert resp.status_code == 200
        assert resp.json()["guild_id"] == "1288437029213835356"

    @pytest.mark.asyncio
    async def test_get_after_put_returns_saved(self, app_client):
        await app_client.put(
            "/api/v1/admin/discord-config",
            json={"guild_id": "1288437029213835356"},
        )
        resp = await app_client.get("/api/v1/admin/discord-config")
        assert resp.status_code == 200
        assert resp.json()["guild_id"] == "1288437029213835356"

    @pytest.mark.asyncio
    async def test_put_invalid_guild_id_rejected(self, app_client):
        resp = await app_client.put(
            "/api/v1/admin/discord-config",
            json={"guild_id": "not-a-number"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_put_too_short_guild_id_rejected(self, app_client):
        resp = await app_client.put(
            "/api/v1/admin/discord-config",
            json={"guild_id": "12345"},
        )
        assert resp.status_code == 422
