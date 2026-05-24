"""
Google Calendar 連携（service + router）の単体テスト。

Redis・Google API は全てモックする。SQLite + httpx で FastAPI をテスト。

カバー範囲:
  - service: issue_state / consume_state（Redis mock）
  - service: get_auth_url（Flow mock）
  - service: exchange_code（Flow mock + state 検証）
  - service: _is_token_expired
  - router: GET /google-calendar/status（未接続）
  - router: GET /google-calendar/connect/start（管理者チェック）
  - router: GET /google-calendar/connect/callback（OAuth callback）
  - router: GET /google-calendar/events（未接続 502）
  - router: POST /google-calendar/events（未接続 502）
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest
from cryptography.fernet import Fernet

# テスト用環境変数を先に設定
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("METADATA_FERNET_KEY", Fernet.generate_key().decode())
os.environ.setdefault("GOOGLE_CALENDAR_CLIENT_ID", "test-client-id.apps.googleusercontent.com")
os.environ.setdefault("GOOGLE_CALENDAR_CLIENT_SECRET", "test-secret")
os.environ.setdefault("GOOGLE_CALENDAR_REDIRECT_URI", "https://api.example.com/callback")


# ---------------------------------------------------------------------------
# service: _is_token_expired
# ---------------------------------------------------------------------------

class TestIsTokenExpired:
    def test_expired_when_none(self):
        from app.services.google_calendar import _is_token_expired
        assert _is_token_expired(None) is True

    def test_expired_when_past(self):
        from app.services.google_calendar import _is_token_expired
        past = datetime.now(timezone.utc) - timedelta(hours=2)
        assert _is_token_expired(past) is True

    def test_not_expired_when_future(self):
        from app.services.google_calendar import _is_token_expired
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        assert _is_token_expired(future) is False

    def test_expired_within_buffer(self):
        """期限まで3分（5分バッファ内）は expired 扱い。"""
        from app.services.google_calendar import _is_token_expired
        soon = datetime.now(timezone.utc) + timedelta(minutes=3)
        assert _is_token_expired(soon) is True


# ---------------------------------------------------------------------------
# service: issue_state / consume_state
# ---------------------------------------------------------------------------

class TestOAuthState:
    @pytest.fixture
    def mock_redis(self):
        r = AsyncMock()
        pipeline_mock = MagicMock()  # pipeline コマンドは awaitable でない（キューイング）
        pipeline_mock.__aenter__ = AsyncMock(return_value=pipeline_mock)
        pipeline_mock.__aexit__ = AsyncMock(return_value=None)
        pipeline_mock.get = MagicMock(return_value=None)
        pipeline_mock.delete = MagicMock(return_value=None)
        pipeline_mock.execute = AsyncMock(return_value=[None, 0])
        r.pipeline = MagicMock(return_value=pipeline_mock)
        with patch("app.services.google_calendar.get_redis", return_value=r):
            yield r, pipeline_mock

    @pytest.mark.asyncio
    async def test_issue_state_returns_state_string(self, mock_redis):
        from app.services.google_calendar import issue_state
        r, _ = mock_redis
        state = await issue_state(tenant_id=1, user_id=42)
        assert isinstance(state, str)
        assert len(state) > 20  # urlsafe random token
        r.setex.assert_called_once()

    @pytest.mark.asyncio
    async def test_issue_state_no_redis_raises(self):
        from app.services.google_calendar import issue_state
        with patch("app.services.google_calendar.get_redis", return_value=None):
            with pytest.raises(RuntimeError, match="Redis"):
                await issue_state(tenant_id=1, user_id=1)

    @pytest.mark.asyncio
    async def test_consume_state_not_found_returns_none(self, mock_redis):
        from app.services.google_calendar import consume_state
        # pipeline returns None (key not found)
        state = await consume_state("nonexistent-state")
        assert state is None

    @pytest.mark.asyncio
    async def test_consume_state_empty_string_returns_none(self, mock_redis):
        from app.services.google_calendar import consume_state
        result = await consume_state("")
        assert result is None

    @pytest.mark.asyncio
    async def test_consume_state_no_redis_raises(self):
        from app.services.google_calendar import consume_state
        with patch("app.services.google_calendar.get_redis", return_value=None):
            with pytest.raises(RuntimeError, match="Redis"):
                await consume_state("some-state")

    @pytest.mark.asyncio
    async def test_consume_state_found_returns_payload(self):
        """正常な state が Redis に保存されていれば payload を返す。"""
        from app.services.google_calendar import consume_state
        from app.services import encryption

        payload = {"tenant_id": 1, "user_id": 42, "nonce": "abc"}
        encrypted = encryption.encrypt(json.dumps(payload))

        r = AsyncMock()
        pipeline_mock = AsyncMock()
        pipeline_mock.__aenter__ = AsyncMock(return_value=pipeline_mock)
        pipeline_mock.__aexit__ = AsyncMock(return_value=None)
        pipeline_mock.execute = AsyncMock(return_value=[encrypted, 1])
        r.pipeline = MagicMock(return_value=pipeline_mock)

        with patch("app.services.google_calendar.get_redis", return_value=r):
            result = await consume_state("valid-state-token")

        assert result is not None
        assert result["tenant_id"] == 1
        assert result["user_id"] == 42


# ---------------------------------------------------------------------------
# service: get_auth_url
# ---------------------------------------------------------------------------

class TestGetAuthUrl:
    @pytest.mark.asyncio
    async def test_returns_string_url(self):
        from app.services.google_calendar import get_auth_url

        mock_flow = MagicMock()
        mock_flow.authorization_url = MagicMock(return_value=("https://accounts.google.com/o/oauth2/auth?state=x", "x"))

        r = AsyncMock()
        r.setex = AsyncMock(return_value=True)

        with patch("app.services.google_calendar.get_redis", return_value=r):
            with patch("google_auth_oauthlib.flow.Flow") as MockFlow:
                MockFlow.from_client_config.return_value = mock_flow
                url = await get_auth_url(tenant_id=1, user_id=2)

        assert url.startswith("https://accounts.google.com")

    @pytest.mark.asyncio
    async def test_raises_when_env_missing(self):
        """環境変数未設定時は RuntimeError を出す（startup で検知）。"""
        from app.services import google_calendar as svc

        with patch.dict(os.environ, {"GOOGLE_CALENDAR_CLIENT_ID": ""}):
            with pytest.raises(RuntimeError, match="GOOGLE_CALENDAR_CLIENT_ID"):
                svc._get_client_id()


# ---------------------------------------------------------------------------
# service: exchange_code
# ---------------------------------------------------------------------------

class TestExchangeCode:
    @pytest.mark.asyncio
    async def test_invalid_state_raises_value_error(self):
        from app.services.google_calendar import exchange_code

        with patch("app.services.google_calendar.consume_state", AsyncMock(return_value=None)):
            with pytest.raises(ValueError, match="無効"):
                await exchange_code("auth-code", "bad-state")

    @pytest.mark.asyncio
    async def test_no_refresh_token_raises(self):
        from app.services.google_calendar import exchange_code

        payload = {"tenant_id": 1, "user_id": 2, "nonce": "x"}
        mock_creds = MagicMock()
        mock_creds.token = "access-token"
        mock_creds.refresh_token = None  # refresh_token が取れなかった
        mock_creds.expiry = None

        mock_flow = MagicMock()
        mock_flow.credentials = mock_creds
        mock_flow.fetch_token = MagicMock()

        with patch("app.services.google_calendar.consume_state", AsyncMock(return_value=payload)):
            with patch("google_auth_oauthlib.flow.Flow") as MockFlow:
                MockFlow.from_client_config.return_value = mock_flow
                with pytest.raises(RuntimeError, match="refresh_token"):
                    await exchange_code("auth-code", "valid-state")

    @pytest.mark.asyncio
    async def test_successful_exchange(self):
        from app.services.google_calendar import exchange_code
        from datetime import datetime, timezone

        payload = {"tenant_id": 5, "user_id": 10, "nonce": "y"}
        expiry = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        mock_creds = MagicMock()
        mock_creds.token = "access-abc"
        mock_creds.refresh_token = "refresh-xyz"
        mock_creds.expiry = expiry

        mock_flow = MagicMock()
        mock_flow.credentials = mock_creds
        mock_flow.fetch_token = MagicMock()

        with patch("app.services.google_calendar.consume_state", AsyncMock(return_value=payload)):
            with patch("google_auth_oauthlib.flow.Flow") as MockFlow:
                MockFlow.from_client_config.return_value = mock_flow
                result = await exchange_code("auth-code", "valid-state")

        assert result["tenant_id"] == 5
        assert result["user_id"] == 10
        assert result["access_token"] == "access-abc"
        assert result["refresh_token"] == "refresh-xyz"
        assert result["expiry"] == expiry


# ---------------------------------------------------------------------------
# router: HTTP エンドポイントテスト（FastAPI TestClient 代わりに単体で検証）
# ---------------------------------------------------------------------------

class TestRouterStatus:
    """GET /google-calendar/status の単体テスト。"""

    @pytest.mark.asyncio
    async def test_status_not_connected(self):
        """DB に行がない場合 connected=False を返す。"""
        from app.routers.google_calendar import connection_status

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.first.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await connection_status(tenant_id=1, db=mock_db)
        assert result["connected"] is False

    @pytest.mark.asyncio
    async def test_status_connected(self):
        """DB に行がある場合 connected=True を返す。"""
        from app.routers.google_calendar import connection_status

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.first.return_value = ("primary", datetime(2026, 1, 1, tzinfo=timezone.utc))
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await connection_status(tenant_id=1, db=mock_db)
        assert result["connected"] is True
        assert result["calendar_id"] == "primary"


class TestRouterConnectStart:
    """GET /google-calendar/connect/start の管理者チェックテスト。"""

    @pytest.mark.asyncio
    async def test_non_admin_raises_403(self):
        from app.routers.google_calendar import connect_start, _require_admin
        from app.models import User
        from fastapi import HTTPException

        user = MagicMock(spec=User)
        user.role = "staff"

        with pytest.raises(HTTPException) as exc_info:
            _require_admin(user)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_passes_check(self):
        from app.routers.google_calendar import _require_admin
        from app.models import User

        user = MagicMock(spec=User)
        user.role = "admin"

        # admin は例外なし
        _require_admin(user)


class TestRouterEvents:
    """イベント取得エンドポイントのテスト。"""

    @pytest.mark.asyncio
    async def test_list_events_db_error_502(self):
        """Google Calendar が接続されていない場合 502 を返す。"""
        from app.routers.google_calendar import list_events
        from fastapi import HTTPException

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.first.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(HTTPException) as exc_info:
            await list_events(
                start="2026-01-01T00:00:00Z",
                end="2026-01-31T23:59:59Z",
                tenant_id=1,
                db=mock_db,
            )
        assert exc_info.value.status_code == 502


class TestRouterCreateEvent:
    """イベント作成エンドポイントのテスト。"""

    @pytest.mark.asyncio
    async def test_create_event_not_connected_502(self):
        from app.routers.google_calendar import create_event, EventBody
        from fastapi import HTTPException

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.first.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        body = EventBody(
            summary="テスト",
            start={"dateTime": "2026-01-01T10:00:00", "timeZone": "Asia/Tokyo"},
            end={"dateTime": "2026-01-01T11:00:00", "timeZone": "Asia/Tokyo"},
        )

        with pytest.raises(HTTPException) as exc_info:
            await create_event(body=body, tenant_id=1, db=mock_db)
        assert exc_info.value.status_code == 502


class TestRouterCallback:
    """OAuth callback のテスト（正常 + state エラー）。"""

    @pytest.mark.asyncio
    async def test_callback_invalid_state_redirects(self):
        from app.routers.google_calendar import connect_callback
        from fastapi.responses import RedirectResponse

        mock_db = AsyncMock()

        with patch("app.routers.google_calendar.cal_svc.exchange_code",
                   AsyncMock(side_effect=ValueError("invalid state"))):
            response = await connect_callback(code="auth-code", state="bad-state", db=mock_db)

        assert isinstance(response, RedirectResponse)
        assert "connected=false" in str(response.headers.get("location", ""))

    @pytest.mark.asyncio
    async def test_callback_runtime_error_redirects(self):
        from app.routers.google_calendar import connect_callback
        from fastapi.responses import RedirectResponse

        mock_db = AsyncMock()

        with patch("app.routers.google_calendar.cal_svc.exchange_code",
                   AsyncMock(side_effect=RuntimeError("token exchange failed"))):
            response = await connect_callback(code="auth-code", state="valid", db=mock_db)

        assert isinstance(response, RedirectResponse)
        assert "connected=false" in str(response.headers.get("location", ""))


class TestRouterDisconnect:
    """接続解除エンドポイントのテスト。"""

    @pytest.mark.asyncio
    async def test_disconnect_admin_succeeds(self):
        from app.routers.google_calendar import disconnect
        from app.models import User

        user = MagicMock(spec=User)
        user.role = "admin"
        mock_db = AsyncMock()

        await disconnect(tenant_id=1, user=user, db=mock_db)
        mock_db.execute.assert_called_once()
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_disconnect_non_admin_403(self):
        from app.routers.google_calendar import disconnect
        from app.models import User
        from fastapi import HTTPException

        user = MagicMock(spec=User)
        user.role = "staff"
        mock_db = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await disconnect(tenant_id=1, user=user, db=mock_db)
        assert exc_info.value.status_code == 403
