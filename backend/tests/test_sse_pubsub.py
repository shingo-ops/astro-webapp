"""
SSE Pub/Sub モジュールのユニットテスト（Phase 2-3）。
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_publish_inbox_update_fails_gracefully():
    """Redis 障害時でも publish_inbox_update は例外を飲み込む（Webhook 継続）"""
    with patch("app.services.sse_pubsub.aioredis.from_url") as mock:
        mock.return_value.publish = AsyncMock(side_effect=ConnectionError("Redis down"))
        mock.return_value.aclose = AsyncMock()
        from app.services.sse_pubsub import publish_inbox_update

        # 例外が外に出ないことを確認
        await publish_inbox_update(tenant_id=1)  # 例外なし


@pytest.mark.asyncio
async def test_increment_decrement_connection():
    """接続数カウンターのインクリメント/デクリメントが正常動作する"""
    from app.services.sse_pubsub import _active, decrement_connection, increment_connection

    _active.clear()

    ok = await increment_connection(999)
    assert ok is True
    assert _active[999] == 1

    await decrement_connection(999)
    assert 999 not in _active  # 0 になったら削除


@pytest.mark.asyncio
async def test_increment_connection_limit():
    """SSE_MAX_CONN_PER_TENANT 超過時は False を返す"""
    from app.services.sse_pubsub import SSE_MAX_CONN_PER_TENANT, _active, increment_connection

    _active[888] = SSE_MAX_CONN_PER_TENANT

    ok = await increment_connection(888)
    assert ok is False

    _active.clear()


# ---------------------------------------------------------------------------
# Phase 3: leads Pub/Sub テスト
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_leads_update_fails_gracefully():
    """Redis 障害時でも publish_leads_update は例外を飲み込む（リード操作継続）"""
    with patch("app.services.sse_pubsub.aioredis.from_url") as mock:
        mock.return_value.publish = AsyncMock(side_effect=ConnectionError("Redis down"))
        mock.return_value.aclose = AsyncMock()
        from app.services.sse_pubsub import publish_leads_update

        await publish_leads_update(tenant_id=1)  # 例外なし


@pytest.mark.asyncio
async def test_leads_channel_naming():
    """leads チャンネル名が正しい形式"""
    from app.services.sse_pubsub import inbox_channel, leads_channel

    assert leads_channel(123) == "leads:123"
    assert inbox_channel(123) == "inbox:123"
