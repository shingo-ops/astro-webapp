"""
backend/app/routers/meta_inbox.py の `GET /api/v1/conversations` 統合テスト
（Phase 1-D Sprint 4）。

`test_meta_channels.py` と同じ構成（最小 FastAPI app + SQLite + dependency
override）で、会話一覧 endpoint の挙動を網羅する。

カバー:
- 接続済 0 件で空配列
- 1 件投稿で正しい payload（lead_id / lead_code / customer_name / platform /
  last_message_text / last_message_at / unread_count / messaging_window_expires_at）
- last_message_at DESC で複数件ソート
- platform=messenger / instagram フィルタ
- unread_only=true で unread_count==0 を除外
- tenant 分離（自テナントのみ）
- limit / offset pagination
- permission 不足で 403

実行:
    pytest backend/tests/test_conversations.py -v

変更履歴:
    2026-04-30: Phase 1-D Sprint 4 初版
"""

from __future__ import annotations

import os
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

# DATABASE_URL を SQLite に必ず差し替え（モジュール import 順の罠回避）
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

import pytest
import pytest_asyncio
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


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


_ALL_PERMS = {"channels.view", "channels.manage", "messaging.view", "messaging.send"}
_NO_VIEW_PERMS = {"channels.view"}  # messaging.view が無いケース


@pytest_asyncio.fixture
async def engine():
    """SQLite に leads + meta_messages を最小スキーマで作成する。"""
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    @event.listens_for(eng.sync_engine, "connect")
    def _setup(dbapi_conn, _):
        dbapi_conn.create_function("NOW", 0, lambda: "2026-04-30 12:00:00+00:00")
        dbapi_conn.execute("PRAGMA foreign_keys = ON")

    async with eng.begin() as conn:
        # leads（migration 015 系を SQLite 用に縮小、本テストで必要な列のみ）
        await conn.execute(text("""
            CREATE TABLE leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id INTEGER NOT NULL DEFAULT 999,
                lead_code VARCHAR(20),
                customer_name VARCHAR(200),
                source VARCHAR(100),
                status VARCHAR(50),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        # meta_messages（migration 012 + 041 を SQLite 用に縮小、Sprint 4 で参照する列）
        await conn.execute(text("""
            CREATE TABLE meta_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id INTEGER NOT NULL,
                lead_id INTEGER,
                platform VARCHAR(20) NOT NULL DEFAULT 'messenger',
                sender_id VARCHAR(100) NOT NULL,
                sender_name VARCHAR(200),
                message_text TEXT,
                direction VARCHAR(10) NOT NULL DEFAULT 'inbound',
                raw_payload TEXT,
                message_id VARCHAR(100),
                recipient_id VARCHAR(100),
                messaging_type VARCHAR(20),
                message_tag VARCHAR(50),
                sent_by_staff_id INTEGER,
                error_code VARCHAR(50),
                error_message TEXT,
                seen_at TIMESTAMP,
                seen_by_staff_id INTEGER,
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


def _mock_user():
    u = MagicMock()
    u.id = 1
    u.tenant_id = 999
    u.email = "tester@example.com"
    return u


def _build_app(db_session, tenant_id: int = 999):
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
async def app_client(db_session):
    """既定 app client（all permissions）。"""
    app = _build_app(db_session, tenant_id=999)
    transport = ASGITransport(app=app)
    with ExitStack() as stack:
        stack.enter_context(patch(
            "app.auth.dependencies.load_user_permissions",
            new=AsyncMock(return_value=_ALL_PERMS),
        ))
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def app_client_no_view(db_session):
    """messaging.view 権限が無い app client（403 確認用）。"""
    app = _build_app(db_session, tenant_id=999)
    transport = ASGITransport(app=app)
    with ExitStack() as stack:
        stack.enter_context(patch(
            "app.auth.dependencies.load_user_permissions",
            new=AsyncMock(return_value=_NO_VIEW_PERMS),
        ))
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    app.dependency_overrides.clear()


async def _insert_lead(db_session, *, lead_id: int, tenant_id: int = 999,
                       lead_code: str | None = None, customer_name: str = "John Doe",
                       source: str | None = None):
    await db_session.execute(text("""
        INSERT INTO leads (id, tenant_id, lead_code, customer_name, source)
        VALUES (:id, :tenant_id, :code, :name, :source)
    """), {
        "id": lead_id, "tenant_id": tenant_id,
        "code": lead_code or f"LD-{lead_id:05d}",
        "name": customer_name, "source": source,
    })
    await db_session.commit()


async def _insert_message(db_session, *, lead_id: int, tenant_id: int = 999,
                          platform: str = "messenger", direction: str = "inbound",
                          message_text: str = "Hello", sender_id: str = "PSID-1",
                          created_at: str | None = None,
                          seen_at: str | None = None):
    await db_session.execute(text("""
        INSERT INTO meta_messages
            (tenant_id, lead_id, platform, sender_id, message_text, direction, created_at, seen_at)
        VALUES
            (:tenant_id, :lead_id, :platform, :sender_id, :text, :direction,
             COALESCE(:created_at, CURRENT_TIMESTAMP), :seen_at)
    """), {
        "tenant_id": tenant_id, "lead_id": lead_id,
        "platform": platform, "sender_id": sender_id,
        "text": message_text, "direction": direction,
        "created_at": created_at, "seen_at": seen_at,
    })
    await db_session.commit()


# ---------------------------------------------------------------------------
# テスト本体
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_conversations_returns_empty_when_no_messages(app_client):
    resp = await app_client.get("/api/v1/conversations")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"conversations": [], "next_cursor": None}


@pytest.mark.asyncio
async def test_list_conversations_returns_one_conversation_with_unread(
    app_client, db_session,
):
    """1 lead + 1 inbound メッセージで unread_count=1、最新値が正しく返る。"""
    await _insert_lead(db_session, lead_id=1, customer_name="Alice")
    await _insert_message(
        db_session, lead_id=1, message_text="Hi there",
        created_at="2026-04-30 10:00:00+00:00",
    )
    resp = await app_client.get("/api/v1/conversations")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["conversations"]) == 1
    conv = body["conversations"][0]
    assert conv["lead_id"] == 1
    assert conv["customer_name"] == "Alice"
    assert conv["platform"] == "messenger"
    assert conv["last_message_text"] == "Hi there"
    assert conv["last_message_direction"] == "inbound"
    assert conv["unread_count"] == 1
    # messaging_window_expires_at は inbound から +24h
    assert conv["messaging_window_expires_at"] is not None
    assert "2026-05-01" in conv["messaging_window_expires_at"]


