"""
Discord DM 受信箱連携のテスト群（ガバナンス必須テスト）。

カバー:
- discord_sender.send_discord_dm: 成功・DiscordSendError・Token未設定 (httpx mock)
- POST /leads/{id}/messages Discord パス:
    - 409 (discord_dm_channel_id 未設定)
    - 502 (Discord API エラー)
    - 201 成功 + outbound meta_message INSERT
- GET /leads/{id}/messages Discord: messaging_window.can_send_at_all=True
- dm_writer.upsert_lead_and_message: 新規 lead 作成・idempotent (AsyncMock ベース)

FastAPI テストは SQLite in-memory + dependency override（test_message_send.py パターン）。
dm_writer テストは AsyncMock でセッションを模倣（schema 修飾 SQL は SQLite 非対応のため）。

実行:
    pytest backend/tests/test_discord_inbox.py -v
"""
from __future__ import annotations

import os
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.auth.dependencies import get_current_tenant, get_current_user
from app.database import get_db
from app.routers import leads as leads_router
from app.services.discord_sender import DiscordSendError, send_discord_dm


# ---------------------------------------------------------------------------
# DDL (SQLite in-memory)
# ---------------------------------------------------------------------------

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
        messenger_link VARCHAR(255),
        discord_id VARCHAR(255),
        instagram_link VARCHAR(255),
        whatsapp_link VARCHAR(255),
        discord_user_id VARCHAR(50),
        discord_dm_channel_id VARCHAR(50)
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

_STAFF_DDL = """
    CREATE TABLE staff (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_id INTEGER NOT NULL DEFAULT 999,
        primary_email VARCHAR(255) NOT NULL
    )
"""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    @event.listens_for(eng.sync_engine, "connect")
    def _setup(dbapi_conn, _):
        dbapi_conn.create_function(
            "NOW", 0,
            lambda: datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S+00:00"),
        )
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


_ALL_PERMS = {"channels.view", "channels.manage", "messaging.view", "messaging.send"}


@pytest_asyncio.fixture
async def app_client(db_session):
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


async def _insert_discord_lead(
    db_session,
    *,
    lead_id: int,
    tenant_id: int = 999,
    discord_user_id: str = "USER123",
    discord_dm_channel_id: str | None = "DM-CH-123",
    source: str = "discord:USER123",
):
    await db_session.execute(text("""
        INSERT INTO leads
            (id, tenant_id, lead_code, customer_name, source, type, status,
             discord_user_id, discord_dm_channel_id)
        VALUES
            (:id, :tenant_id, :code, 'Discord Customer', :source, 'prospect', '新規',
             :discord_user_id, :discord_dm_channel_id)
    """), {
        "id": lead_id,
        "tenant_id": tenant_id,
        "code": f"LD-{lead_id:05d}",
        "source": source,
        "discord_user_id": discord_user_id,
        "discord_dm_channel_id": discord_dm_channel_id,
    })
    await db_session.commit()


async def _insert_discord_inbound(
    db_session,
    *,
    lead_id: int,
    tenant_id: int = 999,
    sender_id: str = "USER123",
    minutes_ago: int = 30,
):
    when = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    await db_session.execute(text("""
        INSERT INTO meta_messages
            (tenant_id, lead_id, platform, sender_id, message_text, direction, created_at)
        VALUES
            (:tenant_id, :lead_id, 'discord', :sender_id, 'こんにちは', 'inbound', :when)
    """), {
        "tenant_id": tenant_id,
        "lead_id": lead_id,
        "sender_id": sender_id,
        "when": when.strftime("%Y-%m-%d %H:%M:%S+00:00"),
    })
    await db_session.commit()


async def _count_outbound(db_session, *, lead_id: int, tenant_id: int = 999) -> int:
    res = await db_session.execute(text(
        "SELECT COUNT(*) FROM meta_messages "
        "WHERE lead_id = :lead AND tenant_id = :tid AND direction = 'outbound'"
    ), {"lead": lead_id, "tid": tenant_id})
    return int(res.scalar() or 0)


