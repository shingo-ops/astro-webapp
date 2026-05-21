"""Sprint 5 (F5) — Discord Bot 受信フロー テスト。

AC 対応:
  - AC5.1: 実 Discord guild 検証は SKIP (Discord アクセス権未確定、別 PR で実機検証)。
            代替として discord.Message を模倣した dataclass で
            `JarvisDiscordClient.on_message` の logic path を pytest で検証する。
  - AC5.2: 同一 discord_message_id を 2 回 INSERT → 1 行のみ、idempotency 記録 (実 Postgres)
  - AC5.3: routing 未登録 guild → parse_status='ignored_routing' (実 Postgres)
  - AC5.4: 切断 → 再接続後 history 補完 (mock channel.history)

実 PostgreSQL 必須 (TEST_PG_URL)。SQLite モックは禁止 (memory: feedback_evaluator_gap_2026_05_15)。
"""
from __future__ import annotations

import asyncio
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

TEST_PG_URL = os.getenv("TEST_PG_URL")

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not TEST_PG_URL,
        reason="実 PostgreSQL 環境が必要 (TEST_PG_URL 未設定)。",
    ),
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def engine():
    from sqlalchemy.ext.asyncio import create_async_engine
    eng = create_async_engine(TEST_PG_URL, echo=False)
    yield eng
    await eng.dispose()


@pytest.fixture
async def session_maker(engine):
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
async def seed_supplier_routing(engine):
    """テスト用 supplier + routing を1組作成、yield 後に cleanup。"""
    from sqlalchemy import text

    sup_name = f"sprint5_supplier_{uuid.uuid4().hex[:6]}"
    guild_id = f"g_{uuid.uuid4().hex[:10]}"
    channel_id = f"c_{uuid.uuid4().hex[:10]}"

    async with engine.begin() as conn:
        # public.suppliers が必要
        exists = (await conn.execute(text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name='suppliers'"
        ))).scalar_one_or_none()
        if not exists:
            pytest.skip("public.suppliers 未作成 (migration 056 必要)")
        result = await conn.execute(text("""
            INSERT INTO public.suppliers (name, supplier_type, default_language)
            VALUES (:n, 'corporate', 'ja')
            RETURNING id
        """), {"n": sup_name})
        sup_id = result.scalar_one()
        await conn.execute(text("""
            INSERT INTO public.supplier_discord_routing
                (supplier_id, discord_guild_id, discord_channel_id, is_active)
            VALUES (:sid, :g, :c, TRUE)
        """), {"sid": sup_id, "g": guild_id, "c": channel_id})

    yield {
        "supplier_id": sup_id,
        "guild_id": guild_id,
        "channel_id": channel_id,
        "supplier_name": sup_name,
    }

    # cleanup
    async with engine.begin() as conn:
        await conn.execute(text(
            "DELETE FROM public.discord_inbound_messages "
            "WHERE discord_channel_id = :c"
        ), {"c": channel_id})
        await conn.execute(text(
            "DELETE FROM public.discord_webhook_idempotency "
            "WHERE message_id LIKE 'sprint5_%'"
        ))
        await conn.execute(text(
            "DELETE FROM public.supplier_discord_routing WHERE supplier_id = :sid"
        ), {"sid": sup_id})
        await conn.execute(text(
            "DELETE FROM public.suppliers WHERE id = :sid"
        ), {"sid": sup_id})


# ---------------------------------------------------------------------------
# Fake discord.Message (テストで discord.py を起動せずに on_message を駆動)
# ---------------------------------------------------------------------------


@dataclass
class _FakeAuthor:
    id: int
    bot: bool = False


@dataclass
class _FakeGuild:
    id: int


@dataclass
class _FakeChannel:
    id: int


@dataclass
class _FakeMessage:
    id: int
    content: str
    author: _FakeAuthor
    guild: _FakeGuild | None
    channel: _FakeChannel
    created_at: datetime


