import hashlib
import json
import logging
import os
from typing import Any

import redis.asyncio as redis

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

# JWT検証キャッシュ: 5分
JWT_CACHE_TTL = 300
# テナント情報キャッシュ: 10分
TENANT_CACHE_TTL = 600

_redis: redis.Redis | None = None


async def init_redis() -> None:
    """Redis接続を初期化する。"""
    global _redis
    try:
        _redis = redis.from_url(REDIS_URL, decode_responses=True)
        await _redis.ping()
        logger.info("Redis接続成功: %s", REDIS_URL)
    except Exception:
        logger.warning("Redis接続失敗: キャッシュなしで動作します")
        _redis = None


async def close_redis() -> None:
    """Redis接続を閉じる。"""
    global _redis
    if _redis:
        await _redis.aclose()
        _redis = None


def get_redis() -> redis.Redis | None:
    """現在のRedis接続を返す。未接続の場合はNone。"""
    return _redis


def _token_hash(token: str) -> str:
    """トークンのSHA-256ハッシュを返す（キーに使用）。"""
    return hashlib.sha256(token.encode()).hexdigest()


async def cache_jwt_result(token: str, user_data: dict) -> None:
    """JWT検証結果をキャッシュする。"""
    r = get_redis()
    if not r:
        return
    try:
        key = f"jwt:{_token_hash(token)}"
        await r.setex(key, JWT_CACHE_TTL, json.dumps(user_data))
    except Exception:
        logger.warning("JWTキャッシュ書き込み失敗")


async def get_cached_jwt(token: str) -> dict | None:
    """キャッシュ済みのJWT検証結果を取得する。"""
    r = get_redis()
    if not r:
        return None
    try:
        key = f"jwt:{_token_hash(token)}"
        data = await r.get(key)
        if data:
            return json.loads(data)
    except Exception:
        logger.warning("JWTキャッシュ読み取り失敗")
    return None


async def cache_tenant(tenant_id: int, is_active: bool) -> None:
    """テナント情報をキャッシュする。"""
    r = get_redis()
    if not r:
        return
    try:
        key = f"tenant:{tenant_id}"
        await r.setex(key, TENANT_CACHE_TTL, json.dumps({"is_active": is_active}))
    except Exception:
        logger.warning("テナントキャッシュ書き込み失敗")


async def get_cached_tenant(tenant_id: int) -> dict | None:
    """キャッシュ済みのテナント情報を取得する。"""
    r = get_redis()
    if not r:
        return None
    try:
        key = f"tenant:{tenant_id}"
        data = await r.get(key)
        if data:
            return json.loads(data)
    except Exception:
        logger.warning("テナントキャッシュ読み取り失敗")
    return None


async def blacklist_token(token: str, ttl: int = 3600) -> None:
    """トークンをブラックリストに追加する（ログアウト時）。"""
    r = get_redis()
    if not r:
        return
    try:
        key = f"blacklist:{_token_hash(token)}"
        await r.setex(key, ttl, "1")
    except Exception:
        logger.warning("ブラックリスト書き込み失敗")


async def is_token_blacklisted(token: str) -> bool:
    """トークンがブラックリストに含まれているか確認する。"""
    r = get_redis()
    if not r:
        return False
    try:
        key = f"blacklist:{_token_hash(token)}"
        return await r.exists(key) > 0
    except Exception:
        logger.warning("ブラックリスト確認失敗")
        return False
