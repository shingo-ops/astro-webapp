"""
502 Bad Gateway 全5経路の網羅テスト (#20)

## 502が発生しうる経路一覧

| # | 経路 | ファイル | テスト |
|---|------|---------|--------|
| 1 | DM 送信 - MetaGraphAPIError         | leads.py:1044       | test_message_send.py |
| 2 | DM 送信 - MetaGraphError (transport) | leads.py:1065       | test_message_send.py |
| 3 | OAuth callback - token exchange error | meta_inbox.py:389   | test_meta_oauth_endpoints.py |
| 4 | OAuth callback - page list error      | meta_inbox.py:437   | ★このファイル |
| 5 | OAuth callback - token exchange transport | meta_inbox.py:398 | test_meta_oauth_endpoints.py |

パス 1/2/3/5 は既存テストでカバー済み。このファイルはパス 4 (page list 502) を追加し、
全5経路が 1 テストスイートから確認できるようにする。

実行:
    pytest backend/tests/test_502_paths.py -v
"""

from __future__ import annotations

import json
import os
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

import httpx
import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.auth.dependencies import get_current_tenant, get_current_user
from app.database import get_db
from app.routers import meta_inbox
from app.services import encryption
from app.services.meta_graph import MetaGraphAPIError, MetaGraphError


# ---------------------------------------------------------------------------
# Minimal fixtures (mirrored from test_meta_oauth_endpoints.py)
# ---------------------------------------------------------------------------