# ---------------------------------------------------------------------------
# discord_sender.send_discord_dm: httpx mock テスト
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_discord_dm_success(monkeypatch):
    """送信成功時に Discord メッセージ ID を返す。"""
    monkeypatch.setenv("DISCORD_BOT_TOKEN_4", "Bot-token-test")

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"id": "discord-msg-001"}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    with patch("app.services.discord_sender.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await send_discord_dm(
            tenant_id=4,
            dm_channel_id="ch-123",
            text="テスト送信",
        )

    assert result == "discord-msg-001"
    mock_client.post.assert_awaited_once()
    call_kwargs = mock_client.post.await_args
    assert "Bot Bot-token-test" in str(call_kwargs)


@pytest.mark.asyncio
async def test_send_discord_dm_raises_on_non_200(monkeypatch):
    """Discord API が非 2xx を返した場合は DiscordSendError を送出する。"""
    monkeypatch.setenv("DISCORD_BOT_TOKEN_4", "Bot-token-test")

    mock_response = MagicMock()
    mock_response.status_code = 403
    mock_response.text = '{"message": "Missing Permissions"}'

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    with patch("app.services.discord_sender.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with pytest.raises(DiscordSendError, match="403"):
            await send_discord_dm(
                tenant_id=4,
                dm_channel_id="ch-123",
                text="テスト送信",
            )


@pytest.mark.asyncio
async def test_send_discord_dm_raises_when_token_missing(monkeypatch):
    """Bot Token が未設定の場合は DiscordSendError を送出する（API 呼び出しなし）。"""
    monkeypatch.delenv("DISCORD_BOT_TOKEN_4", raising=False)

    with pytest.raises(DiscordSendError, match="DISCORD_BOT_TOKEN_4"):
        await send_discord_dm(
            tenant_id=4,
            dm_channel_id="ch-123",
            text="テスト送信",
        )


# ---------------------------------------------------------------------------
# POST /leads/{id}/messages Discord パス（FastAPI + SQLite）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_discord_returns_409_when_no_dm_channel(app_client, db_session):
    """discord_dm_channel_id が未設定の lead に送信 → 409。

    顧客からのDM受信前は dm_channel_id が NULL のため、送信経路が開けない。
    local import された send_discord_dm は 409 到達前に呼ばれないため、patch 不要。
    """
    await _insert_discord_lead(
        db_session, lead_id=1,
        discord_dm_channel_id=None,  # 未設定
    )

    resp = await app_client.post(
        "/api/v1/leads/1/messages", json={"text": "Hello"}
    )

    assert resp.status_code == 409
    assert "チャンネル" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_send_discord_returns_502_on_discord_send_error(app_client, db_session):
    """Discord API 送信失敗 → 502。meta_messages には書き込まない。

    _send_discord_message 内の local import を介してパッチ:
    `app.services.discord_sender.send_discord_dm` を差し替える。
    """
    await _insert_discord_lead(db_session, lead_id=1)

    with patch(
        "app.services.discord_sender.send_discord_dm",
        new=AsyncMock(side_effect=DiscordSendError("Discord API 403")),
    ):
        resp = await app_client.post(
            "/api/v1/leads/1/messages", json={"text": "Hello"}
        )

    assert resp.status_code == 502
    assert await _count_outbound(db_session, lead_id=1) == 0


@pytest.mark.asyncio
async def test_send_discord_success_inserts_outbound_meta_message(app_client, db_session):
    """Discord 送信成功 → outbound meta_message が 1 件 INSERT される。"""
    await _insert_discord_lead(db_session, lead_id=1)

    with patch(
        "app.services.discord_sender.send_discord_dm",
        new=AsyncMock(return_value="discord-msg-success"),
    ):
        resp = await app_client.post(
            "/api/v1/leads/1/messages", json={"text": "こんにちは"}
        )

    assert resp.status_code == 201
    body = resp.json()
    assert body["platform"] == "discord"
    assert body["message_id"] == "discord-msg-success"
    assert body["messaging_type"] is None
    assert body["message_tag"] is None

    # DB に outbound 行が書き込まれていること
    assert await _count_outbound(db_session, lead_id=1) == 1

    res = await db_session.execute(text("""
        SELECT platform, message_text, recipient_id, message_id, direction
        FROM meta_messages WHERE lead_id = 1 AND direction = 'outbound'
    """))
    row = res.first()
    assert row is not None
    platform, message_text, recipient_id, message_id, direction = row
    assert platform == "discord"
    assert message_text == "こんにちは"
    assert recipient_id == "USER123"
    assert message_id == "discord-msg-success"
    assert direction == "outbound"


# ---------------------------------------------------------------------------
# GET /leads/{id}/messages Discord: can_send_at_all=True
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_messages_discord_messaging_window_can_send(app_client, db_session):
    """Discord リードのメッセージ一覧 → messaging_window.can_send_at_all=True。

    Discord は Meta の 24h 送信制限を持たないため、常に送信可能。
    """
    await _insert_discord_lead(db_session, lead_id=1)
    await _insert_discord_inbound(db_session, lead_id=1)

    resp = await app_client.get("/api/v1/leads/1/messages")

    assert resp.status_code == 200
    body = resp.json()
    mw = body["messaging_window"]
    assert mw["can_send_at_all"] is True
    assert body["lead"]["platform"] == "discord"


# ---------------------------------------------------------------------------
# dm_writer.upsert_lead_and_message: AsyncMock ベーステスト
#
# schema 修飾 SQL（tenant_NNN.leads 等）は SQLite 非対応のため、
# AsyncSession を AsyncMock で代替してロジックを検証する。
# ---------------------------------------------------------------------------


def _mock_result(first_value):
    """db.execute() の戻り値を模倣するモック。"""
    r = MagicMock()
    r.first.return_value = first_value
    return r


@pytest.mark.asyncio
async def test_dm_writer_creates_new_lead():
    """初回 DM 受信 → lead が新規作成され、meta_messages に inbound 行が INSERT される。

    実行シーケンス:
      1. SET search_path
      2. SELECT leads (→ None: 未登録)
      3. INSERT leads RETURNING id (→ 新規 id=1)
      4. UPDATE leads SET discord_dm_channel_id (dm_channel_id が None のため)
      5. INSERT meta_messages RETURNING id (→ id=10)
      6. commit
    """
    from app.discord_gateway.dm_writer import upsert_lead_and_message

    mock_session = AsyncMock()
    mock_session.execute.side_effect = [
        _mock_result(None),     # (1) SET search_path
        _mock_result(None),     # (2) SELECT lead → 未登録
        _mock_result((1,)),     # (3) INSERT lead RETURNING id=1
        _mock_result(None),     # (4) UPDATE discord_dm_channel_id
        _mock_result((10,)),    # (5) INSERT meta_messages RETURNING id=10
    ]

    await upsert_lead_and_message(
        mock_session,
        tenant_id=4,
        discord_user_id="111222333",
        sender_name="テストユーザー",
        dm_channel_id="DM-CH-456",
        message_text="初めてのDM",
        discord_message_id="msg-new-001",
        created_at=datetime.now(timezone.utc),
    )

    # 5回の execute + 1回の commit
    assert mock_session.execute.call_count == 5
    assert mock_session.commit.call_count == 1


@pytest.mark.asyncio
async def test_dm_writer_idempotent_on_duplicate_message_id():
    """同一 discord_message_id で 2 回呼び出し → meta_messages は 1 行のみ（冪等）。

    2 回目の INSERT は ON CONFLICT DO NOTHING で RETURNING None になる。
    lead は既存のため再作成されない。

    実行シーケンス:
      1. SET search_path
      2. SELECT leads (→ 既存 lead: id=5, dm_channel_id='DM-CH-789')
      3. discord_dm_channel_id は設定済みのため UPDATE なし
      4. INSERT meta_messages RETURNING id → None (ON CONFLICT)
      5. commit
    """
    from app.discord_gateway.dm_writer import upsert_lead_and_message

    mock_session = AsyncMock()
    mock_session.execute.side_effect = [
        _mock_result(None),                    # (1) SET search_path
        _mock_result((5, "DM-CH-789")),        # (2) SELECT lead → 既存 (id=5, ch_id あり)
        _mock_result(None),                    # (3) INSERT meta_messages → ON CONFLICT (None)
    ]

    await upsert_lead_and_message(
        mock_session,
        tenant_id=4,
        discord_user_id="111222333",
        sender_name="テストユーザー",
        dm_channel_id="DM-CH-789",
        message_text="重複メッセージ",
        discord_message_id="msg-dup-001",
        created_at=datetime.now(timezone.utc),
    )

    # 3回の execute（UPDATE なし）+ 1回の commit
    assert mock_session.execute.call_count == 3
    assert mock_session.commit.call_count == 1
