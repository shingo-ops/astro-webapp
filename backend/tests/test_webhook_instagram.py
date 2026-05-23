"""
Phase 1-D Sprint 6: Instagram 受信 + tenant_meta_config 連携 + Messenger 既存経路の regression test。

テスト対象:
  - GET  /api/v1/webhook/messenger      hub.challenge 応答（Messenger / Instagram 共用 verify）
  - POST /api/v1/webhook/messenger      Messenger / Instagram 双方の受信
  - app.routers.webhook._get_tenant_id_by_page
  - app.routers.webhook._get_tenant_id_by_ig_account
  - app.routers.webhook._iter_inbound_messages
  - app.routers.webhook._persist_meta_message
  - app.routers.webhook.process_messenger_event

テスト方針:
  - SQLite インメモリ + 最小スキーマ（leads / meta_messages / tenant_meta_config / tenants）
  - Meta Webhook は HMAC 検証経由で生 body を流す。BackgroundTasks の挙動は AsyncClient で再現できないので、
    process_messenger_event を **直接 await** して DB 副作用を検証する（HMAC は別途）
  - Discord 通知（send_discord_notification）は patch で no-op に
  - PostgreSQL 固有の `ON CONFLICT (col) WHERE pred` は SQLite でも動作する（部分 UNIQUE インデックスを別途張る）

実行:
    pytest backend/tests/test_webhook_instagram.py -v
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

# DATABASE_URL は他テストと同様 SQLite に固定（import 順の罠回避）
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker


# ---------------------------------------------------------------------------
# DDL（必要最小限、既存 test_message_send.py / test_conversations.py と整合）
# ---------------------------------------------------------------------------


_LEADS_DDL = """
    CREATE TABLE leads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_id INTEGER NOT NULL DEFAULT 999,
        lead_code VARCHAR(20),
        customer_name VARCHAR(255) NOT NULL,
        company_name VARCHAR(255),
        email VARCHAR(255),
        phone VARCHAR(50),
        source VARCHAR(100),
        type VARCHAR(50),
        status VARCHAR(50) DEFAULT '新規',
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

# Sprint 4 migration 041 + Phase 1-E F14-S5 migration 045（page_id 列）を反映
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

# Sprint 1 の migration 040 を SQLite に縮小
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

# webhook.py の env fallback で参照する public.tenants を SQLite で再現
_TENANTS_DDL = """
    CREATE TABLE tenants (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name VARCHAR(200) NOT NULL,
        is_active BOOLEAN NOT NULL DEFAULT 1
    )
"""

# leads.source の部分 UNIQUE 制約（PostgreSQL の ON CONFLICT (source) WHERE ... を再現）
_LEADS_SOURCE_UNIQUE_DDL = """
    CREATE UNIQUE INDEX uq_leads_source_meta
    ON leads (source)
    WHERE source LIKE 'messenger:%' OR source LIKE 'instagram:%'
"""