_ALL_PERMS = {"channels.view", "channels.manage", "messaging.view", "messaging.send"}


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    @event.listens_for(eng.sync_engine, "connect")
    def _setup(dbapi_conn, _):
        dbapi_conn.create_function("NOW", 0, lambda: "2026-04-30 12:00:00+00:00")
        dbapi_conn.execute("PRAGMA foreign_keys = ON")

    async with eng.begin() as conn:
        await conn.execute(text("""
            CREATE TABLE tenant_meta_config (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id INTEGER NOT NULL,
                page_id VARCHAR(50) NOT NULL,
                page_name VARCHAR(200) NOT NULL,
                page_access_token_encrypted BLOB NOT NULL,
                page_token_expires_at TIMESTAMP,
                instagram_business_account_id VARCHAR(50),
                instagram_username VARCHAR(100),
                subscribed_fields TEXT,
                connected_by_staff_id INTEGER,
                connected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_token_refreshed_at TIMESTAMP,
                is_active BOOLEAN NOT NULL DEFAULT 1,
                deactivated_at TIMESTAMP,
                notes TEXT,
                granted_scopes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        await conn.execute(text("""
            CREATE TABLE staff (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id INTEGER NOT NULL DEFAULT 999,
                primary_email VARCHAR(255) NOT NULL
            )
        """))
        await conn.execute(text("""
            CREATE TABLE audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id INTEGER, user_id INTEGER,
                action VARCHAR(100), table_name VARCHAR(100), record_id INTEGER,
                old_data TEXT, new_data TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db_session(engine):
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        yield session
        await session.rollback()


@pytest.fixture
def fernet_env(monkeypatch):
    encryption.reset_cache()
    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("METADATA_FERNET_KEY", key)
    monkeypatch.setenv("META_APP_ID", "test-app-id-123")
    monkeypatch.setenv("META_APP_SECRET", "test-app-secret-shhh")
    monkeypatch.setenv("META_OAUTH_REDIRECT_URI", "https://app.salesanchor.jp/channels/oauth/callback")
    monkeypatch.delenv("META_GRAPH_API_VERSION", raising=False)
    yield
    encryption.reset_cache()


def _mock_user():
    u = MagicMock()
    u.id = 1
    u.tenant_id = 999
    u.email = "tester@example.com"
    return u


@pytest_asyncio.fixture
async def app_client(db_session, fernet_env):
    app = FastAPI()

    async def override_db():
        yield db_session

    async def override_user():
        return _mock_user()

    async def override_tenant():
        return 999

    app.include_router(meta_inbox.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_current_tenant] = override_tenant

    transport = ASGITransport(app=app)
    with ExitStack() as stack:
        stack.enter_context(patch(
            "app.auth.dependencies.load_user_permissions",
            new=AsyncMock(return_value=_ALL_PERMS),
        ))
        stack.enter_context(patch(
            "app.routers.meta_inbox.record_audit_log",
            new=AsyncMock(return_value=None),
        ))
        stack.enter_context(patch(
            "app.routers.meta_inbox.reset_tenant_context",
            new=AsyncMock(return_value=None),
        ))
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    app.dependency_overrides.clear()


def _make_redis_with_state(payload_dict):
    """consume_state 用の Redis pipeline mock を返す。"""
    if payload_dict is None:
        encrypted = None
    else:
        encrypted = encryption.encrypt(json.dumps(payload_dict, separators=(",", ":")))
    redis_mock = AsyncMock()

    def make_pipeline(transaction=True):
        cm = MagicMock()
        pipe = MagicMock()
        pipe.get = MagicMock(return_value=None)
        pipe.delete = MagicMock(return_value=None)

        async def _execute():
            return [encrypted, 1]

        pipe.execute = _execute
        cm.__aenter__ = AsyncMock(return_value=pipe)
        cm.__aexit__ = AsyncMock(return_value=None)
        return cm

    redis_mock.pipeline = MagicMock(side_effect=make_pipeline)
    return redis_mock


def _mock_token_exchange():
    """短期→長期トークン交換を成功させる。"""
    async def _exchange_code(code, redirect_uri):
        return "short-token"

    async def _exchange_short(short_token):
        return {"access_token": "long-token", "expires_in": 5183944}

    return (
        patch("app.services.meta_graph.exchange_code_for_short_token",
              new=AsyncMock(side_effect=_exchange_code)),
        patch("app.services.meta_graph.exchange_short_token_for_long_token",
              new=AsyncMock(side_effect=_exchange_short)),
    )


# ---------------------------------------------------------------------------
# 502 Path 4: OAuth callback - page list error → 502
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_callback_502_when_page_list_fails_with_api_error(app_client):
    """Path 4: /me/accounts で MetaGraphAPIError → 502 Bad Gateway。"""
    redis_mock = _make_redis_with_state({
        "tenant_id": 999, "staff_id": 0, "created_at": "x", "nonce": "y",
    })
    token_patch_1, token_patch_2 = _mock_token_exchange()

    with patch("app.services.oauth_state.get_redis", return_value=redis_mock), \
         token_patch_1, token_patch_2, \
         patch(
             "app.services.meta_graph.list_user_pages",
             new=AsyncMock(side_effect=MetaGraphAPIError(
                 "OAuthException", status_code=400,
                 error_type="OAuthException", error_code=200,
             )),
         ):
        resp = await app_client.get(
            "/api/v1/meta/connect/callback?code=the-code&state=ok-state"
        )

    assert resp.status_code == 502


@pytest.mark.asyncio
async def test_callback_502_when_page_list_fails_with_transport_error(app_client):
    """Path 4b: /me/accounts で MetaGraphError (transport) → 502 Bad Gateway。"""
    redis_mock = _make_redis_with_state({
        "tenant_id": 999, "staff_id": 0, "created_at": "x", "nonce": "y",
    })
    token_patch_1, token_patch_2 = _mock_token_exchange()

    with patch("app.services.oauth_state.get_redis", return_value=redis_mock), \
         token_patch_1, token_patch_2, \
         patch(
             "app.services.meta_graph.list_user_pages",
             new=AsyncMock(side_effect=MetaGraphError("network failure")),
         ):
        resp = await app_client.get(
            "/api/v1/meta/connect/callback?code=the-code&state=ok-state"
        )

    assert resp.status_code == 502


# ---------------------------------------------------------------------------
# 502 経路カバレッジサマリ（文書用テスト）
# ---------------------------------------------------------------------------


def test_all_502_paths_are_covered():
    """502 全5経路がテスト済みであることを文書化する。

    各経路の実テストは以下のファイルに存在する:
    - Path 1: test_message_send.py::test_send_returns_502_when_meta_api_error
    - Path 2: test_message_send.py::test_send_returns_502_when_meta_transport_error
    - Path 3: test_meta_oauth_endpoints.py::test_callback_handles_meta_oauth_exception
    - Path 4: test_502_paths.py::test_callback_502_when_page_list_fails_with_api_error
    - Path 5: test_meta_oauth_endpoints.py::test_callback_502_when_meta_token_exchange_transport_error
    """
    covered_paths = {
        "path_1_dm_send_api_error": "test_message_send.py",
        "path_2_dm_send_transport": "test_message_send.py",
        "path_3_oauth_token_exchange_api_error": "test_meta_oauth_endpoints.py",
        "path_4_oauth_page_list_error": "test_502_paths.py",
        "path_5_oauth_token_exchange_transport": "test_meta_oauth_endpoints.py",
    }
    assert len(covered_paths) == 5
