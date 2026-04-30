"""
backend/app/routers/meta_inbox.py の統合テスト。

`app.main` を介さず、meta_inbox ルーターのみを抱える最小 FastAPI アプリを構築し、
- 認証 dependency (`get_current_user` / `get_current_tenant`) を override
- `app.auth.dependencies.load_user_permissions` で全権限付与
- DB は SQLite (in-memory) + tenant_meta_config 簡易スキーマ
- Meta Graph API は `app.services.meta_graph` の関数を `unittest.mock.patch` で差し替え
- Redis は `app.services.oauth_state.get_redis` を AsyncMock で差し替え
することで、OAuth エンドポイントのフローを再現性高くテストする。

カバー:
- POST /meta/connect/start: state 発行 + Redis 保存 + auth_url 構造
- GET  /meta/connect/callback: state 不一致 / 期限切れ / 正常系 (Page 接続 + DB 保存) / Meta API エラー
- DELETE /meta/connect/{page_id}: 切断 (404, 200, Meta unsubscribe 失敗時の DB 更新)

実行:
    pytest backend/tests/test_meta_oauth_endpoints.py -v

変更履歴:
    2026-04-30: Phase 1-D Sprint 2 初版
"""

from __future__ import annotations

import json
import os
from contextlib import ExitStack
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

# DATABASE_URL を SQLite に必ず差し替え（モジュール import 順の罠回避）
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

import httpx
import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.auth.dependencies import (
    get_current_tenant,
    get_current_user,
    load_user_permissions,
)
from app.database import get_db
from app.routers import meta_inbox
from app.services import encryption


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


_ALL_PERMS = {"channels.view", "channels.manage", "messaging.view", "messaging.send"}


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    @event.listens_for(eng.sync_engine, "connect")
    def _setup(dbapi_conn, _):
        # NOW() を SQLite で動かす
        dbapi_conn.create_function("NOW", 0, lambda: "2026-04-30 12:00:00+00:00")
        dbapi_conn.execute("PRAGMA foreign_keys = ON")

    async with eng.begin() as conn:
        # tenant_meta_config（SQLite 用に最小限）
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
        # JSONB は SQLite に無いので、tenant.py の text-based JSON で十分
        yield session
        await session.rollback()


@pytest.fixture
def fernet_env(monkeypatch):
    """暗号化鍵 + META 環境変数を仕込む。"""
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
    """meta_inbox ルーターのみ含む FastAPI アプリ + テストクライアント。"""

    # SQLite 用 audit_log SQL は schema 名 INSERT INTO tenant_999.audit_logs ... なので
    # 動かない。audit ロガーを no-op にする。
    async def _noop_audit(*args, **kwargs):
        return None

    # _resolve_staff_id が SQLite で staff テーブル存在前提なので、テーブル作成済（fixture 内）
    # _upsert_tenant_meta_config の RETURNING は SQLite 3.35+ 対応

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
        # require_permission の内部呼び出しもパッチ
        stack.enter_context(patch(
            "app.auth.dependencies.load_user_permissions",
            new=AsyncMock(return_value=_ALL_PERMS),
        ))
        # audit ロガー no-op（SQLite で tenant_NNN.audit_logs を解釈できないため）
        stack.enter_context(patch(
            "app.routers.meta_inbox.record_audit_log",
            new=AsyncMock(return_value=None),
        ))
        # reset_tenant_context は SQLite では既に no-op だが、テスト時は確実に何もしないこと保証
        stack.enter_context(patch(
            "app.routers.meta_inbox.reset_tenant_context",
            new=AsyncMock(return_value=None),
        ))
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helpers: Meta Graph mock
# ---------------------------------------------------------------------------