# meta_messages.message_id の部分 UNIQUE（migration 013 を SQLite で再現）
_META_MSG_ID_UNIQUE_DDL = """
    CREATE UNIQUE INDEX uq_meta_messages_message_id
    ON meta_messages (message_id)
    WHERE message_id IS NOT NULL
"""


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    @event.listens_for(eng.sync_engine, "connect")
    def _setup(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys = ON")

    async with eng.begin() as conn:
        await conn.execute(text(_LEADS_DDL))
        await conn.execute(text(_META_MESSAGES_DDL))
        await conn.execute(text(_TENANT_META_CONFIG_DDL))
        await conn.execute(text(_TENANTS_DDL))
        await conn.execute(text(_LEADS_SOURCE_UNIQUE_DDL))
        await conn.execute(text(_META_MSG_ID_UNIQUE_DDL))

        # 既定: tenant_id=999 を tenants に追加（env fallback テスト用）
        await conn.execute(
            text("INSERT INTO tenants (id, name, is_active) VALUES (999, 'Test Tenant', 1)")
        )

        # webhook.py の env fallback 経路は `public.tenants` をハードコード参照する
        # （PostgreSQL 本番ではスキーマ修飾が必要なため）。SQLite には schema 概念が無いので
        # 同名のビューを `public.tenants` として張る。
        # SQLite 3.7+ で `CREATE VIEW main.public_tenants` 風の hack ではなく、
        # ATTACH DATABASE ':memory:' AS public で同じインメモリに別 schema 名を割り当てる。
        await conn.exec_driver_sql("ATTACH DATABASE ':memory:' AS public")
        await conn.execute(text("""
            CREATE TABLE public.tenants AS
            SELECT * FROM tenants WHERE 0
        """))
        await conn.execute(text(
            "INSERT INTO public.tenants (id, name, is_active) VALUES (999, 'Test Tenant', 1)"
        ))

    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db_session(engine):
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        yield session
        await session.rollback()


@pytest.fixture
def app_secret_env(monkeypatch):
    """HMAC 検証で使う META_APP_SECRET を固定。"""
    monkeypatch.setenv("META_APP_SECRET", "test-app-secret")


@pytest.fixture
def verify_token_env(monkeypatch):
    monkeypatch.setenv("META_VERIFY_TOKEN", "test-verify-token")


# ---------------------------------------------------------------------------
# helper: insert tenant_meta_config row
# ---------------------------------------------------------------------------


async def _insert_tenant_meta_config(
    db_session,
    *,
    tenant_id: int = 999,
    page_id: str = "PAGE-1",
    ig_business_account_id: str | None = None,
    is_active: bool = True,
):
    await db_session.execute(text("""
        INSERT INTO tenant_meta_config (
            tenant_id, page_id, page_name, page_access_token_encrypted,
            instagram_business_account_id, is_active
        )
        VALUES (
            :tenant_id, :page_id, :name, :token, :ig, :active
        )
    """), {
        "tenant_id": tenant_id,
        "page_id": page_id,
        "name": "Test Page",
        "token": b"encrypted-bytes",
        "ig": ig_business_account_id,
        "active": 1 if is_active else 0,
    })
    await db_session.commit()


# ---------------------------------------------------------------------------
# webhook.py 内部の SET 文を SQLite で吸収するための共通 patch
# ---------------------------------------------------------------------------


# シンプルに SET 文だけ吸収するヘルパ（fixture と組み合わせて使う）
def _wrap_session_for_set_noop(db_session):
    original_execute = db_session.execute

    async def patched(stmt, *args, **kwargs):
        sql = str(stmt).strip()
        if sql.upper().startswith("SET "):
            return None
        return await original_execute(stmt, *args, **kwargs)

    db_session.execute = patched
    return original_execute


# ---------------------------------------------------------------------------
# 共通 fixture: AsyncSessionLocal + Discord + reset_tenant_context patch
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def webhook_env(db_session):
    """process_messenger_event を SQLite で安全に直接 await するための環境。"""

    class _SessionCtx:
        async def __aenter__(self):
            return db_session

        async def __aexit__(self, exc_type, exc, tb):
            return False

    original_execute = _wrap_session_for_set_noop(db_session)

    with ExitStack() as stack:
        stack.enter_context(patch(
            "app.routers.webhook.AsyncSessionLocal",
            new=lambda: _SessionCtx(),
        ))
        stack.enter_context(patch(
            "app.routers.webhook.reset_tenant_context",
            new=AsyncMock(return_value=None),
        ))
        stack.enter_context(patch(
            "app.routers.webhook.send_discord_notification",
            new=AsyncMock(return_value=None),
        ))
        yield

    # cleanup: execute を元に戻す
    db_session.execute = original_execute


# ---------------------------------------------------------------------------
# GET /webhook/messenger（hub.challenge 応答）
# ---------------------------------------------------------------------------


def _build_app_for_get():
    from app.routers import webhook as wh

    app = FastAPI()
    app.include_router(wh.router, prefix="/api/v1")
    return app


@pytest.mark.asyncio
async def test_verify_webhook_returns_challenge_when_token_matches(verify_token_env):
    app = _build_app_for_get()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get(
            "/api/v1/webhook/messenger",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "test-verify-token",
                "hub.challenge": "challenge-12345",
            },
        )
    assert resp.status_code == 200
    assert resp.text == "challenge-12345"


@pytest.mark.asyncio
async def test_verify_webhook_returns_403_when_token_mismatch(verify_token_env):
    app = _build_app_for_get()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get(
            "/api/v1/webhook/messenger",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "wrong-token",
                "hub.challenge": "challenge-12345",
            },
        )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_verify_webhook_returns_500_when_env_missing(monkeypatch):
    monkeypatch.delenv("META_VERIFY_TOKEN", raising=False)
    app = _build_app_for_get()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get(
            "/api/v1/webhook/messenger",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "anything",
                "hub.challenge": "x",
            },
        )
    assert resp.status_code == 500


# ---------------------------------------------------------------------------
# POST /webhook/messenger HMAC 検証
# ---------------------------------------------------------------------------


def _hmac_header(secret: str, body_bytes: bytes) -> str:
    return "sha256=" + hmac.new(
        secret.encode(), body_bytes, hashlib.sha256
    ).hexdigest()


@pytest.mark.asyncio
async def test_post_webhook_returns_403_when_signature_invalid(app_secret_env):
    app = _build_app_for_get()
    transport = ASGITransport(app=app)
    body = json.dumps({"object": "page", "entry": []}).encode()
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post(
            "/api/v1/webhook/messenger",
            content=body,
            headers={
                "X-Hub-Signature-256": "sha256=deadbeef",
                "Content-Type": "application/json",
            },
        )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_post_webhook_returns_200_when_signature_valid(app_secret_env):
    """HMAC 一致時は 200 + status:ok を返す（BackgroundTasks の中身までは検証しない、
    process_messenger_event は別テストで直接 await する）。"""
    app = _build_app_for_get()
    transport = ASGITransport(app=app)
    body = json.dumps({"object": "page", "entry": []}).encode()
    sig = _hmac_header("test-app-secret", body)

    # BackgroundTasks 経由の DB 呼び出しは patch で完全に no-op（ここでは HMAC のみ検証）
    with patch(
        "app.routers.webhook.process_messenger_event",
        new=AsyncMock(return_value=None),
    ):
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post(
                "/api/v1/webhook/messenger",
                content=body,
                headers={
                    "X-Hub-Signature-256": sig,
                    "Content-Type": "application/json",
                },
            )
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# テナント特定: tenant_meta_config 参照
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_tenant_id_by_page_returns_tenant_when_active_row_exists(db_session):
    from app.routers import webhook as wh

    await _insert_tenant_meta_config(
        db_session, tenant_id=999, page_id="PAGE-A",
    )
    tenant_id = await wh._get_tenant_id_by_page(db_session, "PAGE-A")
    assert tenant_id == 999