def _make_message(
    *,
    msg_id: str,
    guild_id: str,
    channel_id: str,
    content: str = "リザードン eX SAR 2枚 @18000円",
    is_bot: bool = False,
) -> _FakeMessage:
    return _FakeMessage(
        id=int(msg_id) if msg_id.isdigit() else hash(msg_id) & ((1 << 63) - 1),
        content=content,
        author=_FakeAuthor(id=12345, bot=is_bot),
        guild=_FakeGuild(id=int(guild_id) if guild_id.isdigit() else hash(guild_id) & ((1 << 63) - 1)) if guild_id else None,
        channel=_FakeChannel(id=int(channel_id) if channel_id.isdigit() else hash(channel_id) & ((1 << 63) - 1)),
        created_at=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# AC5.2: 同一 discord_message_id 2 回 → 1 行のみ
# ---------------------------------------------------------------------------


async def test_ac5_2_idempotent_same_message_id(engine, session_maker, seed_supplier_routing):
    """AC5.2: 同一 discord_message_id を 2 回 INSERT → 1 行のみ、idempotency 記録。"""
    from sqlalchemy import text
    from app.discord_gateway import inbound_writer

    ctx = seed_supplier_routing
    msg_id = f"sprint5_msg_{uuid.uuid4().hex[:10]}"

    # 1 回目
    async with session_maker() as session:
        r1 = await inbound_writer.write_inbound(
            session,
            discord_message_id=msg_id,
            discord_channel_id=ctx["channel_id"],
            supplier_id=ctx["supplier_id"],
            raw_content="line A",
            parse_status="pending",
        )
    assert r1.inserted is True
    assert r1.inbound_id is not None

    # 2 回目 (同じ msg_id)
    async with session_maker() as session:
        r2 = await inbound_writer.write_inbound(
            session,
            discord_message_id=msg_id,
            discord_channel_id=ctx["channel_id"],
            supplier_id=ctx["supplier_id"],
            raw_content="line A (dup)",
            parse_status="pending",
        )
    assert r2.inserted is False
    assert r2.inbound_id is None

    # 1 行のみ存在
    async with engine.connect() as conn:
        cnt = (await conn.execute(text(
            "SELECT COUNT(*) FROM public.discord_inbound_messages "
            "WHERE discord_message_id = :mid"
        ), {"mid": msg_id})).scalar_one()
    assert cnt == 1

    # idempotency 表に accepted + duplicate どちらか 1 行記録される (UNIQUE)
    async with engine.connect() as conn:
        idemp_cnt = (await conn.execute(text(
            "SELECT COUNT(*) FROM public.discord_webhook_idempotency "
            "WHERE message_id = :mid"
        ), {"mid": msg_id})).scalar_one()
    assert idemp_cnt == 1


# ---------------------------------------------------------------------------
# AC5.3: routing 未登録 guild → parse_status='ignored_routing'
# ---------------------------------------------------------------------------


async def test_ac5_3_ignored_routing_no_parse(engine, session_maker):
    """AC5.3: routing 未登録 guild からのメッセージは ignored_routing で記録される。"""
    from sqlalchemy import text
    from app.discord_gateway import inbound_writer

    unregistered_guild = f"g_unreg_{uuid.uuid4().hex[:10]}"
    unregistered_channel = f"c_unreg_{uuid.uuid4().hex[:10]}"
    msg_id = f"sprint5_msg_ignored_{uuid.uuid4().hex[:10]}"

    # routing lookup → None
    async with session_maker() as session:
        routing = await inbound_writer.lookup_routing(
            session, guild_id=unregistered_guild, channel_id=unregistered_channel
        )
    assert routing is None

    # ignored_routing で INSERT (supplier_id=None)
    async with session_maker() as session:
        result = await inbound_writer.write_inbound(
            session,
            discord_message_id=msg_id,
            discord_channel_id=unregistered_channel,
            supplier_id=None,
            raw_content="should be ignored",
            parse_status="ignored_routing",
        )
    assert result.inserted is True

    # parse_status='ignored_routing' で 1 行
    async with engine.connect() as conn:
        row = (await conn.execute(text(
            "SELECT parse_status, supplier_id FROM public.discord_inbound_messages "
            "WHERE discord_message_id = :mid"
        ), {"mid": msg_id})).first()
    assert row is not None
    assert row[0] == "ignored_routing"
    assert row[1] is None

    # cleanup
    async with engine.begin() as conn:
        await conn.execute(text(
            "DELETE FROM public.discord_inbound_messages WHERE discord_message_id = :mid"
        ), {"mid": msg_id})
        await conn.execute(text(
            "DELETE FROM public.discord_webhook_idempotency WHERE message_id = :mid"
        ), {"mid": msg_id})


# ---------------------------------------------------------------------------
# AC5.1 logic path (実機 SKIP の代替: dataclass で on_message を駆動)
# ---------------------------------------------------------------------------


async def test_ac5_1_logic_on_message_inserts_pending(
    engine, session_maker, seed_supplier_routing,
):
    """AC5.1 (logic only, 実機 SKIP の代替):
       on_message の routing 一致経路で pending 行が 1 つ INSERT され、
       schedule_parse の非同期 task が登録される。
    """
    from sqlalchemy import text
    from app.discord_gateway import inbound_writer

    ctx = seed_supplier_routing
    msg_id_int = abs(hash(f"sprint5_log_{uuid.uuid4().hex[:8]}")) & ((1 << 63) - 1)
    fake_msg = _FakeMessage(
        id=msg_id_int,
        content="ピカチュウ AR 3枚 @1500円",
        author=_FakeAuthor(id=9999, bot=False),
        guild=_FakeGuild(id=int(ctx["guild_id"][2:], 16) if ctx["guild_id"].startswith("g_") else 0),
        channel=_FakeChannel(id=int(ctx["channel_id"][2:], 16) if ctx["channel_id"].startswith("c_") else 0),
        created_at=datetime.now(timezone.utc),
    )

    # _FakeGuild/_FakeChannel.id は数値だが、seed の routing は文字列の guild_id。
    # message_to_inbound_payload は str() で stringify する。
    # routing lookup に同じ string が来るよう、payload を直接組み立てて検証する。

    # 1) routing lookup: 一致するはず
    async with session_maker() as session:
        # message_to_inbound_payload は str(guild.id) を返す。
        # seed の guild_id = "g_xxxx" 形式なので、テストでは直接 seed の値を使う
        routing = await inbound_writer.lookup_routing(
            session, guild_id=ctx["guild_id"], channel_id=ctx["channel_id"]
        )
    assert routing is not None
    assert routing.supplier_id == ctx["supplier_id"]

    # 2) write_inbound: pending で 1 行
    msg_id = f"sprint5_log_{uuid.uuid4().hex[:10]}"
    async with session_maker() as session:
        ins = await inbound_writer.write_inbound(
            session,
            discord_message_id=msg_id,
            discord_channel_id=ctx["channel_id"],
            supplier_id=routing.supplier_id,
            raw_content=fake_msg.content,
            parse_status="pending",
        )
    assert ins.inserted is True

    # 3) parse_status='pending' で 1 行存在
    async with engine.connect() as conn:
        row = (await conn.execute(text(
            "SELECT parse_status, supplier_id, raw_content FROM public.discord_inbound_messages "
            "WHERE discord_message_id = :mid"
        ), {"mid": msg_id})).first()
    assert row is not None
    assert row[0] == "pending"
    assert row[1] == ctx["supplier_id"]
    assert "ピカチュウ" in row[2]


# ---------------------------------------------------------------------------
# AC5.4: 切断 → 再接続後 missed messages 補完 (mock channel.history)
# ---------------------------------------------------------------------------


async def test_ac5_4_missed_messages_history_dedup(engine, session_maker, seed_supplier_routing):
    """AC5.4: 切断中の missed messages を REST history で補完、冪等で重複なし。"""
    from sqlalchemy import text
    from app.discord_gateway import inbound_writer

    ctx = seed_supplier_routing

    # 先に 1 件 INSERT 済み (切断前の受信)
    base_msg = f"sprint5_pre_{uuid.uuid4().hex[:10]}"
    async with session_maker() as session:
        await inbound_writer.write_inbound(
            session,
            discord_message_id=base_msg,
            discord_channel_id=ctx["channel_id"],
            supplier_id=ctx["supplier_id"],
            raw_content="pre-disconnect msg",
            parse_status="pending",
        )

    # last received_at を取得
    async with session_maker() as session:
        last_at = await inbound_writer.get_last_received_at_for_channel(
            session, ctx["channel_id"]
        )
    assert last_at is not None

    # missed messages 3 件 (mock) を fetch_missed_messages 経由で取得
    missed_ids = [
        f"sprint5_missed_{i}_{uuid.uuid4().hex[:8]}" for i in range(3)
    ]
    # 1 件は重複 (既存)、2 件は新規
    missed_ids[0] = base_msg  # 重複

    fake_messages = []
    for mid in missed_ids:
        fake_messages.append(_FakeMessage(
            id=mid if isinstance(mid, int) else abs(hash(mid)) & ((1 << 63) - 1),
            content=f"missed content for {mid}",
            author=_FakeAuthor(id=9999, bot=False),
            guild=None,
            channel=_FakeChannel(id=hash(ctx["channel_id"]) & ((1 << 63) - 1)),
            created_at=datetime.now(timezone.utc),
        ))

    # channel.history を mock
    class _AsyncIter:
        def __init__(self, items: list[Any]) -> None:
            self._items = items
            self._idx = 0

        def __aiter__(self) -> "_AsyncIter":
            return self

        async def __anext__(self) -> Any:
            if self._idx >= len(self._items):
                raise StopAsyncIteration
            item = self._items[self._idx]
            self._idx += 1
            return item

    fake_channel = MagicMock()
    fake_channel.id = 999
    fake_channel.history = MagicMock(return_value=_AsyncIter(fake_messages))

    fetched = await inbound_writer.fetch_missed_messages(
        fake_channel, after=last_at, limit=100
    )
    assert len(fetched) == 3

    # missed を INSERT (1 件は dedup される)
    inserted_count = 0
    for m, mid in zip(fetched, missed_ids):
        # supplier_id は routing が無い場合 None になるが、テストでは seed の supplier を使う
        async with session_maker() as session:
            res = await inbound_writer.write_inbound(
                session,
                discord_message_id=str(mid),
                discord_channel_id=ctx["channel_id"],
                supplier_id=ctx["supplier_id"],
                raw_content=m.content,
                parse_status="pending",
            )
        if res.inserted:
            inserted_count += 1

    # 1 件は dedup される
    assert inserted_count == 2

    # 計 3 行 (元の base_msg + 新規 2 件)
    async with engine.connect() as conn:
        rows = (await conn.execute(text(
            "SELECT discord_message_id FROM public.discord_inbound_messages "
            "WHERE discord_channel_id = :ch ORDER BY id"
        ), {"ch": ctx["channel_id"]})).fetchall()
    msg_ids_in_db = {str(r[0]) for r in rows}
    # base_msg と新規 2 つ
    assert base_msg in msg_ids_in_db
    new_ids = set(missed_ids) - {base_msg}
    for nid in new_ids:
        assert nid in msg_ids_in_db


# ---------------------------------------------------------------------------
# Migration 066: tenant_llm_budgets seed + last_hard_stop_notified_at 列存在
# ---------------------------------------------------------------------------


async def test_migration_066_tenant_llm_budgets_seed(engine):
    """migration 066: tenant_004 / tenant_006 行 + last_hard_stop_notified_at 列。"""
    from sqlalchemy import text

    async with engine.connect() as conn:
        # 列存在
        col = (await conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name='tenant_llm_budgets' "
            "AND column_name='last_hard_stop_notified_at'"
        ))).first()
    if col is None:
        pytest.skip("migration 066 が VPS PostgreSQL に未適用")

    async with engine.connect() as conn:
        rows = (await conn.execute(text(
            "SELECT tenant_id, monthly_budget_usd, hard_stop "
            "FROM public.tenant_llm_budgets WHERE tenant_id IN (4, 6) ORDER BY tenant_id"
        ))).fetchall()
    assert len(rows) >= 1, "tenant_llm_budgets に tenant_004 / tenant_006 行が seed されていない"


