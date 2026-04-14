import hashlib
import json
import logging
import os
from typing import Optional

import redis.asyncio as redis

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

# JWT検証キャッシュ: 5分
JWT_CACHE_TTL = 300
# テナント情報キャッシュ: 10分
TENANT_CACHE_TTL = 600

_redis: Optional[redis.Redis] = None


async def init_redis() -> None:
    """Redis接続を初期化する。"""
    global _redis
    try:
        _redis = redis.from_url(REDIS_URL, decode_responses=True)
        await _redis.ping()
        logger.info("Redis接続成功: %s", REDIS_URL)
    except Exception:
        logger.critical("Redis接続失敗: ブラックリスト検証が無効になります")
        _redis = None


async def close_redis() -> None:
    """Redis接続を閉じる。"""
    global _redis
    if _redis:
        await _redis.aclose()
        _redis = None


def get_redis() -> Optional[redis.Redis]:
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


async def get_cached_jwt(token: str) -> Optional[dict]:
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


async def invalidate_jwt_cache(token: str) -> None:
    """JWT検証キャッシュを削除する（ログアウト時に使用）。"""
    r = get_redis()
    if not r:
        return
    try:
        key = f"jwt:{_token_hash(token)}"
        await r.delete(key)
    except Exception:
        logger.warning("JWTキャッシュ削除失敗")


async def invalidate_dashboard_cache(tenant_id: int) -> None:
    """ダッシュボードKPIキャッシュを削除する（顧客/商談/注文の変更時に呼ぶ）。"""
    r = get_redis()
    if not r:
        return
    try:
        await r.delete(f"dashboard_kpi:{tenant_id}")
    except Exception:
        logger.warning("ダッシュボードキャッシュ削除失敗")


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


async def get_cached_tenant(tenant_id: int) -> Optional[dict]:
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
    """トークンをブラックリストに追加し、JWTキャッシュも削除する（ログアウト時）。"""
    r = get_redis()
    if not r:
        logger.critical("Redis未接続: トークンのブラックリスト登録に失敗")
        return
    try:
        token_h = _token_hash(token)
        pipe = r.pipeline()
        pipe.setex(f"blacklist:{token_h}", ttl, "1")
        pipe.delete(f"jwt:{token_h}")
        await pipe.execute()
    except Exception:
        logger.critical("ブラックリスト書き込み失敗: トークン無効化が不完全")


async def is_token_blacklisted(token: str) -> bool:
    """
    トークンがブラックリストに含まれているか確認する。
    Redis障害時はfail-closed（安全側に倒してTrueを返す）。
    """
    r = get_redis()
    if not r:
        logger.critical("Redis未接続: ブラックリスト検証不能のためリクエスト拒否")
        return True
    try:
        key = f"blacklist:{_token_hash(token)}"
        return await r.exists(key) > 0
    except Exception:
        logger.critical("ブラックリスト確認失敗: 安全側に倒してリクエスト拒否")
        return True