@pytest.mark.asyncio
async def test_get_tenant_id_by_page_ignores_inactive_row(db_session):
    from app.routers import webhook as wh

    await _insert_tenant_meta_config(
        db_session, tenant_id=999, page_id="PAGE-A", is_active=False,
    )
    tenant_id = await wh._get_tenant_id_by_page(db_session, "PAGE-A")
    assert tenant_id is None


# Phase 1-E F25-S6 で META_PAGE_ID env fallback が削除されたため、
# 旧 test_get_tenant_id_by_page_falls_back_to_env / *_env_fallback_does_not_match_other_page /
# *_db_takes_priority_over_env / *_env_fallback_works_after_search_aborts_session は廃止。
# F26 regression は F16 で routing 表化されアボートシナリオ自体が消滅したため
# 不要になった。


@pytest.mark.asyncio
async def test_search_tenant_meta_config_prefers_meta_page_routing(
    db_session, monkeypatch,
):
    """Phase 1-E F16-S6 regression:
    `_search_tenant_meta_config` は最初に `public.meta_page_routing`（migration 043+044
    で同期される公開ルーティング表）を 1 クエリで参照する。テナント数 N に依存しない
    O(1) 逆引きが成立することをモックで検証。

    本テストでは `db.execute` をラップして、
      1. 最初の SELECT が `public.meta_page_routing` を含むこと
      2. routing 表が値を返した場合、フラットの `tenant_meta_config` への 2 回目クエリは
         発行されないこと
    を確認する。
    """
    from app.routers import webhook as wh
    from sqlalchemy.engine import Result
    from unittest.mock import MagicMock

    queries: list[str] = []
    original_execute = db_session.execute

    async def execute_recorder(stmt, *args, **kwargs):
        sql = str(stmt) if hasattr(stmt, "compile") else stmt.text
        queries.append(sql)
        # 1 回目（meta_page_routing）には tenant_id=42 を返すモック Result を返す
        if "meta_page_routing" in sql:
            mock_result = MagicMock(spec=Result)
            mock_result.first.return_value = (42,)
            return mock_result
        return await original_execute(stmt, *args, **kwargs)

    monkeypatch.setattr(db_session, "execute", execute_recorder)

    tenant_id = await wh._search_tenant_meta_config(
        db_session, column="page_id", value="PAGE-X",
    )

    assert tenant_id == 42, "meta_page_routing からの値が返っていない"
    # 1 クエリで完了（フラット tenant_meta_config への 2 回目クエリなし）
    routing_queries = [q for q in queries if "meta_page_routing" in q]
    flat_queries = [
        q for q in queries
        if "tenant_meta_config" in q and "meta_page_routing" not in q
    ]
    assert len(routing_queries) == 1, (
        f"meta_page_routing への参照が 1 回ではない: {len(routing_queries)} 回"
    )
    assert len(flat_queries) == 0, (
        "meta_page_routing が値を返したのに flat tenant_meta_config も参照している: "
        f"{flat_queries}"
    )


@pytest.mark.asyncio
async def test_search_tenant_meta_config_falls_back_when_routing_table_missing(
    db_session, monkeypatch,
):
    """Phase 1-E F16-S6 regression:
    `public.meta_page_routing` が存在しない環境（SQLite テスト or migration 043 未適用 PG）
    では、フラットな `tenant_meta_config` への直接検索にフォールバックする。
    """
    from app.routers import webhook as wh

    # SQLite では public.meta_page_routing は存在しない → 自然に flat フォールバックされる
    await _insert_tenant_meta_config(
        db_session, tenant_id=777, page_id="PAGE-Y",
    )

    tenant_id = await wh._search_tenant_meta_config(
        db_session, column="page_id", value="PAGE-Y",
    )
    assert tenant_id == 777


@pytest.mark.asyncio
async def test_get_tenant_id_by_ig_account_returns_tenant_when_match(db_session):
    from app.routers import webhook as wh

    await _insert_tenant_meta_config(
        db_session, tenant_id=999, page_id="PAGE-A",
        ig_business_account_id="IG-BIZ-1",
    )
    tenant_id = await wh._get_tenant_id_by_ig_account(db_session, "IG-BIZ-1")
    assert tenant_id == 999


