"""
backend/app/routers/meta_inbox.py の `GET /api/v1/meta/channels` 統合テスト
（Phase 1-D Sprint 3）。

`test_meta_oauth_endpoints.py` と同じ構成（最小 FastAPI app + SQLite + dependency
override）で、Channels 一覧 endpoint の挙動を網羅する。

カバー:
- 接続済 0 件で empty list
- 1 件で正しい payload（page_access_token は絶対に含めない）
- include_inactive=false（既定）で is_active=FALSE 行を除外
- include_inactive=true で全件返却
- 複数件で connected_at DESC ソート
- tenant 分離（自テナントの行のみ返却）

実行:
    pytest backend/tests/test_meta_channels.py -v

変更履歴:
    2026-04-30: Phase 1-D Sprint 3 初版
"""

from __future__ import annotations

import json
import os
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

# DATABASE_URL を SQLite に必ず差し替え（モジュール import 順の罠回避）
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.auth.dependencies import (
    get_current_tenant,
    get_current_user,
)
from app.database import get_db
from app.routers import meta_inbox
from app.services import encryption


# ---------------------------------------------------------------------------
# fixtures（`test_meta_oauth_endpoints.py` の構造を踏襲）
# ---------------------------------------------------------------------------


_ALL_PERMS = {"channels.view", "channels.manage", "messaging.view", "messaging.send"}
_VIEW_ONLY_PERMS = {"channels.view"}


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    @event.listens_for(eng.sync_engine, "connect")
    def _setup(dbapi_conn, _):
        dbapi_conn.create_function("NOW", 0, lambda: "2026-04-30 12:00:00+00:00")
        dbapi_conn.execute("PRAGMA foreign_keys = ON")

    async with eng.begin() as conn:
        # tenant_meta_config（migration 040 を SQLite 用に縮小）
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
        # staff（migration 019 を SQLite 用に縮小、表示名取得に使う列のみ）
        await conn.execute(text("""
            CREATE TABLE staff (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id INTEGER NOT NULL DEFAULT 999,
                primary_email VARCHAR(255) NOT NULL,
                surname_jp VARCHAR(50),
                given_name_jp VARCHAR(50)
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
    """暗号化鍵を仕込む（既存 token を BLOB に書き込むため必要）。"""
    encryption.reset_cache()
    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("METADATA_FERNET_KEY", key)
    yield
    encryption.reset_cache()


def _mock_user():
    u = MagicMock()
    u.id = 1
    u.tenant_id = 999
    u.email = "tester@example.com"
    return u


def _build_app(db_session, tenant_id: int = 999, perms: set[str] = _ALL_PERMS):
    """meta_inbox ルーター付き最小 FastAPI app を作る（fixture と直接 helper 兼用）。"""
    app = FastAPI()

    async def override_db():
        yield db_session

    async def override_user():
        return _mock_user()

    async def override_tenant():
        return tenant_id

    app.include_router(meta_inbox.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_current_tenant] = override_tenant
    return app


@pytest_asyncio.fixture
async def app_client(db_session, fernet_env):
    """既定の app client（all permissions）。"""
    app = _build_app(db_session, tenant_id=999, perms=_ALL_PERMS)
    transport = ASGITransport(app=app)
    with ExitStack() as stack:
        stack.enter_context(patch(
            "app.auth.dependencies.load_user_permissions",
            new=AsyncMock(return_value=_ALL_PERMS),
        ))
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    app.dependency_overrides.clear()


async def _insert_channel(
    db_session,
    *,
    tenant_id: int,
    page_id: str,
    page_name: str,
    instagram_business_account_id: str | None = None,
    instagram_username: str | None = None,
    is_active: bool = True,
    connected_at: str | None = None,
    page_token_expires_at: str | None = None,
    connected_by_staff_id: int | None = None,
    token_plain: str = "fake-page-token",
):
    """tenant_meta_config に 1 行 INSERT するヘルパー。"""
    encrypted = encryption.encrypt(token_plain).encode("ascii")
    sql = """
        INSERT INTO tenant_meta_config
            (tenant_id, page_id, page_name, page_access_token_encrypted,
             instagram_business_account_id, instagram_username,
             subscribed_fields, connected_by_staff_id,
             connected_at, page_token_expires_at, is_active)
        VALUES
            (:tenant_id, :page_id, :page_name, :token,
             :ig_id, :ig_user,
             '[]', :staff_id,
             COALESCE(:connected_at, CURRENT_TIMESTAMP),
             :expires_at, :is_active)
    """
    await db_session.execute(text(sql), {
        "tenant_id": tenant_id,
        "page_id": page_id,
        "page_name": page_name,
        "token": encrypted,
        "ig_id": instagram_business_account_id,
        "ig_user": instagram_username,
        "staff_id": connected_by_staff_id,
        "connected_at": connected_at,
        "expires_at": page_token_expires_at,
        "is_active": 1 if is_active else 0,
    })
    await db_session.commit()


# ---------------------------------------------------------------------------
# テスト本体
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_channels_returns_empty_when_no_connections(app_client):
    """接続済 0 件なら channels が空配列で 200。"""
    resp = await app_client.get("/api/v1/meta/channels")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"channels": []}


@pytest.mark.asyncio
async def test_list_channels_returns_single_active_page(app_client, db_session):
    """1 件接続済で page_id/page_name/IG 情報が正しく返る。token は含まれない。"""
    await _insert_channel(
        db_session,
        tenant_id=999,
        page_id="page-1",
        page_name="Highlife JPN",
        instagram_business_account_id="ig-1",
        instagram_username="highlifejpn",
        token_plain="VERY-SECRET-TOKEN-SHOULD-NEVER-LEAK",
    )

    resp = await app_client.get("/api/v1/meta/channels")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["channels"]) == 1
    ch = body["channels"][0]
    assert ch["page_id"] == "page-1"
    assert ch["page_name"] == "Highlife JPN"
    assert ch["instagram_business_account_id"] == "ig-1"
    assert ch["instagram_username"] == "highlifejpn"
    assert ch["is_active"] is True
    assert ch["connected_at"] is not None
    # Page Access Token は絶対に出てこない
    raw_text = resp.text
    assert "VERY-SECRET-TOKEN-SHOULD-NEVER-LEAK" not in raw_text
    assert "page_access_token" not in raw_text
    assert "page_access_token_encrypted" not in raw_text


@pytest.mark.asyncio
async def test_list_channels_excludes_inactive_by_default(app_client, db_session):
    """include_inactive 未指定（既定 false）で is_active=FALSE 行が除外される。"""
    await _insert_channel(
        db_session, tenant_id=999, page_id="active-1", page_name="Active",
        is_active=True,
    )
    await _insert_channel(
        db_session, tenant_id=999, page_id="inactive-1", page_name="Inactive",
        is_active=False,
    )
    resp = await app_client.get("/api/v1/meta/channels")
    assert resp.status_code == 200
    page_ids = [c["page_id"] for c in resp.json()["channels"]]
    assert page_ids == ["active-1"]


@pytest.mark.asyncio
async def test_list_channels_include_inactive_true_returns_all(app_client, db_session):
    """include_inactive=true で is_active=FALSE も含めて返却される。"""
    await _insert_channel(
        db_session, tenant_id=999, page_id="active-1", page_name="Active",
        is_active=True,
    )
    await _insert_channel(
        db_session, tenant_id=999, page_id="inactive-1", page_name="Inactive",
        is_active=False,
    )
    resp = await app_client.get("/api/v1/meta/channels?include_inactive=true")
    assert resp.status_code == 200
    page_ids = sorted([c["page_id"] for c in resp.json()["channels"]])
    assert page_ids == ["active-1", "inactive-1"]
    # is_active boolean が両方 boolean で返る
    actives = {c["page_id"]: c["is_active"] for c in resp.json()["channels"]}
    assert actives["active-1"] is True
    assert actives["inactive-1"] is False


@pytest.mark.asyncio
async def test_list_channels_orders_by_connected_at_desc(app_client, db_session):
    """connected_at が新しい順（DESC）で返る。"""
    await _insert_channel(
        db_session, tenant_id=999, page_id="page-old", page_name="Old",
        connected_at="2026-01-01 00:00:00+00:00",
    )
    await _insert_channel(
        db_session, tenant_id=999, page_id="page-mid", page_name="Mid",
        connected_at="2026-03-01 00:00:00+00:00",
    )
    await _insert_channel(
        db_session, tenant_id=999, page_id="page-new", page_name="New",
        connected_at="2026-04-30 00:00:00+00:00",
    )
    resp = await app_client.get("/api/v1/meta/channels")
    assert resp.status_code == 200
    page_ids = [c["page_id"] for c in resp.json()["channels"]]
    assert page_ids == ["page-new", "page-mid", "page-old"]


@pytest.mark.asyncio
async def test_list_channels_filters_other_tenants(app_client, db_session):
    """別テナントの行は SELECT 結果に含まれない（多重テナント漏洩防止）。"""
    # 自テナント (999) の行
    await _insert_channel(
        db_session, tenant_id=999, page_id="own-page", page_name="Own",
    )
    # 他テナント (888) の行（漏れてはいけない）
    await _insert_channel(
        db_session, tenant_id=888, page_id="other-page", page_name="Other",
    )
    resp = await app_client.get("/api/v1/meta/channels")
    assert resp.status_code == 200
    page_ids = [c["page_id"] for c in resp.json()["channels"]]
    assert page_ids == ["own-page"]
    assert "other-page" not in page_ids


@pytest.mark.asyncio
async def test_list_channels_resolves_staff_name_when_present(app_client, db_session):
    """connected_by_staff_id が staff にある場合、staff_name が `surname_jp + ' ' + given_name_jp` で返る。"""
    # staff 行を投入
    await db_session.execute(text("""
        INSERT INTO staff (id, tenant_id, primary_email, surname_jp, given_name_jp)
        VALUES (5, 999, 'yamada@example.com', '山田', '太郎')
    """))
    await db_session.commit()

    await _insert_channel(
        db_session, tenant_id=999, page_id="page-1", page_name="P",
        connected_by_staff_id=5,
    )
    resp = await app_client.get("/api/v1/meta/channels")
    assert resp.status_code == 200
    ch = resp.json()["channels"][0]
    assert ch["connected_by_staff_id"] == 5
    assert ch["connected_by_staff_name"] == "山田 太郎"


@pytest.mark.asyncio
async def test_list_channels_returns_null_staff_name_when_unlinked(app_client, db_session):
    """connected_by_staff_id が NULL もしくは staff に存在しない場合 staff_name は NULL。"""
    await _insert_channel(
        db_session, tenant_id=999, page_id="page-1", page_name="P",
        connected_by_staff_id=None,
    )
    resp = await app_client.get("/api/v1/meta/channels")
    assert resp.status_code == 200
    ch = resp.json()["channels"][0]
    assert ch["connected_by_staff_id"] is None
    assert ch["connected_by_staff_name"] is None


@pytest.mark.asyncio
async def test_list_channels_returns_token_expires_at_when_set(app_client, db_session):
    """page_token_expires_at がレスポンスに ISO 文字列として返る。"""
    await _insert_channel(
        db_session, tenant_id=999, page_id="page-1", page_name="P",
        page_token_expires_at="2026-06-29 12:00:00+00:00",
    )
    resp = await app_client.get("/api/v1/meta/channels")
    assert resp.status_code == 200
    ch = resp.json()["channels"][0]
    assert ch["page_token_expires_at"] is not None
    # SQLite は str 返却、PostgreSQL は datetime（_format_dt で str 化）。
    # ともかく "2026" を含む文字列であれば OK
    assert "2026" in ch["page_token_expires_at"]
