"""
SSE 用 Redis Pub/Sub 管理（Phase 2-3）。
DB3 専用。チャンネル: inbox:{tenant_id} / leads:{tenant_id}
"""
from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

# DB3 を SSE 専用に割り当て
# REDIS_URL が redis://:pass@host:6379/0 形式でも /0 → /3 に置換
_base = os.getenv("REDIS_URL", "redis://redis:6379/0")
SSE_REDIS_URL = _base.rsplit("/", 1)[0] + "/3"

SSE_MAX_CONN_PER_TENANT = int(os.getenv("SSE_MAX_CONNECTIONS_PER_TENANT", "10"))

_active: dict[int, int] = {}
_lock = asyncio.Lock()


async def increment_connection(tenant_id: int) -> bool:
    async with _lock:
        n = _active.get(tenant_id, 0)
        if n >= SSE_MAX_CONN_PER_TENANT:
            logger.warning("SSE接続数上限: tenant_id=%s current=%d", tenant_id, n)
            return False
        _active[tenant_id] = n + 1
        return True


async def decrement_connection(tenant_id: int) -> None:
    async with _lock:
        n = _active.get(tenant_id, 0)
        if n > 1:
            _active[tenant_id] = n - 1
        else:
            _active.pop(tenant_id, None)  # 0 or 1 → remove entry


def inbox_channel(tenant_id: int) -> str:
    return f"inbox:{tenant_id}"


def leads_channel(tenant_id: int) -> str:
    return f"leads:{tenant_id}"


async def _publish(ch: str, tenant_id: int, label: str) -> None:
    """汎用 publish ヘルパー。fail-open: Redis 障害時はログのみ。"""
    try:
        r = aioredis.from_url(SSE_REDIS_URL, decode_responses=True)
        try:
            await r.publish(ch, "update")
        finally:
            await r.aclose()
    except Exception:
        logger.warning(
            "SSE publish失敗（%s継続）: tenant_id=%s", label, tenant_id, exc_info=True
        )


async def _subscribe(ch: str) -> AsyncIterator[None]:
    """汎用 subscribe ジェネレータ。呼び出し元で gen.aclose() を必ず実行すること。"""
    r = aioredis.from_url(SSE_REDIS_URL, decode_responses=True)
    pubsub = r.pubsub()
    try:
        await pubsub.subscribe(ch)
        async for msg in pubsub.listen():
            if msg["type"] == "message":
                yield None
    finally:
        await pubsub.aclose()
        await r.aclose()


async def publish_inbox_update(tenant_id: int) -> None:
    """Webhook 処理から呼ぶ。Redis 障害時はログのみで Webhook 継続（fail-open）。"""
    await _publish(inbox_channel(tenant_id), tenant_id, "Webhook")


async def subscribe_inbox(tenant_id: int) -> AsyncIterator[None]:
    """SSE エンドポイントから呼ぶ非同期ジェネレータ。"""
    async for _ in _subscribe(inbox_channel(tenant_id)):
        yield None


async def publish_leads_update(tenant_id: int) -> None:
    """leads.py の create/update/delete から呼ぶ。fail-open。"""
    await _publish(leads_channel(tenant_id), tenant_id, "リード更新")


async def subscribe_leads(tenant_id: int) -> AsyncIterator[None]:
    """SSE エンドポイントから呼ぶ非同期ジェネレータ。"""
    async for _ in _subscribe(leads_channel(tenant_id)):
        yield None