def _mk_graph_handler(code_to_short: dict[str, str] | None = None,
                      short_to_long: dict[str, dict] | None = None,
                      pages: list[dict] | None = None,
                      ig_by_page: dict[str, dict] | None = None,
                      subscribe_ok: bool = True,
                      unsubscribe_ok: bool = True):
    """httpx.MockTransport handler を組み立てる。

    Meta Graph API の各 endpoint をパス + パラメータで分岐する。
    """
    if code_to_short is None:
        code_to_short = {"the-code": "short-uat"}
    if short_to_long is None:
        short_to_long = {"short-uat": {"access_token": "long-uat", "expires_in": 5183944}}
    if pages is None:
        pages = [{
            "id": "page-1", "name": "Highlife JPN",
            "access_token": "page-1-token",
            "instagram_business_account": {"id": "ig-1"},
        }]
    if ig_by_page is None:
        ig_by_page = {"page-1": {"id": "ig-1", "username": "highlifejpn"}}

    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        params = dict(req.url.params)
        if path.endswith("/oauth/access_token"):
            if "code" in params:  # 短期交換
                code = params["code"]
                if code in code_to_short:
                    return _ok({"access_token": code_to_short[code]})
                return _err(400, {"type": "OAuthException", "code": 100,
                                   "message": "Invalid verification code format."})
            if params.get("grant_type") == "fb_exchange_token":
                short = params.get("fb_exchange_token")
                if short in short_to_long:
                    return _ok(short_to_long[short])
                return _err(400, {"type": "OAuthException", "code": 190,
                                   "message": "Invalid token"})
        if path.endswith("/me/accounts"):
            return _ok({"data": pages})
        if path.endswith("/subscribed_apps"):
            if not subscribe_ok and req.method == "POST":
                return _err(400, {"type": "GraphMethodException", "code": 100,
                                   "message": "Unsupported"})
            if not unsubscribe_ok and req.method == "DELETE":
                return _err(400, {"type": "GraphMethodException", "code": 100,
                                   "message": "Cannot unsubscribe"})
            return _ok({"success": True})
        # GET /{page_id} で IG account fetch
        for pid, iba in ig_by_page.items():
            if path.endswith(f"/{pid}"):
                if iba is None:
                    return _ok({})
                return _ok({"instagram_business_account": iba})
        return _ok({})

    return handler


def _ok(payload: dict) -> httpx.Response:
    return httpx.Response(200, content=json.dumps(payload).encode("utf-8"),
                          headers={"content-type": "application/json"})


def _err(status: int, error_body: dict) -> httpx.Response:
    return httpx.Response(status, content=json.dumps({"error": error_body}).encode("utf-8"),
                          headers={"content-type": "application/json"})


def _patch_graph(handler):
    """meta_graph._request 内で生成する httpx.AsyncClient を MockTransport ベースに置換。"""
    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def _make_client(*args, **kwargs):
        kwargs.pop("timeout", None)
        return real_async_client(transport=transport, timeout=5.0)

    return patch("app.services.meta_graph.httpx.AsyncClient", side_effect=_make_client)


# ---------------------------------------------------------------------------
# POST /meta/connect/start
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connect_start_returns_auth_url_and_state(app_client):
    redis_mock = AsyncMock()
    with patch("app.services.oauth_state.get_redis", return_value=redis_mock):
        resp = await app_client.post("/api/v1/meta/connect/start")
    assert resp.status_code == 200
    body = resp.json()
    # 必要 scope を含む authorize URL
    assert "facebook.com" in body["auth_url"]
    assert "client_id=test-app-id-123" in body["auth_url"]
    assert "pages_messaging" in body["auth_url"]
    assert "instagram_basic" in body["auth_url"]
    assert "redirect_uri=https" in body["auth_url"]
    # state が返り、Redis に書き込まれている
    assert isinstance(body["state"], str) and len(body["state"]) >= 32
    redis_mock.setex.assert_called_once()
    args = redis_mock.setex.call_args.args
    assert args[1] == 600  # 10 分 TTL


@pytest.mark.asyncio
async def test_connect_start_503_when_redis_down(app_client):
    """Redis 未接続なら 503。"""
    with patch("app.services.oauth_state.get_redis", return_value=None):
        resp = await app_client.post("/api/v1/meta/connect/start")
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_connect_start_500_when_redirect_uri_missing(app_client, monkeypatch):
    monkeypatch.delenv("META_OAUTH_REDIRECT_URI", raising=False)
    redis_mock = AsyncMock()
    with patch("app.services.oauth_state.get_redis", return_value=redis_mock):
        resp = await app_client.post("/api/v1/meta/connect/start")
    assert resp.status_code == 500


# ---------------------------------------------------------------------------
# GET /meta/connect/callback
# ---------------------------------------------------------------------------


def _make_redis_with_state(payload_dict: dict | None) -> tuple[AsyncMock, MagicMock]:
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
    return redis_mock, redis_mock.pipeline


