"""
POST /api/v1/leads/{lead_id}/messages/image の統合テスト（Sprint 2）。

カバー:
- 無効 MIME タイプ → 400
- ファイルサイズ超過 → 400
- lead 不在 → 404
- tenant_meta_config 未接続 → 409
- messaging window 超過 → 400
- upload_attachment API エラー → 502
- 送信成功 → 201 + meta_messages に attachment_type='image'
- Discord lead → 400（未サポート）

実行:
    pytest backend/tests/test_message_image_send.py -v
"""

from __future__ import annotations

import os
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

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
from app.services.meta_graph import MetaGraphAPIError


_ALL_PERMS = {"channels.view", "channels.manage", "messaging.view", "messaging.send"}

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
        per_order_amount NUMERIC(15,2),
        monthly_frequency NUMERIC(10,2),
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
        discord_role_sync_at TIMESTAMP WITH TIME ZONE,
        discord_guild_channel_id VARCHAR(50)
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
        attachment_url TEXT,
        attachment_type VARCHAR(20),
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
        tenant_id INTEGER NOT NULL,
        primary_email VARCHAR(255),
        surname_jp VARCHAR(100),
        given_name_jp VARCHAR(100)
    )
"""


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    @event.listens_for(eng.sync_engine, "connect")
    def set_pragma(dbapi_conn, _):
        dbapi_conn.create_function("NOW", 0, lambda: "2026-06-01 00:00:00+00:00")
        dbapi_conn.execute("PRAGMA journal_mode=WAL")
        dbapi_conn.execute("PRAGMA foreign_keys=OFF")

    async with eng.begin() as conn:
        for ddl in [_LEAD_DDL, _META_MESSAGES_DDL, _TENANT_META_CONFIG_DDL, _STAFF_DDL]:
            await conn.execute(text(ddl))

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
    yield Fernet(key.encode("ascii"))
    encryption.reset_cache()


def _mock_user(email: str = "tester@example.com"):
    u = MagicMock()
    u.id = 1
    u.tenant_id = 999
    u.email = email
    return u


def _build_app(db_session, tenant_id: int = 999):
    app = FastAPI()

    async def override_db():
        yield db_session

    async def override_user():
        return _mock_user()

    async def override_tenant():
        return tenant_id

    app.include_router(leads_router.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_current_tenant] = override_tenant
    return app


@pytest_asyncio.fixture
async def app_client(db_session, fernet_env):
    app = _build_app(db_session)
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
        stack.enter_context(patch(
            "app.routers.leads.record_audit_log",
            new=AsyncMock(return_value=None),
        ))
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac, db_session, fernet_env
    app.dependency_overrides.clear()


def _make_image_bytes() -> bytes:
    return b"\xff\xd8\xff\xe0" + b"\x00" * 100


async def _insert_inbound(db, tenant_id: int, lead_id: int, platform: str, delta_hours: float = -1.0):
    ts = (datetime.now(timezone.utc) + timedelta(hours=delta_hours)).isoformat()
    await db.execute(
        text("""
            INSERT INTO meta_messages
                (tenant_id, lead_id, platform, sender_id, message_text, direction, created_at)
            VALUES (:tid, :lid, :platform, 'psid_1', 'hello', 'inbound', :ts)
        """),
        {"tid": tenant_id, "lid": lead_id, "platform": platform, "ts": ts},
    )
    await db.commit()


async def _insert_config(db, tenant_id: int, page_id: str, fernet: Fernet, ig_id: str | None = None):
    token_enc = fernet.encrypt(b"fake_page_token")
    await db.execute(
        text("""
            INSERT INTO tenant_meta_config
                (tenant_id, page_id, page_name, page_access_token_encrypted,
                 instagram_business_account_id, is_active)
            VALUES (:tid, :pid, 'Test Page', :tok, :ig_id, 1)
        """),
        {"tid": tenant_id, "pid": page_id, "tok": token_enc, "ig_id": ig_id},
    )
    await db.commit()


# ---------------------------------------------------------------------------
# テスト
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_mime_type_returns_400(app_client):
    ac, db, _ = app_client
    await db.execute(
        text("INSERT INTO leads (id, tenant_id, source, customer_name) VALUES (1, 999, 'messenger:psid_1', 'Test')"),
    )
    await db.commit()
    resp = await ac.post(
        "/api/v1/leads/1/messages/image",
        files={"image": ("test.txt", b"not an image", "text/plain")},
    )
    assert resp.status_code == 400, resp.text
    assert "サポートされていない" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_file_too_large_returns_400(app_client):
    ac, db, _ = app_client
    await db.execute(
        text("INSERT INTO leads (id, tenant_id, source, customer_name) VALUES (1, 999, 'messenger:psid_1', 'Test')"),
    )
    await db.commit()
    big = b"\xff\xd8\xff\xe0" + b"x" * (9 * 1024 * 1024)
    resp = await ac.post(
        "/api/v1/leads/1/messages/image",
        files={"image": ("big.jpg", big, "image/jpeg")},
    )
    assert resp.status_code == 400, resp.text
    assert "8MB" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_lead_not_found_returns_404(app_client):
    ac, db, _ = app_client
    resp = await ac.post(
        "/api/v1/leads/9999/messages/image",
        files={"image": ("img.png", _make_image_bytes(), "image/png")},
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_discord_platform_returns_400(app_client):
    ac, db, fernet = app_client
    await db.execute(
        text("INSERT INTO leads (id, tenant_id, source, customer_name) VALUES (1, 999, 'discord:user_1', 'Test')"),
    )
    await _insert_inbound(db, 999, 1, "discord")
    resp = await ac.post(
        "/api/v1/leads/1/messages/image",
        files={"image": ("img.jpeg", _make_image_bytes(), "image/jpeg")},
    )
    assert resp.status_code == 400, resp.text
    assert "Discord" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_no_meta_config_returns_409(app_client):
    ac, db, _ = app_client
    await db.execute(
        text("INSERT INTO leads (id, tenant_id, source, customer_name) VALUES (1, 999, 'messenger:psid_1', 'Test')"),
    )
    await _insert_inbound(db, 999, 1, "messenger")
    resp = await ac.post(
        "/api/v1/leads/1/messages/image",
        files={"image": ("img.jpeg", _make_image_bytes(), "image/jpeg")},
    )
    assert resp.status_code == 409, resp.text


@pytest.mark.asyncio
async def test_messaging_window_expired_returns_400(app_client):
    ac, db, fernet = app_client
    await db.execute(
        text("INSERT INTO leads (id, tenant_id, source, customer_name) VALUES (1, 999, 'messenger:psid_1', 'Test')"),
    )
    await _insert_inbound(db, 999, 1, "messenger", delta_hours=-(8 * 24))
    await _insert_config(db, 999, "page_1", fernet)
    resp = await ac.post(
        "/api/v1/leads/1/messages/image",
        files={"image": ("img.jpeg", _make_image_bytes(), "image/jpeg")},
    )
    assert resp.status_code == 400, resp.text
    assert "ウィンドウ" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_upload_api_error_returns_502(app_client):
    ac, db, fernet = app_client
    await db.execute(
        text("INSERT INTO leads (id, tenant_id, source, customer_name) VALUES (1, 999, 'messenger:psid_1', 'Test')"),
    )
    await _insert_inbound(db, 999, 1, "messenger")
    await _insert_config(db, 999, "page_1", fernet)

    with patch("app.services.meta_graph.upload_attachment", new_callable=AsyncMock) as mock_upload:
        mock_upload.side_effect = MetaGraphAPIError("upload error", status_code=400, error_code=100)
        resp = await ac.post(
            "/api/v1/leads/1/messages/image",
            files={"image": ("img.jpeg", _make_image_bytes(), "image/jpeg")},
        )
    assert resp.status_code == 502, resp.text


@pytest.mark.asyncio
async def test_success_inserts_outbound_row(app_client):
    ac, db, fernet = app_client
    await db.execute(
        text("INSERT INTO leads (id, tenant_id, source, customer_name) VALUES (1, 999, 'messenger:psid_1', 'Test')"),
    )
    await _insert_inbound(db, 999, 1, "messenger")
    await _insert_config(db, 999, "page_1", fernet)

    with (
        patch("app.services.meta_graph.upload_attachment", new_callable=AsyncMock) as mock_upload,
        patch("app.services.meta_graph.send_messenger_attachment", new_callable=AsyncMock) as mock_send,
    ):
        mock_upload.return_value = "att_123"
        mock_send.return_value = {"recipient_id": "psid_1", "message_id": "mid_abc"}

        resp = await ac.post(
            "/api/v1/leads/1/messages/image",
            files={"image": ("photo.jpeg", _make_image_bytes(), "image/jpeg")},
        )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["attachment_type"] == "image"
    assert body["platform"] == "messenger"
    assert body["message_id"] == "mid_abc"

    row = await db.execute(
        text("SELECT direction, attachment_type, message_id FROM meta_messages WHERE lead_id=1 AND direction='outbound'")
    )
    out_row = row.first()
    assert out_row is not None
    assert out_row[1] == "image"
    assert out_row[2] == "mid_abc"
