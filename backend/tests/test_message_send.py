"""
backend/app/routers/leads.py の `POST /api/v1/leads/{lead_id}/messages`
の統合テスト（Phase 1-D Sprint 5、spec §5-5 / §3-3 / §9-1）。

`test_messages.py` と同じ最小 FastAPI app + SQLite + dependency override
パターン。Meta Graph API は `app.services.meta_graph.send_messenger_message` /
`send_instagram_message` を `unittest.mock.patch` で差し替え。

カバー:
- 認証 / 認可: 401 不要（dependency override 済）、403 (messaging.send 不足)
- 入力 validation: text 空 / 長すぎ
- lead 不在 / 別テナント lead → 404
- tenant_meta_config 未接続 → 409
- 24h 以内 → messaging_type='RESPONSE', tag=NULL
- 24h-7d → messaging_type='MESSAGE_TAG', tag='HUMAN_AGENT'
- 7d 超 → 400（Send API 呼ばない、DB 書かない）
- 受信履歴なし → 400（同上）
- force_human_agent_tag=true で 24h 以内でも HUMAN_AGENT
- Messenger / Instagram 両方
- Send API 例外 → 502 + meta_messages に書かない
- 送信成功 → meta_messages に outbound 1 件 INSERT、recipient_id / messaging_type /
  message_tag / sent_by_staff_id / message_id がセット済

実行:
    pytest backend/tests/test_message_send.py -v
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
from cryptography.fernet import Fernet
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.auth.dependencies import get_current_tenant, get_current_user
from app.database import get_db
from app.routers import leads as leads_router
from app.services import encryption
from app.services.meta_graph import MetaGraphAPIError, MetaGraphTransportError


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


_ALL_PERMS = {"channels.view", "channels.manage", "messaging.view", "messaging.send"}
_NO_SEND_PERMS = {"messaging.view"}  # send だけ欠落


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
        nickname VARCHAR(255)
    )
"""

_META_MESSAGES_DDL = """
    CREATE TABLE meta_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_id INTEGER NOT NULL,
        lead_id INTEGER,
        platform VARCHAR(20) NOT NULL DEFAULT 'messenger',
        sender_id VARCHAR(100),
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
        page_id VARCHAR(50),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
"""

