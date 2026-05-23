"""
セッションハイジャック検知ミドルウェア（P4・縮小版）。

設計方針:
  - IP変更はログ記録のみ（誤検知防止: モバイル/VPN/企業NAT）
  - 「物理的に不可能な移動」のみ強制再認証
    例: 東京 → ヨーロッパに5分以内でアクセス（光速を超える移動）
  - ASN（ISP）の変化も記録するが、強制再認証は発動しない

実装手段:
  - JWT の token ハッシュをセッション識別子として使用
  - 前回のIPをRedisに保存（TTL: 1時間）
  - 前回IPと現在IPの /8 プレフィックスを比較（簡易的な地域推定）
  - プレフィックス急変 + 短時間（5分以内）= 強制再認証

注意:
  - Redis 不通時は fail-open（全ユーザーを通す）
  - 誤検知リスクを最小化するため、判定は保守的に設定
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

# セッション追跡の有効期間: 1時間
SESSION_IP_TTL = 3600

# 「物理的に不可能な移動」判定: この秒数以内にIPプレフィックスが変わったら強制再認証
IMPOSSIBLE_TRAVEL_WINDOW_SEC = 300  # 5分

# セッションハイジャック検知を適用しないパス
_SKIP_PATHS = ("/health", "/metrics", "/docs", "/openapi", "/static", "/api/health")


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _ip_prefix_8(ip: str) -> str:
    """IPアドレスの /8 プレフィックスを返す（簡易的な地域推定）。

    同じ /8 ブロックなら同じ大陸・国という粗い近似。
    IPv6 は先頭 2 セグメントで比較。
    """
    try:
        if ":" in ip:
            parts = ip.split(":")
            return ":".join(parts[:2])
        else:
            return ip.split(".")[0]
    except Exception:
        return ip


async def _check_session_ip(token_hash: str, current_ip: str) -> bool:
    """セッションのIPを確認し、物理的に不可能な移動を検知する。

    Returns:
        True  = 強制再認証が必要（物理的に不可能な移動を検知）
        False = 正常 or Redis 不通 or 判定不能
    """
    try:
        from app.cache import get_redis
        r = get_redis()
        if not r:
            return False

        session_key = f"session_ip:{token_hash}"
        stored = await r.get(session_key)
        current_prefix = _ip_prefix_8(current_ip)
        current_ts = int(time.time())

        if stored:
            data = json.loads(stored)
            prev_prefix = data.get("prefix", "")
            prev_ts = data.get("ts", 0)
            prev_ip = data.get("ip", "")

            if prev_prefix and prev_prefix != current_prefix:
                elapsed = current_ts - prev_ts
                logger.info(
                    "セッションIP変化を検知: token=%s prev=%s current=%s elapsed=%ds",
                    token_hash[:8],
                    prev_ip,
                    current_ip,
                    elapsed,
                )

                if elapsed < IMPOSSIBLE_TRAVEL_WINDOW_SEC:
                    logger.warning(
                        "物理的に不可能な移動を検知（強制再認証）: token=%s prev=%s(%s) "
                        "current=%s(%s) elapsed=%ds",
                        token_hash[:8],
                        prev_ip,
                        prev_prefix,
                        current_ip,
                        current_prefix,
                        elapsed,
                    )
                    return True

        # 現在のIPを記録（TTLをリセット）
        await r.setex(
            session_key,
            SESSION_IP_TTL,
            json.dumps({"ip": current_ip, "prefix": current_prefix, "ts": current_ts}),
        )
        return False
    except Exception:
        logger.warning("セッションIP確認失敗: fail-openとして通過")
        return False


class SessionGuardMiddleware(BaseHTTPMiddleware):
    """セッションハイジャック検知（物理的に不可能な移動のみ強制再認証）"""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path

        # 除外パスはスキップ
        if any(path.startswith(p) for p in _SKIP_PATHS):
            return await call_next(request)

        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return await call_next(request)

        # JWTのハッシュをセッション識別子として使用
        token = auth_header[7:]
        token_hash = hashlib.sha256(token.encode()).hexdigest()[:24]
        client_ip = _get_client_ip(request)

        # セッションIP確認（物理的に不可能な移動を検知）
        if await _check_session_ip(token_hash, client_ip):
            return JSONResponse(
                status_code=401,
                content={
                    "detail": "セッションの安全性を確保するため、再度ログインしてください",
                    "code": "SESSION_COMPROMISED",
                },
            )

        return await call_next(request)