@pytest.mark.asyncio
async def test_get_tenant_id_by_ig_account_returns_none_when_inactive(db_session):
    from app.routers import webhook as wh

    await _insert_tenant_meta_config(
        db_session, tenant_id=999, page_id="PAGE-A",
        ig_business_account_id="IG-BIZ-1", is_active=False,
    )
    tenant_id = await wh._get_tenant_id_by_ig_account(db_session, "IG-BIZ-1")
    assert tenant_id is None


@pytest.mark.asyncio
async def test_get_tenant_id_by_ig_account_returns_none_for_unknown(db_session):
    from app.routers import webhook as wh

    tenant_id = await wh._get_tenant_id_by_ig_account(db_session, "IG-UNKNOWN")
    assert tenant_id is None


@pytest.mark.asyncio
async def test_search_tenant_meta_config_rejects_unknown_column(db_session):
    """SQL injection 防止のためのホワイトリスト検証。"""
    from app.routers import webhook as wh

    with pytest.raises(ValueError):
        await wh._search_tenant_meta_config(
            db_session, column="page_access_token_encrypted", value="x",
        )


# Phase 1-E F25-S6: `_list_active_tenant_ids` は env fallback でしか使われていなかった
# ため、env fallback 削除と同時にこの helper も削除。テストも廃止。


# ---------------------------------------------------------------------------
# _iter_inbound_messages: payload 形式パース
# ---------------------------------------------------------------------------


def test_iter_inbound_messages_messenger_messaging_format():
    from app.routers import webhook as wh

    entry = {
        "id": "PAGE-A",
        "messaging": [
            {
                "sender": {"id": "PSID-1"},
                "timestamp": 1714400000,
                "message": {"mid": "mid-100", "text": "Hello"},
            },
            {
                "sender": {"id": "PSID-2"},
                "timestamp": 1714400001,
                # echo はスキップされる
                "message": {"mid": "mid-101", "text": "Echo!", "is_echo": True},
            },
            {
                "sender": {"id": "PSID-3"},
                # message が無い event（postback 等）はスキップ
            },
        ],
    }
    out = list(wh._iter_inbound_messages(entry, object_type="page"))
    assert len(out) == 1
    assert out[0]["sender_id"] == "PSID-1"
    assert out[0]["message_text"] == "Hello"
    assert out[0]["message_id"] == "mid-100"


def test_iter_inbound_messages_instagram_messaging_format():
    from app.routers import webhook as wh

    entry = {
        "id": "IG-BIZ-1",
        "messaging": [
            {
                "sender": {"id": "IGSID-1"},
                "timestamp": 1714400000,
                "message": {"mid": "ig-mid-1", "text": "こんにちは"},
            },
        ],
    }
    out = list(wh._iter_inbound_messages(entry, object_type="instagram"))
    assert len(out) == 1
    assert out[0]["sender_id"] == "IGSID-1"
    assert out[0]["message_text"] == "こんにちは"


def test_iter_inbound_messages_instagram_changes_format():
    """Instagram の `entry[].changes[].value.messages[]` 形式をパースする。"""
    from app.routers import webhook as wh

    entry = {
        "id": "IG-BIZ-1",
        "changes": [
            {
                "field": "messages",
                "value": {
                    "messaging_product": "instagram",
                    "messages": [
                        {
                            "id": "ig-mid-2",
                            "from": {"id": "IGSID-2"},
                            "timestamp": "1714400099",
                            "text": "やぁ",
                        },
                    ],
                },
            },
        ],
    }
    out = list(wh._iter_inbound_messages(entry, object_type="instagram"))
    assert len(out) == 1
    assert out[0]["sender_id"] == "IGSID-2"
    assert out[0]["message_text"] == "やぁ"
    assert out[0]["message_id"] == "ig-mid-2"


def test_iter_inbound_messages_skips_unknown_change_field():
    from app.routers import webhook as wh

    entry = {
        "id": "IG-BIZ-1",
        "changes": [
            {"field": "comments", "value": {"messages": [{"id": "x", "from": {"id": "y"}}]}},
        ],
    }
    out = list(wh._iter_inbound_messages(entry, object_type="instagram"))
    assert out == []


def test_iter_inbound_messages_returns_empty_for_no_payload():
    from app.routers import webhook as wh

    out = list(wh._iter_inbound_messages({"id": "X"}, object_type="page"))
    assert out == []


# ---------------------------------------------------------------------------
# _persist_meta_message: lead 自動作成 + meta_messages INSERT
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persist_meta_message_creates_lead_for_messenger(db_session, webhook_env):
    from app.routers import webhook as wh

    msg_id = await wh._persist_meta_message(
        db_session,
        tenant_id=999,
        platform="messenger",
        sender_id="PSID-NEW",
        message_text="hello",
        message_id="mid-msg-1",
        timestamp=1714400000,
        has_attachments=False,
    )
    assert msg_id is not None

    # leads 自動作成
    res = await db_session.execute(text(
        "SELECT id, source, customer_name, lead_code FROM leads"
    ))
    rows = list(res.mappings())
    assert len(rows) == 1
    assert rows[0]["source"] == "messenger:PSID-NEW"
    assert rows[0]["customer_name"] == "Messenger User"
    assert rows[0]["lead_code"] == f"LD-{rows[0]['id']:05d}"

    # meta_messages 登録
    res = await db_session.execute(text(
        "SELECT platform, sender_id, message_text, direction, message_id "
        "FROM meta_messages WHERE id = :id"
    ), {"id": msg_id})
    row = res.mappings().first()
    assert row["platform"] == "messenger"
    assert row["sender_id"] == "PSID-NEW"
    assert row["message_text"] == "hello"
    assert row["direction"] == "inbound"
    assert row["message_id"] == "mid-msg-1"


