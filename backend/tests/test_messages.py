"""
backend/app/routers/leads.py の以下 endpoints の統合テスト
（Phase 1-D Sprint 4、spec §5-4 / §5-6）:
- GET  /api/v1/leads/{lead_id}/messages
- POST /api/v1/leads/{lead_id}/messages/mark-read

`test_meta_oauth_endpoints.py` / `test_conversations.py` と同じ構成
（最小 FastAPI app + SQLite + dependency override）。

カバー:
- GET messages: lead 不在で 404 / 別テナント lead で 404 / 時系列 ASC ソート /
  pagination (before, limit) / lead 概要返却 / messaging_window 計算 / 0 件で空配列
- mark-read: 未読 inbound のみ更新 / outbound は触らない / lead 不在で 404 /
  別テナント lead で 404 / staff_id 解決 / 連続呼び出しで 2 回目は 0 件
- 認可: messaging.view 不足で 403

実行:
    pytest backend/tests/test_messages.py -v

変更履歴:
    2026-04-30: Phase 1-D Sprint 4 初版
"""

from __future__ import annotations

import os
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
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
from app.routers import leads as leads_router


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


_ALL_PERMS = {"channels.view", "channels.manage", "messaging.view", "messaging.send"}
_NO_VIEW_PERMS = {"channels.view"}  # messaging.view 不足


# leads.py の SELECT は _LEAD_COLUMNS を使う。本テストでは leads テーブルに
# 全列を生やし、最低限の値を入れる。
_LEAD_DDL = """
    CREATE TABLE leads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_id INTEGER NOT NULL DEFAULT 999,
        lead_code VARCHAR(20),
        customer_name VARCHAR(200),
        company_name VARCHAR(200),
        email VARCHAR(255),
        phone VARCHAR(50),
        source VARCHAR(100),
        type VARCHAR(50),
        status VARCHAR(50),
        temperature VARCHAR(20),
        estimated_scale VARCHAR(20),
        customer_type VARCHAR(20),
        response_speed VARCHAR(20),
        monthly_forecast NUMERIC(15,2),
        prospect_rank VARCHAR(20),
        assigned_to INTEGER,
        converted_deal_id INTEGER,
        notes TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        next_action VARCHAR(500),
        next_action_date DATE,
        challenge TEXT,
        meeting_memo TEXT,
        meeting_impression VARCHAR(50),
        cs_memo TEXT,
        sales_form VARCHAR(50),
        competitor_check BOOLEAN NOT NULL DEFAULT 0,
        per_order_amount NUMERIC(15, 2),
        monthly_frequency NUMERIC(10, 2),
        nickname VARCHAR(255),
        country VARCHAR(100),
        target_titles VARCHAR(500),
        messenger_link VARCHAR(1000),
        discord_id VARCHAR(255),
        instagram_link VARCHAR(1000),
        whatsapp_link VARCHAR(1000),
        discord_user_id VARCHAR(50),
        discord_dm_channel_id VARCHAR(50),
        discord_role_sync_status VARCHAR(20),
        discord_role_sync_at TIMESTAMP,
        discord_guild_channel_id VARCHAR(50)
    )
"""

# meta_messages（migration 012 + 041）の Sprint 4 で必要な列のみ
_META_MESSAGES_DDL = """
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
"""

_STAFF_DDL = """
    CREATE TABLE staff (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_id INTEGER NOT NULL DEFAULT 999,
        primary_email VARCHAR(255) NOT NULL
    )
"""


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    @event.listens_for(eng.sync_engine, "connect")
    def _setup(dbapi_conn, _):
        dbapi_conn.create_function("NOW", 0, lambda: "2026-04-30 12:00:00+00:00")
        dbapi_conn.execute("PRAGMA foreign_keys = ON")

    async with eng.begin() as conn:
        await conn.execute(text(_LEAD_DDL))
        await conn.execute(text(_META_MESSAGES_DDL))
        await conn.execute(text(_STAFF_DDL))

    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db_session(engine):
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        yield session
        await session.rollback()


def _mock_user(email: str = "tester@example.com"):
    u = MagicMock()
    u.id = 1
    u.tenant_id = 999
    u.email = email
    return u