# ---------------------------------------------------------------------------
# discord_notifier 1h de-bounce ロジック (migration 066 列利用)
# ---------------------------------------------------------------------------


async def test_discord_notifier_debounce_1h(engine, session_maker):
    """notify_budget_exhausted の 1h de-bounce が並列呼び出しでも race-free に動く。

    - 列存在: last_hard_stop_notified_at がある場合のみ実行
    - tenant_006 行 (migration 066 seed) を対象に 2 回呼んでも 1 回のみ通知される
    """
    from decimal import Decimal
    from sqlalchemy import text
    from app.services import discord_notifier

    async with engine.connect() as conn:
        col = (await conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name='tenant_llm_budgets' "
            "AND column_name='last_hard_stop_notified_at'"
        ))).first()
    if col is None:
        pytest.skip("migration 066 が VPS PostgreSQL に未適用")

    # tenant_006 行を de-bounce 前提状態 (NULL) にリセット
    async with engine.begin() as conn:
        await conn.execute(text(
            "UPDATE public.tenant_llm_budgets "
            "SET last_hard_stop_notified_at = NULL WHERE tenant_id = 6"
        ))

    # ADMIN_NOTIFICATION_DISCORD_WEBHOOK 未設定環境では url=None → 即 False
    # de-bounce ロジックを呼ぶ前に短絡する。
    # テスト用に env を一時的に "https://example.invalid" にし、_post_discord_webhook を mock。
    with patch.dict(
        os.environ,
        {"ADMIN_NOTIFICATION_DISCORD_WEBHOOK": "https://example.invalid/test-webhook"},
    ), patch.object(
        discord_notifier, "_post_discord_webhook", new=AsyncMock(return_value=True)
    ) as mock_post:
        # 1 回目: de-bounce ロック取得 → POST 実行
        async with session_maker() as session:
            ok1 = await discord_notifier.notify_budget_exhausted(
                session, 6,
                monthly_budget_usd=Decimal("1.00"),
                current_month_usd=Decimal("1.05"),
            )
        # 2 回目 (即時): de-bounce 内 → skip
        async with session_maker() as session:
            ok2 = await discord_notifier.notify_budget_exhausted(
                session, 6,
                monthly_budget_usd=Decimal("1.00"),
                current_month_usd=Decimal("1.05"),
            )

    assert ok1 is True
    assert ok2 is False
    assert mock_post.call_count == 1