@pytest.mark.asyncio
async def test_persist_meta_message_creates_lead_for_instagram(db_session, webhook_env):
    from app.routers import webhook as wh

    msg_id = await wh._persist_meta_message(
        db_session,
        tenant_id=999,
        platform="instagram",
        sender_id="IGSID-1",
        message_text="やぁ",
        message_id="ig-mid-99",
        timestamp=1714400000,
        has_attachments=False,
    )
    assert msg_id is not None

    res = await db_session.execute(text(
        "SELECT source, customer_name FROM leads"
    ))
    row = res.mappings().first()
    assert row["source"] == "instagram:IGSID-1"
    assert row["customer_name"] == "Instagram User"

    res = await db_session.execute(text(
        "SELECT platform FROM meta_messages WHERE id = :id"
    ), {"id": msg_id})
    assert res.scalar() == "instagram"


@pytest.mark.asyncio
async def test_persist_meta_message_skips_duplicate_message_id(
    db_session, webhook_env,
):
    """同じ message_id が来たら 2 回目は INSERT されず None が返る。"""
    from app.routers import webhook as wh

    first = await wh._persist_meta_message(
        db_session,
        tenant_id=999,
        platform="messenger",
        sender_id="PSID-1",
        message_text="dup test",
        message_id="mid-dup",
        timestamp=1,
        has_attachments=False,
    )
    second = await wh._persist_meta_message(
        db_session,
        tenant_id=999,
        platform="messenger",
        sender_id="PSID-1",
        message_text="dup test",
        message_id="mid-dup",
        timestamp=1,
        has_attachments=False,
    )
    assert first is not None
    assert second is None
    res = await db_session.execute(text(
        "SELECT COUNT(*) FROM meta_messages WHERE message_id = 'mid-dup'"
    ))
    assert res.scalar() == 1


@pytest.mark.asyncio
async def test_persist_meta_message_reuses_existing_lead(db_session, webhook_env):
    """同じ source の lead がすでにあれば再作成しない。"""
    from app.routers import webhook as wh

    # 既存 lead を投入
    await db_session.execute(text("""
        INSERT INTO leads (id, tenant_id, lead_code, customer_name, source, status)
        VALUES (42, 999, 'LD-00042', 'Existing', 'messenger:PSID-EX', '新規')
    """))
    await db_session.commit()

    await wh._persist_meta_message(
        db_session,
        tenant_id=999,
        platform="messenger",
        sender_id="PSID-EX",
        message_text="reuse",
        message_id="mid-reuse",
        timestamp=1,
        has_attachments=False,
    )

    res = await db_session.execute(text("SELECT COUNT(*) FROM leads"))
    assert res.scalar() == 1  # 増えていない
    res = await db_session.execute(text(
        "SELECT lead_id FROM meta_messages WHERE message_id = 'mid-reuse'"
    ))
    assert res.scalar() == 42


@pytest.mark.asyncio
async def test_persist_meta_message_rejects_unknown_platform(db_session, webhook_env):
    from app.routers import webhook as wh

    with pytest.raises(ValueError):
        await wh._persist_meta_message(
            db_session,
            tenant_id=999,
            platform="whatsapp",  # 未対応
            sender_id="X",
            message_text="x",
            message_id=None,
            timestamp=None,
            has_attachments=False,
        )


# ---------------------------------------------------------------------------
# process_messenger_event: end-to-end（HMAC 検証は別、ここはペイロード分岐の検証）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_event_messenger_inbound_persists_record(db_session, webhook_env):
    """Messenger の標準 webhook ペイロードで meta_messages に platform='messenger' で
    レコードが入り、leads が新規作成される（既存挙動の regression を兼ねる）。"""
    from app.routers import webhook as wh

    await _insert_tenant_meta_config(
        db_session, tenant_id=999, page_id="PAGE-A",
    )

    body = {
        "object": "page",
        "entry": [{
            "id": "PAGE-A",
            "messaging": [{
                "sender": {"id": "PSID-100"},
                "timestamp": 1714400000,
                "message": {"mid": "mid-msg-100", "text": "Hello"},
            }],
        }],
    }
    await wh.process_messenger_event(body)

    res = await db_session.execute(text(
        "SELECT platform, message_text, page_id FROM meta_messages "
        "WHERE message_id = 'mid-msg-100'"
    ))
    row = res.mappings().first()
    assert row is not None
    assert row["platform"] == "messenger"
    assert row["message_text"] == "Hello"
    # Phase 1-E F14-S5: Messenger は entry.id を page_id として保存
    assert row["page_id"] == "PAGE-A"

    res = await db_session.execute(text(
        "SELECT source FROM leads WHERE source = 'messenger:PSID-100'"
    ))
    assert res.scalar() == "messenger:PSID-100"