_TENANT_META_CONFIG_DDL = """
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
        dbapi_conn.create_function("NOW", 0, lambda: datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S+00:00"))
        dbapi_conn.execute("PRAGMA foreign_keys = ON")

    async with eng.begin() as conn:
        await conn.execute(text(_LEAD_DDL))
        await conn.execute(text(_META_MESSAGES_DDL))
        await conn.execute(text(_TENANT_META_CONFIG_DDL))
        await conn.execute(text(_STAFF_DDL))

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
    yield
    encryption.reset_cache()


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
async def app_client(db_session, fernet_env):
    app = _build_app(db_session, tenant_id=999)
    transport = ASGITransport(app=app)
    with ExitStack() as stack:
        stack.enter_context(patch(
            "app.auth.dependencies.load_user_permissions",
            new=AsyncMock(return_value=_ALL_PERMS),
        ))
        stack.enter_context(patch(
            "app.routers.leads.invalidate_dashboard_cache",
            new=AsyncMock(return_value=None),
        ))
        # audit_log は SQLite で `tenant_NNN.audit_logs` を解釈できないため no-op
        stack.enter_context(patch(
            "app.routers.leads.record_audit_log",
            new=AsyncMock(return_value=None),
        ))
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def app_client_no_send(db_session, fernet_env):
    app = _build_app(db_session, tenant_id=999)
    transport = ASGITransport(app=app)
    with ExitStack() as stack:
        stack.enter_context(patch(
            "app.auth.dependencies.load_user_permissions",
            new=AsyncMock(return_value=_NO_SEND_PERMS),
        ))
        stack.enter_context(patch(
            "app.routers.leads.invalidate_dashboard_cache",
            new=AsyncMock(return_value=None),
        ))
        stack.enter_context(patch(
            "app.routers.leads.record_audit_log",
            new=AsyncMock(return_value=None),
        ))
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _insert_lead(
    db_session, *, lead_id: int, tenant_id: int = 999,
    customer_name: str = "Alice", source: str | None = "messenger:PSID-1",
):
    await db_session.execute(text("""
        INSERT INTO leads (id, tenant_id, lead_code, customer_name, source, status)
        VALUES (:id, :tenant_id, :code, :name, :source, '新規')
    """), {
        "id": lead_id, "tenant_id": tenant_id,
        "code": f"LD-{lead_id:05d}", "name": customer_name, "source": source,
    })
    await db_session.commit()


async def _insert_inbound(
    db_session, *, lead_id: int, tenant_id: int = 999,
    platform: str = "messenger", sender_id: str = "PSID-1",
    minutes_ago: int = 60, message_text: str = "Hi",
):
    when = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    await db_session.execute(text("""
        INSERT INTO meta_messages
            (tenant_id, lead_id, platform, sender_id, message_text, direction, created_at)
        VALUES
            (:tenant_id, :lead_id, :platform, :sender_id, :text, 'inbound', :when)
    """), {
        "tenant_id": tenant_id, "lead_id": lead_id,
        "platform": platform, "sender_id": sender_id,
        "text": message_text,
        "when": when.strftime("%Y-%m-%d %H:%M:%S+00:00"),
    })
    await db_session.commit()


async def _insert_inbound_at(
    db_session, *, lead_id: int, tenant_id: int = 999,
    when: datetime, platform: str = "messenger", sender_id: str = "PSID-1",
):
    await db_session.execute(text("""
        INSERT INTO meta_messages
            (tenant_id, lead_id, platform, sender_id, message_text, direction, created_at)
        VALUES
            (:tenant_id, :lead_id, :platform, :sender_id, 'X', 'inbound', :when)
    """), {
        "tenant_id": tenant_id, "lead_id": lead_id,
        "platform": platform, "sender_id": sender_id,
        "when": when.strftime("%Y-%m-%d %H:%M:%S+00:00"),
    })
    await db_session.commit()


async def _insert_tenant_meta_config(
    db_session, *, tenant_id: int = 999,
    page_id: str = "page-1", ig_business_account_id: str | None = None,
):
    encrypted = encryption.encrypt("page-token-plain")
    await db_session.execute(text("""
        INSERT INTO tenant_meta_config
            (tenant_id, page_id, page_name, page_access_token_encrypted,
             instagram_business_account_id, is_active, connected_at)
        VALUES
            (:tenant_id, :page_id, :name, :token, :ig, 1, :now)
    """), {
        "tenant_id": tenant_id, "page_id": page_id,
        "name": "Highlife JPN", "token": encrypted.encode("ascii"),
        "ig": ig_business_account_id,
        "now": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S+00:00"),
    })
    await db_session.commit()


async def _count_outbound(db_session, *, lead_id: int, tenant_id: int = 999) -> int:
    res = await db_session.execute(text(
        "SELECT COUNT(*) FROM meta_messages "
        "WHERE lead_id = :lead AND tenant_id = :tid AND direction = 'outbound'"
    ), {"lead": lead_id, "tid": tenant_id})
    return int(res.scalar() or 0)


# ---------------------------------------------------------------------------
# 認可
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_returns_403_without_messaging_send(app_client_no_send, db_session):
    await _insert_lead(db_session, lead_id=1)
    resp = await app_client_no_send.post(
        "/api/v1/leads/1/messages", json={"text": "hi"}
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# 入力 validation / lead 検証
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_returns_404_when_lead_missing(app_client):
    resp = await app_client.post("/api/v1/leads/9999/messages", json={"text": "hi"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_send_returns_404_when_lead_in_other_tenant(app_client, db_session):
    await _insert_lead(db_session, lead_id=1, tenant_id=888)
    resp = await app_client.post("/api/v1/leads/1/messages", json={"text": "hi"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_send_returns_422_when_text_empty(app_client, db_session):
    """Pydantic min_length=1 で 422（FastAPI 既定）。"""
    await _insert_lead(db_session, lead_id=1)
    resp = await app_client.post("/api/v1/leads/1/messages", json={"text": ""})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_send_returns_400_when_text_only_whitespace(app_client, db_session):
    """Pydantic は通すが strip 後空 → 400 を投げる。"""
    await _insert_lead(db_session, lead_id=1)
    await _insert_inbound(db_session, lead_id=1, minutes_ago=60)
    await _insert_tenant_meta_config(db_session)
    resp = await app_client.post("/api/v1/leads/1/messages", json={"text": "   "})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_send_returns_422_when_text_too_long(app_client, db_session):
    await _insert_lead(db_session, lead_id=1)
    long_text = "a" * 2001
    resp = await app_client.post("/api/v1/leads/1/messages", json={"text": long_text})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# tenant_meta_config 未接続 → 409
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_returns_409_when_no_meta_connection(app_client, db_session):
    await _insert_lead(db_session, lead_id=1)
    await _insert_inbound(db_session, lead_id=1, minutes_ago=60)
    # tenant_meta_config に行を入れない
    resp = await app_client.post("/api/v1/leads/1/messages", json={"text": "hi"})
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# 24h ルール
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_within_24h_uses_response_messaging_type(app_client, db_session):
    await _insert_lead(db_session, lead_id=1)
    await _insert_inbound(db_session, lead_id=1, minutes_ago=60)  # 1h ago
    await _insert_tenant_meta_config(db_session)

    captured = {}

    async def fake_send(**kwargs):
        captured.update(kwargs)
        return {"recipient_id": kwargs["recipient_id"], "message_id": "mid-001"}

    with patch("app.routers.leads.meta_graph.send_messenger_message",
               new=AsyncMock(side_effect=fake_send)) as mocked:
        resp = await app_client.post(
            "/api/v1/leads/1/messages", json={"text": "ありがとう"}
        )

    assert resp.status_code == 201
    body = resp.json()
    # HUMAN_AGENT auto-apply 仕様 (dac01e3) に追随:
    # 24h 以内でも messaging_type=MESSAGE_TAG / message_tag=HUMAN_AGENT を返す
    assert body["messaging_type"] == "MESSAGE_TAG"
    assert body["message_tag"] == "HUMAN_AGENT"
    assert body["message_id"] == "mid-001"
    # Send API に正しい引数が渡る
    assert mocked.await_count == 1
    assert captured["messaging_type"] == "MESSAGE_TAG"
    assert captured["tag"] == "HUMAN_AGENT"
    assert captured["text"] == "ありがとう"
    assert captured["recipient_id"] == "PSID-1"


@pytest.mark.asyncio
async def test_send_24h_to_7d_uses_message_tag_human_agent(app_client, db_session):
    await _insert_lead(db_session, lead_id=1)
    # 3 日前
    when = datetime.now(timezone.utc) - timedelta(days=3)
    await _insert_inbound_at(db_session, lead_id=1, when=when)
    await _insert_tenant_meta_config(db_session)

    captured = {}

    async def fake_send(**kwargs):
        captured.update(kwargs)
        return {"recipient_id": kwargs["recipient_id"], "message_id": "mid-002"}

    with patch("app.routers.leads.meta_graph.send_messenger_message",
               new=AsyncMock(side_effect=fake_send)):
        resp = await app_client.post("/api/v1/leads/1/messages", json={"text": "再連絡"})

    assert resp.status_code == 201
    body = resp.json()
    assert body["messaging_type"] == "MESSAGE_TAG"
    assert body["message_tag"] == "HUMAN_AGENT"
    assert captured["tag"] == "HUMAN_AGENT"


@pytest.mark.asyncio
async def test_send_beyond_7d_returns_400_and_does_not_call_send_api(app_client, db_session):
    await _insert_lead(db_session, lead_id=1)
    when = datetime.now(timezone.utc) - timedelta(days=8)
    await _insert_inbound_at(db_session, lead_id=1, when=when)
    await _insert_tenant_meta_config(db_session)

    with patch("app.routers.leads.meta_graph.send_messenger_message",
               new=AsyncMock()) as mocked:
        resp = await app_client.post("/api/v1/leads/1/messages", json={"text": "test"})

    assert resp.status_code == 400
    assert mocked.await_count == 0
    assert await _count_outbound(db_session, lead_id=1) == 0


@pytest.mark.asyncio
async def test_send_no_inbound_history_returns_400(app_client, db_session):
    """inbound 履歴 0 件 → 送信不可（最初は顧客側からの仕様）。"""
    await _insert_lead(db_session, lead_id=1, source="messenger:PSID-X")
    await _insert_tenant_meta_config(db_session)

    with patch("app.routers.leads.meta_graph.send_messenger_message",
               new=AsyncMock()) as mocked:
        resp = await app_client.post("/api/v1/leads/1/messages", json={"text": "test"})

    assert resp.status_code == 400
    assert mocked.await_count == 0


# ---------------------------------------------------------------------------
# force_human_agent_tag override
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_force_human_agent_within_24h_uses_message_tag(app_client, db_session):
    await _insert_lead(db_session, lead_id=1)
    await _insert_inbound(db_session, lead_id=1, minutes_ago=60)
    await _insert_tenant_meta_config(db_session)

    captured = {}

    async def fake_send(**kwargs):
        captured.update(kwargs)
        return {"recipient_id": kwargs["recipient_id"], "message_id": "mid-003"}

    with patch("app.routers.leads.meta_graph.send_messenger_message",
               new=AsyncMock(side_effect=fake_send)):
        resp = await app_client.post(
            "/api/v1/leads/1/messages",
            json={"text": "force", "force_human_agent_tag": True},
        )

    assert resp.status_code == 201
    body = resp.json()
    assert body["messaging_type"] == "MESSAGE_TAG"
    assert body["message_tag"] == "HUMAN_AGENT"
    assert captured["messaging_type"] == "MESSAGE_TAG"


# ---------------------------------------------------------------------------
# Instagram
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_instagram_calls_instagram_send_api(app_client, db_session):
    await _insert_lead(db_session, lead_id=1, source="instagram:IGSID-1")
    await _insert_inbound(db_session, lead_id=1, platform="instagram",
                          sender_id="IGSID-1", minutes_ago=30)
    await _insert_tenant_meta_config(db_session, ig_business_account_id="ig-biz-1")

    captured = {}

    async def fake_send(**kwargs):
        captured.update(kwargs)
        return {"recipient_id": kwargs["recipient_id"], "message_id": "ig-mid-001"}

    with patch("app.routers.leads.meta_graph.send_instagram_message",
               new=AsyncMock(side_effect=fake_send)) as mocked_ig, \
         patch("app.routers.leads.meta_graph.send_messenger_message",
               new=AsyncMock()) as mocked_msg:
        resp = await app_client.post("/api/v1/leads/1/messages", json={"text": "DM"})

    assert resp.status_code == 201
    body = resp.json()
    assert body["platform"] == "instagram"
    assert body["message_id"] == "ig-mid-001"
    assert captured["page_id"] == "page-1"
    assert captured["recipient_id"] == "IGSID-1"
    assert mocked_ig.await_count == 1
    assert mocked_msg.await_count == 0


@pytest.mark.asyncio
async def test_send_instagram_returns_409_when_no_ig_business_id(app_client, db_session):
    """tenant_meta_config に IG 接続情報がない場合は 409。"""
    await _insert_lead(db_session, lead_id=1, source="instagram:IGSID-1")
    await _insert_inbound(db_session, lead_id=1, platform="instagram",
                          sender_id="IGSID-1", minutes_ago=30)
    # ig_business_account_id を NULL のまま登録
    await _insert_tenant_meta_config(db_session, ig_business_account_id=None)

    resp = await app_client.post("/api/v1/leads/1/messages", json={"text": "DM"})
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Send API エラー
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_returns_502_when_meta_api_error(app_client, db_session):
    await _insert_lead(db_session, lead_id=1)
    await _insert_inbound(db_session, lead_id=1, minutes_ago=60)
    await _insert_tenant_meta_config(db_session)

    err = MetaGraphAPIError(
        "Permissions error",
        status_code=400, error_type="OAuthException",
        error_code=10, error_subcode=2018278,
    )
    with patch("app.routers.leads.meta_graph.send_messenger_message",
               new=AsyncMock(side_effect=err)):
        resp = await app_client.post("/api/v1/leads/1/messages", json={"text": "x"})

    assert resp.status_code == 502
    body = resp.json()
    detail = body["detail"]
    # detail が dict
    assert isinstance(detail, dict)
    assert detail.get("error_code") == 10
    assert detail.get("error_type") == "OAuthException"
    # 失敗時は meta_messages に書かない
    assert await _count_outbound(db_session, lead_id=1) == 0


@pytest.mark.asyncio
async def test_send_returns_502_when_meta_transport_error(app_client, db_session):
    await _insert_lead(db_session, lead_id=1)
    await _insert_inbound(db_session, lead_id=1, minutes_ago=60)
    await _insert_tenant_meta_config(db_session)

    err = MetaGraphTransportError("network failed")
    with patch("app.routers.leads.meta_graph.send_messenger_message",
               new=AsyncMock(side_effect=err)):
        resp = await app_client.post("/api/v1/leads/1/messages", json={"text": "x"})

    assert resp.status_code == 502
    assert await _count_outbound(db_session, lead_id=1) == 0


# ---------------------------------------------------------------------------
# 送信成功時の DB 書き込み + sent_by_staff_id 解決
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_success_inserts_outbound_meta_message(app_client, db_session):
    await _insert_lead(db_session, lead_id=1)
    await _insert_inbound(db_session, lead_id=1, minutes_ago=60)
    await _insert_tenant_meta_config(db_session, page_id="page-1")

    async def fake_send(**kwargs):
        return {"recipient_id": kwargs["recipient_id"], "message_id": "mid-success"}

    with patch("app.routers.leads.meta_graph.send_messenger_message",
               new=AsyncMock(side_effect=fake_send)):
        resp = await app_client.post(
            "/api/v1/leads/1/messages", json={"text": "Hello"}
        )
    assert resp.status_code == 201

    # outbound 1 件、各列が埋まっていること
    res = await db_session.execute(text("""
        SELECT direction, message_text, recipient_id, messaging_type,
               message_tag, message_id, platform, sender_id, page_id
        FROM meta_messages
        WHERE lead_id = 1 AND direction = 'outbound'
    """))
    row = res.first()
    assert row is not None
    direction, message_text, recipient_id, messaging_type, message_tag, message_id, platform, sender_id, page_id = row
    assert direction == "outbound"
    assert message_text == "Hello"
    assert recipient_id == "PSID-1"
    # HUMAN_AGENT auto-apply 仕様 (dac01e3) に追随:
    # window 内は常に MESSAGE_TAG / HUMAN_AGENT で書き込む
    assert messaging_type == "MESSAGE_TAG"
    assert message_tag == "HUMAN_AGENT"
    assert message_id == "mid-success"
    assert platform == "messenger"
    assert sender_id == "page-1"
    # Phase 1-E F14-S5: outbound Messenger も page_id を埋める（Page フィルタの一貫性）
    assert page_id == "page-1"


@pytest.mark.asyncio
async def test_send_success_resolves_sent_by_staff_id(app_client, db_session):
    """user.email → staff.id を解決してセット。"""
    await db_session.execute(text(
        "INSERT INTO staff (id, tenant_id, primary_email) "
        "VALUES (7, 999, 'tester@example.com')"
    ))
    await db_session.commit()
    await _insert_lead(db_session, lead_id=1)
    await _insert_inbound(db_session, lead_id=1, minutes_ago=60)
    await _insert_tenant_meta_config(db_session)

    async def fake_send(**kwargs):
        return {"recipient_id": kwargs["recipient_id"], "message_id": "mid-staff"}

    with patch("app.routers.leads.meta_graph.send_messenger_message",
               new=AsyncMock(side_effect=fake_send)):
        resp = await app_client.post("/api/v1/leads/1/messages", json={"text": "x"})
    assert resp.status_code == 201

    res = await db_session.execute(text(
        "SELECT sent_by_staff_id FROM meta_messages "
        "WHERE lead_id = 1 AND direction = 'outbound'"
    ))
    assert res.first()[0] == 7


# ---------------------------------------------------------------------------
# tenant 分離（meta_config も別テナント）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_uses_only_own_tenant_meta_config(app_client, db_session):
    """別テナントの tenant_meta_config は使わない（同 tenant の行が無いと 409）。"""
    await _insert_lead(db_session, lead_id=1, tenant_id=999)
    await _insert_inbound(db_session, lead_id=1, tenant_id=999, minutes_ago=60)
    # 別テナント（tenant_id=888）の meta_config だけ存在
    await _insert_tenant_meta_config(db_session, tenant_id=888, page_id="other-page")

    resp = await app_client.post("/api/v1/leads/1/messages", json={"text": "x"})
    assert resp.status_code == 409