def _build_app(db_session, tenant_id: int = 999, user_email: str = "tester@example.com"):
    app = FastAPI()

    async def override_db():
        yield db_session

    async def override_user():
        return _mock_user(email=user_email)

    async def override_tenant():
        return tenant_id

    app.include_router(leads_router.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_current_tenant] = override_tenant
    return app


@pytest_asyncio.fixture
async def app_client(db_session):
    app = _build_app(db_session, tenant_id=999)
    transport = ASGITransport(app=app)
    with ExitStack() as stack:
        stack.enter_context(patch(
            "app.auth.dependencies.load_user_permissions",
            new=AsyncMock(return_value=_ALL_PERMS),
        ))
        # invalidate_dashboard_cache は Redis 必須なので stub
        stack.enter_context(patch(
            "app.routers.leads.invalidate_dashboard_cache",
            new=AsyncMock(return_value=None),
        ))
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def app_client_no_view(db_session):
    app = _build_app(db_session, tenant_id=999)
    transport = ASGITransport(app=app)
    with ExitStack() as stack:
        stack.enter_context(patch(
            "app.auth.dependencies.load_user_permissions",
            new=AsyncMock(return_value=_NO_VIEW_PERMS),
        ))
        stack.enter_context(patch(
            "app.routers.leads.invalidate_dashboard_cache",
            new=AsyncMock(return_value=None),
        ))
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    app.dependency_overrides.clear()


async def _insert_lead(db_session, *, lead_id: int, tenant_id: int = 999,
                       lead_code: str | None = None, customer_name: str = "Alice",
                       source: str | None = "messenger:PSID-1"):
    await db_session.execute(text("""
        INSERT INTO leads (id, tenant_id, lead_code, customer_name, source, status)
        VALUES (:id, :tenant_id, :code, :name, :source, '新規')
    """), {
        "id": lead_id, "tenant_id": tenant_id,
        "code": lead_code or f"LD-{lead_id:05d}",
        "name": customer_name, "source": source,
    })
    await db_session.commit()