@pytest.mark.asyncio
async def test_list_conversations_unread_count_excludes_seen(app_client, db_session):
    """seen_at が設定された inbound は unread にカウントしない。"""
    await _insert_lead(db_session, lead_id=1)
    # 既読
    await _insert_message(
        db_session, lead_id=1, message_text="seen msg",
        created_at="2026-04-30 09:00:00+00:00",
        seen_at="2026-04-30 09:30:00+00:00",
    )
    # 未読
    await _insert_message(
        db_session, lead_id=1, message_text="unseen msg",
        created_at="2026-04-30 10:00:00+00:00",
    )
    resp = await app_client.get("/api/v1/conversations")
    body = resp.json()
    assert body["conversations"][0]["unread_count"] == 1
    assert body["conversations"][0]["last_message_text"] == "unseen msg"


@pytest.mark.asyncio
async def test_list_conversations_outbound_does_not_count_as_unread(
    app_client, db_session,
):
    """outbound メッセージは unread_count に含めない。"""
    await _insert_lead(db_session, lead_id=1)
    await _insert_message(
        db_session, lead_id=1, direction="outbound", message_text="Reply from staff",
        created_at="2026-04-30 11:00:00+00:00",
    )
    resp = await app_client.get("/api/v1/conversations")
    body = resp.json()
    assert body["conversations"][0]["unread_count"] == 0
    assert body["conversations"][0]["last_message_direction"] == "outbound"


@pytest.mark.asyncio
async def test_list_conversations_orders_by_last_message_at_desc(app_client, db_session):
    await _insert_lead(db_session, lead_id=1, customer_name="Old")
    await _insert_lead(db_session, lead_id=2, customer_name="New")
    await _insert_message(
        db_session, lead_id=1, created_at="2026-04-29 10:00:00+00:00",
    )
    await _insert_message(
        db_session, lead_id=2, created_at="2026-04-30 10:00:00+00:00",
    )
    resp = await app_client.get("/api/v1/conversations")
    body = resp.json()
    names = [c["customer_name"] for c in body["conversations"]]
    assert names == ["New", "Old"]