@pytest.mark.asyncio
async def test_callback_invalid_state_returns_400(app_client):
    redis_mock, _ = _make_redis_with_state(None)  # Redis に該当なし
    with patch("app.services.oauth_state.get_redis", return_value=redis_mock):
        resp = await app_client.get(
            "/api/v1/meta/connect/callback?code=c&state=missing-state"
        )
    assert resp.status_code == 400
    assert "state" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_callback_state_tenant_mismatch_returns_400(app_client):
    """state の tenant_id が現リクエストの tenant と違うなら CSRF。"""
    redis_mock, _ = _make_redis_with_state({
        "tenant_id": 1,  # 現テナント (999) と不一致
        "staff_id": 1,
        "created_at": "2026-04-30T12:00:00+00:00",
        "nonce": "x",
    })
    with patch("app.services.oauth_state.get_redis", return_value=redis_mock):
        resp = await app_client.get(
            "/api/v1/meta/connect/callback?code=c&state=valid-state"
        )
    assert resp.status_code == 400
    assert "テナント" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_callback_happy_path_inserts_tenant_meta_config(app_client, db_session):
    """正常フロー: Page を 1 つ接続 → DB 保存。"""
    redis_mock, _ = _make_redis_with_state({
        "tenant_id": 999,
        "staff_id": 0,
        "created_at": "2026-04-30T12:00:00+00:00",
        "nonce": "x",
    })
    handler = _mk_graph_handler()

    with patch("app.services.oauth_state.get_redis", return_value=redis_mock), \
         _patch_graph(handler):
        resp = await app_client.get(
            "/api/v1/meta/connect/callback?code=the-code&state=ok-state"
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["connected_pages"][0]["page_id"] == "page-1"
    assert body["connected_pages"][0]["instagram_username"] == "highlifejpn"
    assert body["failed_pages"] == []

    # DB に行が入った
    row = (await db_session.execute(text(
        "SELECT page_id, page_name, instagram_business_account_id, "
        "instagram_username, is_active, page_access_token_encrypted, "
        "subscribed_fields FROM tenant_meta_config "
        "WHERE tenant_id = 999 AND page_id = 'page-1'"
    ))).first()
    assert row is not None
    assert row[0] == "page-1"
    assert row[1] == "Highlife JPN"
    assert row[2] == "ig-1"
    assert row[3] == "highlifejpn"
    assert bool(row[4]) is True
    # token は Fernet 暗号化（生 token と一致しない）
    encrypted_blob = row[5]
    if isinstance(encrypted_blob, (bytes, bytearray, memoryview)):
        encrypted_str = bytes(encrypted_blob).decode("ascii")
    else:
        encrypted_str = str(encrypted_blob)
    assert encrypted_str != "page-1-token"
    decrypted = encryption.decrypt(encrypted_str)
    assert decrypted == "page-1-token"
    # subscribed_fields に messages が入る
    fields = json.loads(row[6])
    assert "messages" in fields


@pytest.mark.asyncio
async def test_callback_handles_meta_oauth_exception(app_client):
    """Meta が OAuthException を返すと 502。"""
    redis_mock, _ = _make_redis_with_state({
        "tenant_id": 999, "staff_id": 0,
        "created_at": "x", "nonce": "y",
    })
    handler = _mk_graph_handler(code_to_short={})  # 全コード reject

    with patch("app.services.oauth_state.get_redis", return_value=redis_mock), \
         _patch_graph(handler):
        resp = await app_client.get(
            "/api/v1/meta/connect/callback?code=bad&state=ok-state"
        )
    assert resp.status_code == 502


@pytest.mark.asyncio
async def test_callback_no_pages_returns_400(app_client):
    """管理可能 Page 0 件で 400。"""
    redis_mock, _ = _make_redis_with_state({
        "tenant_id": 999, "staff_id": 0, "created_at": "x", "nonce": "y",
    })
    handler = _mk_graph_handler(pages=[])

    with patch("app.services.oauth_state.get_redis", return_value=redis_mock), \
         _patch_graph(handler):
        resp = await app_client.get(
            "/api/v1/meta/connect/callback?code=the-code&state=ok-state"
        )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_callback_subscribe_failure_recorded_in_failed_pages(app_client, db_session):
    """subscribe_apps 失敗 Page は failed_pages に入り、DB には保存されない。"""
    redis_mock, _ = _make_redis_with_state({
        "tenant_id": 999, "staff_id": 0, "created_at": "x", "nonce": "y",
    })
    handler = _mk_graph_handler(subscribe_ok=False)

    with patch("app.services.oauth_state.get_redis", return_value=redis_mock), \
         _patch_graph(handler):
        resp = await app_client.get(
            "/api/v1/meta/connect/callback?code=the-code&state=ok-state"
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["connected_pages"] == []
    assert len(body["failed_pages"]) == 1
    assert body["failed_pages"][0]["reason"] == "subscribe_failed"

    # DB に何も書き込まれていない
    count = (await db_session.execute(text(
        "SELECT COUNT(*) FROM tenant_meta_config"
    ))).scalar_one()
    assert count == 0


@pytest.mark.asyncio
async def test_callback_upsert_pattern_updates_existing_active_row(app_client, db_session):
    """同 page_id の active 行が既にあれば UPDATE（INSERT は増えない）。"""
    # 事前に 1 行投入（暗号化 token も Fernet）
    encrypted = encryption.encrypt("old-token").encode("ascii")
    await db_session.execute(text("""
        INSERT INTO tenant_meta_config
            (tenant_id, page_id, page_name, page_access_token_encrypted,
             subscribed_fields, is_active)
        VALUES (999, 'page-1', 'Old Name', :tok, '[]', 1)
    """), {"tok": encrypted})
    await db_session.commit()

    redis_mock, _ = _make_redis_with_state({
        "tenant_id": 999, "staff_id": 0, "created_at": "x", "nonce": "y",
    })
    handler = _mk_graph_handler()

    with patch("app.services.oauth_state.get_redis", return_value=redis_mock), \
         _patch_graph(handler):
        resp = await app_client.get(
            "/api/v1/meta/connect/callback?code=the-code&state=ok-state"
        )
    assert resp.status_code == 200

    rows = (await db_session.execute(text(
        "SELECT page_name FROM tenant_meta_config WHERE tenant_id = 999 AND page_id = 'page-1'"
    ))).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "Highlife JPN"  # UPDATE で page_name 更新


# ---------------------------------------------------------------------------
# DELETE /meta/connect/{page_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_page_unsubscribes_and_marks_inactive(app_client, db_session):
    encrypted = encryption.encrypt("page-1-token").encode("ascii")
    await db_session.execute(text("""
        INSERT INTO tenant_meta_config
            (tenant_id, page_id, page_name, page_access_token_encrypted,
             subscribed_fields, is_active)
        VALUES (999, 'page-1', 'P', :tok, '[]', 1)
    """), {"tok": encrypted})
    await db_session.commit()

    handler = _mk_graph_handler()
    with _patch_graph(handler):
        resp = await app_client.delete("/api/v1/meta/connect/page-1")

    assert resp.status_code == 200
    body = resp.json()
    assert body["page_id"] == "page-1"
    assert body["is_active"] is False
    assert body["meta_unsubscribe_ok"] is True

    row = (await db_session.execute(text(
        "SELECT is_active, deactivated_at FROM tenant_meta_config "
        "WHERE tenant_id = 999 AND page_id = 'page-1'"
    ))).first()
    assert bool(row[0]) is False
    assert row[1] is not None


@pytest.mark.asyncio
async def test_delete_page_404_when_not_found(app_client):
    handler = _mk_graph_handler()
    with _patch_graph(handler):
        resp = await app_client.delete("/api/v1/meta/connect/no-such-page")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_page_marks_inactive_even_when_meta_unsubscribe_fails(app_client, db_session):
    """Meta unsubscribe が失敗しても DB の is_active=FALSE は実行される。"""
    encrypted = encryption.encrypt("page-1-token").encode("ascii")
    await db_session.execute(text("""
        INSERT INTO tenant_meta_config
            (tenant_id, page_id, page_name, page_access_token_encrypted,
             subscribed_fields, is_active)
        VALUES (999, 'page-1', 'P', :tok, '[]', 1)
    """), {"tok": encrypted})
    await db_session.commit()

    handler = _mk_graph_handler(unsubscribe_ok=False)
    with _patch_graph(handler):
        resp = await app_client.delete("/api/v1/meta/connect/page-1")

    assert resp.status_code == 200
    body = resp.json()
    assert body["meta_unsubscribe_ok"] is False  # Meta API は API エラー
    # DB は確実に inactive
    row = (await db_session.execute(text(
        "SELECT is_active FROM tenant_meta_config WHERE page_id = 'page-1'"
    ))).first()
    assert bool(row[0]) is False


@pytest.mark.asyncio
async def test_delete_page_returns_500_when_token_decrypt_fails(app_client, db_session, monkeypatch):
    """保存トークンが現在の Fernet 鍵で復号できないと 500。"""
    # 別鍵で暗号化したトークンを保存
    other_key = Fernet.generate_key()
    other_fernet = Fernet(other_key)
    bogus_encrypted = other_fernet.encrypt(b"page-1-token").decode("ascii").encode("ascii")
    await db_session.execute(text("""
        INSERT INTO tenant_meta_config
            (tenant_id, page_id, page_name, page_access_token_encrypted,
             subscribed_fields, is_active)
        VALUES (999, 'page-1', 'P', :tok, '[]', 1)
    """), {"tok": bogus_encrypted})
    await db_session.commit()

    handler = _mk_graph_handler()
    with _patch_graph(handler):
        resp = await app_client.delete("/api/v1/meta/connect/page-1")
    assert resp.status_code == 500
