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
# ユーザー権限キャッシュ: 5分
PERMISSIONS_CACHE_TTL = 300

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


async def blacklist_token(token: str, ttl: int = 3600) -> bool:
    """トークンをブラックリストに追加し、JWTキャッシュも削除する（ログアウト時）。

    Returns:
        True  - ブラックリスト登録成功
        False - Redis未接続または書き込み失敗（呼び出し元で503を返すこと）
    """
    r = get_redis()
    if not r:
        logger.critical("Redis未接続: トークンのブラックリスト登録に失敗")
        return False
    try:
        token_h = _token_hash(token)
        pipe = r.pipeline()
        pipe.setex(f"blacklist:{token_h}", ttl, "1")
        pipe.delete(f"jwt:{token_h}")
        await pipe.execute()
        return True
    except Exception:
        logger.critical("ブラックリスト書き込み失敗: トークン無効化が不完全")
        return False


async def cache_user_permissions(tenant_id: int, user_id: int, keys: set[str]) -> None:
    """
    ユーザーの有効パーミッション（文字列キーの集合）をキャッシュする。
    キー: perms:{tenant_id}:{user_id}
    """
    r = get_redis()
    if not r:
        return
    try:
        key = f"perms:{tenant_id}:{user_id}"
        await r.setex(key, PERMISSIONS_CACHE_TTL, json.dumps(sorted(keys)))
    except Exception:
        logger.warning("パーミッションキャッシュ書き込み失敗")


async def get_cached_user_permissions(tenant_id: int, user_id: int) -> Optional[set[str]]:
    """
    キャッシュ済みのユーザー権限セットを取得する。
    キャッシュミス時はNone。
    """
    r = get_redis()
    if not r:
        return None
    try:
        key = f"perms:{tenant_id}:{user_id}"
        data = await r.get(key)
        if data:
            return set(json.loads(data))
    except Exception:
        logger.warning("パーミッションキャッシュ読み取り失敗")
    return None


async def invalidate_user_permissions(tenant_id: int, user_id: int) -> None:
    """特定ユーザーの権限キャッシュを削除する（ロール付与/剥奪時に呼ぶ）。"""
    r = get_redis()
    if not r:
        return
    try:
        await r.delete(f"perms:{tenant_id}:{user_id}")
    except Exception:
        logger.warning("パーミッションキャッシュ削除失敗")


async def invalidate_tenant_permissions(tenant_id: int) -> None:
    """
    テナント内全ユーザーの権限キャッシュを削除する
    （ロールの権限構成を変更した時に呼ぶ）。
    SCANベースで対象キーを列挙→削除。
    """
    r = get_redis()
    if not r:
        return
    try:
        pattern = f"perms:{tenant_id}:*"
        # Redisの非同期 scan_iter を利用してまとめて削除
        async for key in r.scan_iter(match=pattern, count=100):
            await r.delete(key)
    except Exception:
        logger.warning("テナント権限キャッシュ一括削除失敗")


# === ブルートフォース対策 ===
# 認証失敗: IP単位、10回で15分ロック（Firebase token validation failure）
AUTH_FAIL_MAX = 10
AUTH_FAIL_LOCKOUT_TTL = 900  # 15分
# 登録失敗: Email単位、5回で30分ロック（メールアドレス列挙攻撃対策）
REGISTER_FAIL_MAX = 5
REGISTER_FAIL_LOCKOUT_TTL = 1800  # 30分


async def check_auth_rate_limit(ip: str) -> bool:
    """IPアドレス単位の認証失敗レートリミットを確認する。True=ロック中。

    Redis不通時はfail-open（サービス継続優先）。
    """
    r = get_redis()
    if not r:
        return False
    try:
        key = f"auth_fail_ip:{hashlib.sha256(ip.encode()).hexdigest()[:16]}"
        count = await r.get(key)
        return int(count or 0) >= AUTH_FAIL_MAX
    except Exception:
        logger.warning("auth_rate_limit確認失敗: fail-openとして通過")
        return False


async def record_auth_failure(ip: str) -> None:
    """認証失敗をIPアドレスに記録する。"""
    r = get_redis()
    if not r:
        return
    try:
        key = f"auth_fail_ip:{hashlib.sha256(ip.encode()).hexdigest()[:16]}"
        count = await r.incr(key)
        if count == 1:
            await r.expire(key, AUTH_FAIL_LOCKOUT_TTL)
    except Exception:
        logger.warning("認証失敗記録に失敗")


async def check_register_rate_limit(email: str) -> bool:
    """メールアドレス単位の登録失敗レートリミットを確認する。True=ロック中。

    メール列挙攻撃（同じメールで重複登録を繰り返し409を確認する手法）を防ぐ。
    Redis不通時はfail-open。
    """
    r = get_redis()
    if not r:
        return False
    try:
        key = f"reg_fail_email:{hashlib.sha256(email.lower().encode()).hexdigest()[:16]}"
        count = await r.get(key)
        return int(count or 0) >= REGISTER_FAIL_MAX
    except Exception:
        logger.warning("register_rate_limit確認失敗: fail-openとして通過")
        return False


async def record_register_failure(email: str) -> None:
    """メールアドレス単位の登録失敗（重複）を記録する。"""
    r = get_redis()
    if not r:
        return
    try:
        key = f"reg_fail_email:{hashlib.sha256(email.lower().encode()).hexdigest()[:16]}"
        count = await r.incr(key)
        if count == 1:
            await r.expire(key, REGISTER_FAIL_LOCKOUT_TTL)
    except Exception:
        logger.warning("登録失敗記録に失敗")


async def is_token_blacklisted(token: str) -> bool:
    """
    トークンがブラックリストに含まれているか確認する。
    Redis障害時はfail-open（サービス継続優先）。
    ログアウト済みトークンが誤通過するリスクより全ユーザー401のリスクを優先回避。
    """
    r = get_redis()
    if not r:
        logger.warning("Redis未接続: ブラックリスト検証をスキップして認証を継続")
        return False
    try:
        key = f"blacklist:{_token_hash(token)}"
        return await r.exists(key) > 0
    except Exception:
        logger.warning("ブラックリスト確認失敗: fail-openとして認証を継続")
        return False