async def _insert_message(db_session, *, lead_id: int, tenant_id: int = 999,
                          platform: str = "messenger", direction: str = "inbound",
                          message_text: str = "Hi", sender_id: str = "PSID-1",
                          created_at: str | None = None,
                          seen_at: str | None = None):
    await db_session.execute(text("""
        INSERT INTO meta_messages
            (tenant_id, lead_id, platform, sender_id, message_text, direction,
             created_at, seen_at)
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
# GET /leads/{id}/messages テスト
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_messages_returns_404_when_lead_missing(app_client):
    resp = await app_client.get("/api/v1/leads/9999/messages")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_messages_returns_404_when_lead_in_other_tenant(app_client, db_session):
    """別テナントの lead は 404（tenant 分離）。"""
    await _insert_lead(db_session, lead_id=1, tenant_id=888, customer_name="Other")
    resp = await app_client.get("/api/v1/leads/1/messages")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_messages_returns_403_without_messaging_view(app_client_no_view, db_session):
    await _insert_lead(db_session, lead_id=1)
    resp = await app_client_no_view.get("/api/v1/leads/1/messages")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_get_messages_empty_returns_empty_list_with_lead(app_client, db_session):
    """messages が 0 件でも lead 概要は返る、messaging_window は can_send_at_all=False。"""
    await _insert_lead(db_session, lead_id=1, customer_name="Alice")
    resp = await app_client.get("/api/v1/leads/1/messages")
    assert resp.status_code == 200
    body = resp.json()
    assert body["messages"] == []
    assert body["lead"]["id"] == 1
    assert body["lead"]["customer_name"] == "Alice"
    assert body["messaging_window"]["can_send_at_all"] is False
    assert body["messaging_window"]["last_inbound_at"] is None


@pytest.mark.asyncio
async def test_get_messages_returns_chronological_ascending(app_client, db_session):
    await _insert_lead(db_session, lead_id=1)
    await _insert_message(
        db_session, lead_id=1, message_text="third",
        created_at="2026-04-30 11:00:00+00:00",
    )
    await _insert_message(
        db_session, lead_id=1, message_text="first",
        created_at="2026-04-30 09:00:00+00:00",
    )
    await _insert_message(
        db_session, lead_id=1, message_text="second",
        created_at="2026-04-30 10:00:00+00:00",
    )
    resp = await app_client.get("/api/v1/leads/1/messages")
    body = resp.json()
    texts = [m["message_text"] for m in body["messages"]]
    assert texts == ["first", "second", "third"]


@pytest.mark.asyncio
async def test_get_messages_pagination_with_before_and_limit(app_client, db_session):
    """before=N で id<N のメッセージのみ返す（古いほうへスクロール）。"""
    await _insert_lead(db_session, lead_id=1)
    for i in range(1, 6):
        await _insert_message(
            db_session, lead_id=1, message_text=f"msg{i}",
            created_at=f"2026-04-30 0{i}:00:00+00:00",
        )
    resp_all = await app_client.get("/api/v1/leads/1/messages?limit=2")
    body_all = resp_all.json()
    assert len(body_all["messages"]) == 2
    # 古い順 → msg1, msg2
    assert [m["message_text"] for m in body_all["messages"]] == ["msg1", "msg2"]
    # 全件返した最後の id
    last_id = body_all["messages"][-1]["id"]
    # before=last_id → id < last_id（つまり msg1 のみ）
    resp_b = await app_client.get(f"/api/v1/leads/1/messages?before={last_id}")
    texts_b = [m["message_text"] for m in resp_b.json()["messages"]]
    assert texts_b == ["msg1"]


@pytest.mark.asyncio
async def test_get_messages_messaging_window_within_24h(app_client, db_session):
    """直近 inbound が 1 時間前 → can_send_response=True、requires_human_agent_tag=False。"""
    await _insert_lead(db_session, lead_id=1)
    one_hour_ago = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S+00:00")
    await _insert_message(
        db_session, lead_id=1, direction="inbound", message_text="Hi",
        created_at=one_hour_ago,
    )
    resp = await app_client.get("/api/v1/leads/1/messages")
    win = resp.json()["messaging_window"]
    assert win["can_send_response"] is True
    assert win["requires_human_agent_tag"] is False
    assert win["can_send_at_all"] is True


@pytest.mark.asyncio
async def test_get_messages_messaging_window_after_24h_within_7d(app_client, db_session):
    """24h-7d → can_send_response=False, requires_human_agent_tag=True, can_send_at_all=True"""
    await _insert_lead(db_session, lead_id=1)
    three_days_ago = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S+00:00")
    await _insert_message(
        db_session, lead_id=1, direction="inbound", message_text="Hi",
        created_at=three_days_ago,
    )
    resp = await app_client.get("/api/v1/leads/1/messages")
    win = resp.json()["messaging_window"]
    assert win["can_send_response"] is False
    assert win["requires_human_agent_tag"] is True
    assert win["can_send_at_all"] is True


@pytest.mark.asyncio
async def test_get_messages_messaging_window_beyond_7d(app_client, db_session):
    """7d 超過 → can_send_at_all=False"""
    await _insert_lead(db_session, lead_id=1)
    eight_days_ago = (datetime.now(timezone.utc) - timedelta(days=8)).strftime("%Y-%m-%d %H:%M:%S+00:00")
    await _insert_message(
        db_session, lead_id=1, direction="inbound", message_text="Hi",
        created_at=eight_days_ago,
    )
    resp = await app_client.get("/api/v1/leads/1/messages")
    win = resp.json()["messaging_window"]
    assert win["can_send_at_all"] is False
    assert win["can_send_response"] is False
    assert win["requires_human_agent_tag"] is False


@pytest.mark.asyncio
async def test_get_messages_lead_summary_includes_platform(app_client, db_session):
    await _insert_lead(db_session, lead_id=1, customer_name="Alice", source="instagram:IG-1")
    await _insert_message(
        db_session, lead_id=1, platform="instagram",
        created_at="2026-04-30 10:00:00+00:00",
    )
    resp = await app_client.get("/api/v1/leads/1/messages")
    body = resp.json()
    assert body["lead"]["platform"] == "instagram"
    assert body["lead"]["source"] == "instagram:IG-1"


# ---------------------------------------------------------------------------
# POST /leads/{id}/messages/mark-read テスト
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mark_read_updates_inbound_unseen_only(app_client, db_session):
    await _insert_lead(db_session, lead_id=1)
    # 未読 inbound 2 件
    await _insert_message(db_session, lead_id=1, direction="inbound", message_text="m1")
    await _insert_message(db_session, lead_id=1, direction="inbound", message_text="m2")
    # 既読 inbound 1 件（変化しないはず）
    await _insert_message(
        db_session, lead_id=1, direction="inbound", message_text="m3",
        seen_at="2026-04-30 09:00:00+00:00",
    )
    # outbound 1 件（更新対象外）
    await _insert_message(db_session, lead_id=1, direction="outbound", message_text="m4")

    resp = await app_client.post("/api/v1/leads/1/messages/mark-read")
    assert resp.status_code == 200
    assert resp.json() == {"marked_count": 2}

    # 確認: inbound 全件 seen_at != NULL、outbound はまだ NULL
    res = await db_session.execute(text("""
        SELECT direction, message_text, seen_at FROM meta_messages
        WHERE lead_id = 1
        ORDER BY id
    """))
    rows = res.fetchall()
    by_text = {r[1]: r for r in rows}
    assert by_text["m1"][2] is not None
    assert by_text["m2"][2] is not None
    assert by_text["m3"][2] is not None  # 既存 seen_at は維持
    assert by_text["m4"][2] is None


@pytest.mark.asyncio
async def test_mark_read_returns_404_when_lead_missing(app_client):
    resp = await app_client.post("/api/v1/leads/9999/messages/mark-read")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_mark_read_returns_404_when_lead_in_other_tenant(app_client, db_session):
    await _insert_lead(db_session, lead_id=1, tenant_id=888)
    await _insert_message(db_session, lead_id=1, tenant_id=888, message_text="x")
    resp = await app_client.post("/api/v1/leads/1/messages/mark-read")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_mark_read_returns_403_without_messaging_view(app_client_no_view, db_session):
    await _insert_lead(db_session, lead_id=1)
    resp = await app_client_no_view.post("/api/v1/leads/1/messages/mark-read")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_mark_read_idempotent_second_call_returns_zero(app_client, db_session):
    """1 回目で全部既読 → 2 回目は marked_count=0。"""
    await _insert_lead(db_session, lead_id=1)
    await _insert_message(db_session, lead_id=1, direction="inbound", message_text="m1")

    resp1 = await app_client.post("/api/v1/leads/1/messages/mark-read")
    assert resp1.json()["marked_count"] == 1
    resp2 = await app_client.post("/api/v1/leads/1/messages/mark-read")
    assert resp2.json()["marked_count"] == 0


@pytest.mark.asyncio
async def test_mark_read_resolves_seen_by_staff_id_when_present(app_client, db_session):
    """user.email が staff にあれば seen_by_staff_id にセット。"""
    await db_session.execute(text("""
        INSERT INTO staff (id, tenant_id, primary_email)
        VALUES (5, 999, 'tester@example.com')
    """))
    await db_session.commit()
    await _insert_lead(db_session, lead_id=1)
    await _insert_message(db_session, lead_id=1, direction="inbound", message_text="m1")

    resp = await app_client.post("/api/v1/leads/1/messages/mark-read")
    assert resp.json()["marked_count"] == 1

    res = await db_session.execute(text(
        "SELECT seen_by_staff_id FROM meta_messages WHERE lead_id = 1"
    ))
    row = res.first()
    assert row[0] == 5


@pytest.mark.asyncio
async def test_mark_read_does_nothing_when_no_inbound_messages(app_client, db_session):
    """outbound のみの会話なら marked_count=0。"""
    await _insert_lead(db_session, lead_id=1)
    await _insert_message(db_session, lead_id=1, direction="outbound", message_text="m1")

    resp = await app_client.post("/api/v1/leads/1/messages/mark-read")
    assert resp.json()["marked_count"] == 0