@pytest.mark.asyncio
async def test_process_event_instagram_resolves_parent_page_id(
    db_session, webhook_env,
):
    """Phase 1-E F14-FU1: Instagram 受信時は IG account ID から親 Page ID を逆引きして
    meta_messages.page_id を埋める。"""
    from app.routers import webhook as wh

    await _insert_tenant_meta_config(
        db_session, tenant_id=999, page_id="PAGE-PARENT-X",
        ig_business_account_id="IG-BIZ-X",
    )

    body = {
        "object": "instagram",
        "entry": [{
            "id": "IG-BIZ-X",
            "messaging": [{
                "sender": {"id": "IGSID-200"},
                "timestamp": 1714400000,
                "message": {"mid": "mid-ig-200", "text": "Hi IG"},
            }],
        }],
    }
    await wh.process_messenger_event(body)

    res = await db_session.execute(text(
        "SELECT platform, page_id FROM meta_messages WHERE message_id = 'mid-ig-200'"
    ))
    row = res.mappings().first()
    assert row is not None
    assert row["platform"] == "instagram"
    # F14-FU1: IG account ID から親 Page ID が解決される
    assert row["page_id"] == "PAGE-PARENT-X"


@pytest.mark.asyncio
async def test_process_event_instagram_page_id_null_when_no_mapping(
    db_session, webhook_env,
):
    """Phase 1-E F14-FU1: tenant_meta_config に該当 ig_business_account_id が無ければ
    page_id は NULL で保存（webhook 自体は落とさない）。"""
    from app.routers import webhook as wh

    # IG-BIZ-X を登録しない。代わりに別の IG（IG-OTHER）で登録しておくことで
    # webhook が tenant 解決経路（page_id fallback）に進む状況を作る。
    await _insert_tenant_meta_config(
        db_session, tenant_id=999, page_id="IG-NOT-A-PAGE-RELATIVE",
    )

    body = {
        "object": "instagram",
        "entry": [{
            "id": "IG-NOT-A-PAGE-RELATIVE",
            "messaging": [{
                "sender": {"id": "IGSID-300"},
                "timestamp": 1714400000,
                "message": {"mid": "mid-ig-300", "text": "Hi"},
            }],
        }],
    }
    await wh.process_messenger_event(body)

    res = await db_session.execute(text(
        "SELECT page_id FROM meta_messages WHERE message_id = 'mid-ig-300'"
    ))
    row = res.first()
    assert row is not None
    # IG account → page_id 逆引き失敗（page_id 列の値は IG account と一致しない）
    # → NULL のまま
    assert row[0] is None


@pytest.mark.asyncio
async def test_process_event_instagram_messaging_persists_record(db_session, webhook_env):
    """Instagram の messaging[] 形式 + tenant_meta_config.instagram_business_account_id 経由で
    レコードが入る。"""
    from app.routers import webhook as wh

    await _insert_tenant_meta_config(
        db_session, tenant_id=999, page_id="PAGE-A",
        ig_business_account_id="IG-BIZ-1",
    )

    body = {
        "object": "instagram",
        "entry": [{
            "id": "IG-BIZ-1",  # IG webhook では entry.id は IG Business Account ID
            "messaging": [{
                "sender": {"id": "IGSID-100"},
                "timestamp": 1714400000,
                "message": {"mid": "ig-mid-100", "text": "やあ"},
            }],
        }],
    }
    await wh.process_messenger_event(body)

    res = await db_session.execute(text(
        "SELECT platform, sender_id FROM meta_messages WHERE message_id = 'ig-mid-100'"
    ))
    row = res.mappings().first()
    assert row is not None
    assert row["platform"] == "instagram"
    assert row["sender_id"] == "IGSID-100"

    res = await db_session.execute(text(
        "SELECT source FROM leads WHERE source = 'instagram:IGSID-100'"
    ))
    assert res.scalar() == "instagram:IGSID-100"


@pytest.mark.asyncio
async def test_process_event_instagram_changes_format_persists_record(
    db_session, webhook_env,
):
    """Instagram の `entry[].changes[].value.messages[]` 形式でも処理できる。"""
    from app.routers import webhook as wh

    await _insert_tenant_meta_config(
        db_session, tenant_id=999, page_id="PAGE-A",
        ig_business_account_id="IG-BIZ-2",
    )

    body = {
        "object": "instagram",
        "entry": [{
            "id": "IG-BIZ-2",
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "instagram",
                    "messages": [{
                        "id": "ig-mid-200",
                        "from": {"id": "IGSID-200"},
                        "timestamp": "1714400000",
                        "text": "test changes",
                    }],
                },
            }],
        }],
    }
    await wh.process_messenger_event(body)

    res = await db_session.execute(text(
        "SELECT platform, message_text FROM meta_messages WHERE message_id = 'ig-mid-200'"
    ))
    row = res.mappings().first()
    assert row is not None
    assert row["platform"] == "instagram"
    assert row["message_text"] == "test changes"


