"""
APIレート制限ミドルウェア（P2-2）。

認証済みユーザー: メールアドレス単位で 100回/分 を超えたら HTTP 429 を返す。
未認証リクエスト: IPアドレス単位で 60回/分 を超えたら HTTP 429 を返す。

Redis 不通時は制限を適用しない（fail-open）。
ヘルスチェック・静的ファイルは除外。
"""

import base64
import hashlib
import json
import logging
import time
from typing import Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

# 認証済みユーザー: 100回/分
AUTHED_RATE_LIMIT = 100
AUTHED_WINDOW_SEC = 60

# 未認証 IP: 60回/分（認証エンドポイントへの試行抑制）
UNAUTHED_RATE_LIMIT = 60
UNAUTHED_WINDOW_SEC = 60

# レート制限を適用しないパス
_SKIP_PATHS = ("/health", "/metrics", "/docs", "/openapi", "/static", "/api/health")


def _decode_jwt_email(auth_header: str | None) -> str | None:
    """Bearer トークンのペイロードから email を取得する（署名検証なし）。"""
    if not auth_header or not auth_header.startswith("Bearer "):
        return None
    try:
        token = auth_header[7:]
        payload_b64 = token.split(".")[1]
        padded = payload_b64 + "=" * (4 - len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        return payload.get("email")
    except Exception:
        return None


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def _check_rate_limit(identifier: str, limit: int, window_sec: int) -> bool:
    """レートリミットを確認し、超過時は True を返す。

    Returns:
        True  = 超過（429 を返すべき）
        False = 正常範囲内 or Redis 不通
    """
    try:
        from app.cache import get_redis
        r = get_redis()
        if not r:
            return False

        minute_bucket = int(time.time()) // window_sec
        key = f"rate:{hashlib.sha256(identifier.encode()).hexdigest()[:16]}:{minute_bucket}"
        count = await r.incr(key)
        if count == 1:
            await r.expire(key, window_sec + 5)

        return count > limit
    except Exception:
        logger.warning("レートリミット確認失敗: fail-openとして通過")
        return False


class RateLimitMiddleware(BaseHTTPMiddleware):
    """認証済みユーザー/IPアドレス単位のAPIレートリミット"""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path

        # 除外パスはスキップ
        if any(path.startswith(p) for p in _SKIP_PATHS):
            return await call_next(request)

        user_email = _decode_jwt_email(request.headers.get("Authorization"))

        if user_email:
            # 認証済みユーザー: メール単位で 100回/分
            exceeded = await _check_rate_limit(
                f"user:{user_email}", AUTHED_RATE_LIMIT, AUTHED_WINDOW_SEC
            )
        else:
            # 未認証: IP単位で 60回/分
            client_ip = _get_client_ip(request)
            exceeded = await _check_rate_limit(
                f"ip:{client_ip}", UNAUTHED_RATE_LIMIT, UNAUTHED_WINDOW_SEC
            )

        if exceeded:
            return JSONResponse(
                status_code=429,
                content={"detail": "リクエスト数が上限に達しました。しばらく時間をおいてから再試行してください"},
                headers={"Retry-After": str(AUTHED_WINDOW_SEC)},
            )

        return await call_next(request)