@pytest.mark.asyncio
async def test_list_conversations_filters_other_tenants(app_client, db_session):
    """別テナント (888) の lead/message は返らない。"""
    await _insert_lead(db_session, lead_id=1, tenant_id=999, customer_name="Own")
    await _insert_lead(db_session, lead_id=2, tenant_id=888, customer_name="Other")
    await _insert_message(
        db_session, lead_id=1, tenant_id=999, message_text="own",
    )
    await _insert_message(
        db_session, lead_id=2, tenant_id=888, message_text="other",
    )
    resp = await app_client.get("/api/v1/conversations")
    names = [c["customer_name"] for c in resp.json()["conversations"]]
    assert names == ["Own"]


@pytest.mark.asyncio
async def test_list_conversations_filters_by_platform(app_client, db_session):
    """platform=instagram で messenger 行が除外される。"""
    await _insert_lead(db_session, lead_id=1, customer_name="MsngrUser")
    await _insert_lead(db_session, lead_id=2, customer_name="IGUser")
    await _insert_message(
        db_session, lead_id=1, platform="messenger",
        created_at="2026-04-30 09:00:00+00:00",
    )
    await _insert_message(
        db_session, lead_id=2, platform="instagram",
        created_at="2026-04-30 10:00:00+00:00",
    )
    resp_ig = await app_client.get("/api/v1/conversations?platform=instagram")
    names_ig = [c["customer_name"] for c in resp_ig.json()["conversations"]]
    assert names_ig == ["IGUser"]

    resp_msgr = await app_client.get("/api/v1/conversations?platform=messenger")
    names_msgr = [c["customer_name"] for c in resp_msgr.json()["conversations"]]
    assert names_msgr == ["MsngrUser"]


@pytest.mark.asyncio
async def test_list_conversations_unread_only_excludes_zero(app_client, db_session):
    """unread_only=true で unread==0 の会話を除外。"""
    await _insert_lead(db_session, lead_id=1, customer_name="HasUnread")
    await _insert_lead(db_session, lead_id=2, customer_name="AllRead")
    # lead 1: 未読 inbound
    await _insert_message(
        db_session, lead_id=1, message_text="unread",
        created_at="2026-04-30 09:00:00+00:00",
    )
    # lead 2: 既読 inbound
    await _insert_message(
        db_session, lead_id=2, message_text="read",
        created_at="2026-04-30 10:00:00+00:00",
        seen_at="2026-04-30 10:30:00+00:00",
    )
    resp = await app_client.get("/api/v1/conversations?unread_only=true")
    names = [c["customer_name"] for c in resp.json()["conversations"]]
    assert names == ["HasUnread"]


@pytest.mark.asyncio
async def test_list_conversations_pagination_limit_offset(app_client, db_session):
    """limit / offset で順番通りに分割取得できる。"""
    for i in range(1, 6):
        await _insert_lead(db_session, lead_id=i, customer_name=f"User{i}")
        await _insert_message(
            db_session, lead_id=i,
            created_at=f"2026-04-30 1{i}:00:00+00:00",
        )
    # 最新 2 件
    resp1 = await app_client.get("/api/v1/conversations?limit=2&offset=0")
    names1 = [c["customer_name"] for c in resp1.json()["conversations"]]
    assert names1 == ["User5", "User4"]
    # 次の 2 件
    resp2 = await app_client.get("/api/v1/conversations?limit=2&offset=2")
    names2 = [c["customer_name"] for c in resp2.json()["conversations"]]
    assert names2 == ["User3", "User2"]


@pytest.mark.asyncio
async def test_list_conversations_returns_403_without_messaging_view(app_client_no_view):
    """messaging.view 権限が無いと 403。"""
    resp = await app_client_no_view.get("/api/v1/conversations")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_list_conversations_returns_only_latest_message_per_lead(
    app_client, db_session,
):
    """同 lead に複数 inbound あっても、会話 1 件として最新メッセージだけ返す。"""
    await _insert_lead(db_session, lead_id=1, customer_name="Alice")
    await _insert_message(
        db_session, lead_id=1, message_text="first",
        created_at="2026-04-30 09:00:00+00:00",
    )
    await _insert_message(
        db_session, lead_id=1, message_text="second",
        created_at="2026-04-30 10:00:00+00:00",
    )
    await _insert_message(
        db_session, lead_id=1, message_text="latest",
        created_at="2026-04-30 11:00:00+00:00",
    )
    resp = await app_client.get("/api/v1/conversations")
    body = resp.json()
    assert len(body["conversations"]) == 1
    assert body["conversations"][0]["last_message_text"] == "latest"
    assert body["conversations"][0]["unread_count"] == 3