@pytest.mark.asyncio
async def test_process_event_instagram_falls_back_to_page_id(db_session, webhook_env):
    """IG account ID で見つからなくても page_id でも引いて tenant 特定できる。"""
    from app.routers import webhook as wh

    # IG カラムは NULL、page_id だけ登録
    await _insert_tenant_meta_config(
        db_session, tenant_id=999, page_id="PAGE-FB",
    )

    body = {
        "object": "instagram",
        "entry": [{
            "id": "PAGE-FB",  # tenant_meta_config.page_id にヒット
            "messaging": [{
                "sender": {"id": "IGSID-300"},
                "timestamp": 1714400000,
                "message": {"mid": "ig-mid-300", "text": "fallback"},
            }],
        }],
    }
    await wh.process_messenger_event(body)

    res = await db_session.execute(text(
        "SELECT platform FROM meta_messages WHERE message_id = 'ig-mid-300'"
    ))
    assert res.scalar() == "instagram"


@pytest.mark.asyncio
async def test_process_event_skips_when_tenant_unknown(db_session, webhook_env, caplog):
    """tenant_meta_config に該当行が無く env fallback も効かないなら DB 副作用ゼロ。"""
    from app.routers import webhook as wh

    body = {
        "object": "page",
        "entry": [{
            "id": "PAGE-UNKNOWN",
            "messaging": [{
                "sender": {"id": "PSID-X"},
                "timestamp": 1,
                "message": {"mid": "mid-x", "text": "x"},
            }],
        }],
    }
    await wh.process_messenger_event(body)

    res = await db_session.execute(text(
        "SELECT COUNT(*) FROM meta_messages"
    ))
    assert res.scalar() == 0
    res = await db_session.execute(text("SELECT COUNT(*) FROM leads"))
    assert res.scalar() == 0


# Phase 1-E F25-S6: META_PAGE_ID env fallback 削除に伴い、env fallback 経由の
# process_messenger_event 経路は無くなった。test_process_event_uses_env_fallback_when_db_empty
# は廃止（DB 空のときは tenant 特定失敗で warning ログ + skip するのが正しい挙動）。


@pytest.mark.asyncio
async def test_process_event_ignores_unknown_object_type(db_session, webhook_env):
    """object='user' 等は無視する（Sprint 5 までと同じ挙動）。"""
    from app.routers import webhook as wh

    body = {"object": "user", "entry": [{"id": "X"}]}
    await wh.process_messenger_event(body)

    res = await db_session.execute(text("SELECT COUNT(*) FROM meta_messages"))
    assert res.scalar() == 0


# ---------------------------------------------------------------------------
# Phase 1-E F15-S6: customer_name の Graph API 補完
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_new_lead_customer_name_updated_when_graph_api_returns_name(
    db_session, webhook_env, monkeypatch,
):
    """Phase 1-E F15-S6 regression:
    新規 lead 作成時、`_resolve_lead_name_via_graph` が name を返すと
    `leads.customer_name` がその name で UPDATE される（PSID 文字列のままにならない）。
    """
    from app.routers import webhook as wh

    await _insert_tenant_meta_config(
        db_session, tenant_id=999, page_id="PAGE-A",
    )

    # Graph API 由来の name を返すモック（F15-FU1 で page_id 引数追加）
    captured_page_id = {}

    async def fake_resolve(db, sender_id, page_id=None):
        assert sender_id == "PSID-NAME-1"
        captured_page_id["value"] = page_id
        return "山田 太郎"

    monkeypatch.setattr(wh, "_resolve_lead_name_via_graph", fake_resolve)

    body = {
        "object": "page",
        "entry": [{
            "id": "PAGE-A",
            "messaging": [{
                "sender": {"id": "PSID-NAME-1"},
                "timestamp": 1714400000,
                "message": {"mid": "mid-name-1", "text": "Hi"},
            }],
        }],
    }
    await wh.process_messenger_event(body)

    res = await db_session.execute(text(
        "SELECT customer_name FROM leads WHERE source = 'messenger:PSID-NAME-1'"
    ))
    assert res.scalar() == "山田 太郎"
    # Phase 1-E F15-FU1: 受信元 Page ID が graph 解決に渡される
    assert captured_page_id["value"] == "PAGE-A"


@pytest.mark.asyncio
async def test_new_lead_keeps_default_name_when_graph_api_returns_none(
    db_session, webhook_env, monkeypatch,
):
    """Phase 1-E F15-S6: Graph API が None / 失敗時は既定名のまま続行する（webhook を落とさない）。"""
    from app.routers import webhook as wh

    await _insert_tenant_meta_config(
        db_session, tenant_id=999, page_id="PAGE-A",
    )

    async def fake_resolve_none(db, sender_id, page_id=None):
        return None

    monkeypatch.setattr(wh, "_resolve_lead_name_via_graph", fake_resolve_none)

    body = {
        "object": "page",
        "entry": [{
            "id": "PAGE-A",
            "messaging": [{
                "sender": {"id": "PSID-NONAME"},
                "timestamp": 1714400000,
                "message": {"mid": "mid-noname", "text": "Hi"},
            }],
        }],
    }
    await wh.process_messenger_event(body)

    res = await db_session.execute(text(
        "SELECT customer_name FROM leads WHERE source = 'messenger:PSID-NONAME'"
    ))
    assert res.scalar() == "Messenger User"


@pytest.mark.asyncio
async def test_existing_lead_does_not_trigger_graph_api(
    db_session, webhook_env, monkeypatch,
):
    """Phase 1-E F15-S6: 既存 lead（source 一致行が DB に存在）には Graph API を呼ばない。
    （新規作成時のみ補完。再受信のたびに API を叩いて Rate Limit を浪費しない）"""
    from app.routers import webhook as wh

    await _insert_tenant_meta_config(
        db_session, tenant_id=999, page_id="PAGE-A",
    )
    # 既存の lead を入れておく
    await db_session.execute(text("""
        INSERT INTO leads (id, tenant_id, customer_name, source, type, status, lead_code)
        VALUES (5001, 999, '既存さん', 'messenger:PSID-EXISTING', 'Inbound', '新規', 'LD-05001')
    """))
    await db_session.commit()

    call_count = {"n": 0}

    async def fake_resolve_count(db, sender_id, page_id=None):
        call_count["n"] += 1
        return "別人"

    monkeypatch.setattr(wh, "_resolve_lead_name_via_graph", fake_resolve_count)

    body = {
        "object": "page",
        "entry": [{
            "id": "PAGE-A",
            "messaging": [{
                "sender": {"id": "PSID-EXISTING"},
                "timestamp": 1714400000,
                "message": {"mid": "mid-existing", "text": "Hi"},
            }],
        }],
    }
    await wh.process_messenger_event(body)

    # 既存 lead は customer_name が変わらない
    res = await db_session.execute(text(
        "SELECT customer_name FROM leads WHERE id = 5001"
    ))
    assert res.scalar() == "既存さん"
    # Graph API も呼ばれていない
    assert call_count["n"] == 0


# ---------------------------------------------------------------------------
# ADR-026: meta_messages.message_id TEXT 化 — 200 文字 mid の regression
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_long_message_id_persists(db_session, webhook_env):
    """ADR-026 regression:
    Instagram の Message ID (mid) は base64 多重エンコードで 150〜200 文字を超える。
    既存定義 `VARCHAR(100)` で `StringDataRightTruncationError` を起こしていた事象を
    `meta_messages.message_id` の TEXT 化で解消する。

    本テストでは架空の 200 文字 mid を含む IG webhook を `process_messenger_event`
    に流し、`meta_messages` 行が正しく永続化されることを確認する。

    SQLite は型を緩く扱うため VARCHAR(100) でも 200 文字を素通しさせるが、テストの
    意図は「webhook ハンドラが長 mid を取り扱う際にコード側で長さ検査やトリミングを
    行っていないこと」を回帰検証することにある（コード側の non-truncation 保証）。
    PostgreSQL 本番では migration 052 + per-tenant スクリプトで列型を TEXT に拡張
    することで truncation が回避される（Hitoshi 即決 Q-026.1〜Q-026.4 / ADR-026）。
    """
    from app.routers import webhook as wh

    await _insert_tenant_meta_config(
        db_session, tenant_id=999, page_id="PAGE-LONG",
        ig_business_account_id="IG-BIZ-LONG",
    )

    # 架空の 200 文字 mid（PII を含まない、IG mid の base64 風 prefix のみ流用）
    # `aWdfZA` は base64 で "ig_" のエンコード、後続は 'x' × 194 文字
    long_mid = "aWdfZA" + ("x" * 194)
    assert len(long_mid) == 200

    body = {
        "object": "instagram",
        "entry": [{
            "id": "IG-BIZ-LONG",
            "messaging": [{
                "sender": {"id": "IGSID-LONG"},
                "timestamp": 1714400000,
                "message": {"mid": long_mid, "text": "long mid test"},
            }],
        }],
    }
    await wh.process_messenger_event(body)

    # 行が永続化されている（message_id が truncate されていない）
    res = await db_session.execute(
        text(
            "SELECT platform, sender_id, message_text, message_id, length(message_id) AS len "
            "FROM meta_messages WHERE message_id = :mid"
        ),
        {"mid": long_mid},
    )
    row = res.mappings().first()
    assert row is not None, "200 文字 message_id の行が永続化されていない"
    assert row["platform"] == "instagram"
    assert row["sender_id"] == "IGSID-LONG"
    assert row["message_text"] == "long mid test"
    assert row["message_id"] == long_mid
    assert row["len"] == 200, f"保存された message_id の長さが 200 ではない: {row['len']}"

    # leads も作成されている
    res = await db_session.execute(text(
        "SELECT source FROM leads WHERE source = 'instagram:IGSID-LONG'"
    ))
    assert res.scalar() == "instagram:IGSID-LONG"
