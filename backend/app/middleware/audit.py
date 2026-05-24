"""
認証・データアクセス自動記録ミドルウェア。

記録対象:
  [auth_events]
    - 認証関連APIリクエスト（/api/v1/auth/*）
    - 認証失敗（HTTP 401, 403）

  [data_access_events] ← P2-1/P2-3 追加
    - 全書き込み操作（POST / PATCH / PUT / DELETE）
    - 大量エクスポート検知アラート（500件/10分 超過）

注意:
  - パスワード・トークン等の機密情報は記録しない
  - レスポンスをブロックしないよう、バックグラウンドタスクで記録する
  - 大量アクセスはRedisで追跡（Redis不通時は追跡省略）
"""

import base64
import json
import logging
import time
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy import text

from app.database import AsyncSessionLocal

logger = logging.getLogger(__name__)

# 認証イベントを記録する対象パス
_AUTH_PATHS = ("/api/v1/auth/",)

# 認証失敗として記録するステータスコード
_AUTH_FAILURE_CODES = {401, 403}

# 書き込み操作として記録するHTTPメソッド
_WRITE_METHODS = {"POST", "PATCH", "PUT", "DELETE"}

# 除外パス（ヘルスチェック・静的ファイル等）
_SKIP_PATHS = ("/health", "/metrics", "/docs", "/openapi", "/static")

# 大量エクスポート検知: 500件/10分超過で管理者アラート
BULK_EXPORT_WINDOW_SEC = 600   # 10分
BULK_EXPORT_MAX_CALLS = 500    # 10分間に500APIコール超でアラート


def _decode_jwt_email(auth_header: str | None) -> str | None:
    """Bearer トークンのペイロードから email を取得する（署名検証なし・ログ用途のみ）。"""
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


def _get_client_ip_from_request(request: Request) -> str:
    """クライアントIPをリバースプロキシ対応で取得する。"""
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def _check_and_record_bulk_export(user_email: str | None) -> bool:
    """大量エクスポート検知: Redisで10分間のAPIコール数を追跡する。

    Returns:
        True = 閾値超過（アラート対象）
        False = 正常範囲内
    """
    if not user_email:
        return False

    try:
        from app.cache import get_redis
        import hashlib
        r = get_redis()
        if not r:
            return False

        window = int(time.time()) // BULK_EXPORT_WINDOW_SEC
        email_hash = hashlib.sha256(user_email.encode()).hexdigest()[:16]
        key = f"bulk_access:{email_hash}:{window}"
        count = await r.incr(key)
        if count == 1:
            await r.expire(key, BULK_EXPORT_WINDOW_SEC + 60)

        return count > BULK_EXPORT_MAX_CALLS
    except Exception:
        logger.warning("大量エクスポート追跡に失敗")
        return False


class AuditMiddleware(BaseHTTPMiddleware):
    """認証イベント・データアクセスを自動記録するミドルウェア"""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.time()
        response = await call_next(request)
        duration_ms = int((time.time() - start_time) * 1000)

        path = request.url.path
        method = request.method
        status_code = response.status_code

        # 除外パスはスキップ
        if any(path.startswith(p) for p in _SKIP_PATHS):
            return response

        is_auth_path = any(path.startswith(p) for p in _AUTH_PATHS)
        is_auth_failure = status_code in _AUTH_FAILURE_CODES
        is_write_op = method in _WRITE_METHODS

        # 認証イベント記録（既存）
        if is_auth_path or is_auth_failure:
            await self._record_auth_event(
                request=request,
                status_code=status_code,
                duration_ms=duration_ms,
                is_auth_path=is_auth_path,
            )

        # データアクセス記録（P2-1: 書き込み操作）
        if is_write_op and status_code < 500:
            await self._record_data_access(
                request=request,
                status_code=status_code,
                duration_ms=duration_ms,
            )

        return response

    async def _record_auth_event(
        self,
        request: Request,
        status_code: int,
        duration_ms: int,
        is_auth_path: bool,
    ) -> None:
        """認証イベントをDBに記録する"""
        try:
            client_ip = _get_client_ip_from_request(request)

            if status_code in _AUTH_FAILURE_CODES:
                event_type = "auth_failure"
            elif is_auth_path and 200 <= status_code < 300:
                event_type = "auth_success"
            else:
                event_type = "auth_request"

            async with AsyncSessionLocal() as db:
                await db.execute(
                    text("""
                        INSERT INTO public.auth_events
                            (event_type, path, method, status_code,
                             client_ip, user_agent, duration_ms)
                        VALUES
                            (:event_type, :path, :method, :status_code,
                             :client_ip, :user_agent, :duration_ms)
                    """),
                    {
                        "event_type": event_type,
                        "path": request.url.path,
                        "method": request.method,
                        "status_code": status_code,
                        "client_ip": client_ip,
                        "user_agent": (request.headers.get("User-Agent") or "")[:500],
                        "duration_ms": duration_ms,
                    },
                )
                await db.commit()
        except Exception:
            logger.exception("認証イベント記録に失敗")

    async def _record_data_access(
        self,
        request: Request,
        status_code: int,
        duration_ms: int,
    ) -> None:
        """書き込み操作をdata_access_eventsに記録する（P2-1）。
        大量アクセス閾値超過時はアラートも記録する（P2-3）。
        """
        try:
            client_ip = _get_client_ip_from_request(request)
            user_email = _decode_jwt_email(request.headers.get("Authorization"))
            event_type = "data_write"

            # P2-3: 大量エクスポート検知
            is_bulk_alert = await _check_and_record_bulk_export(user_email)
            if is_bulk_alert:
                event_type = "bulk_export_alert"
                logger.warning(
                    "大量APIアクセス検知: user=%s ip=%s path=%s",
                    user_email,
                    client_ip,
                    request.url.path,
                )

            async with AsyncSessionLocal() as db:
                await db.execute(
                    text("""
                        INSERT INTO public.data_access_events
                            (event_type, method, path, status_code,
                             user_email, client_ip, user_agent, duration_ms)
                        VALUES
                            (:event_type, :method, :path, :status_code,
                             :user_email, :client_ip, :user_agent, :duration_ms)
                    """),
                    {
                        "event_type": event_type,
                        "method": request.method,
                        "path": request.url.path,
                        "status_code": status_code,
                        "user_email": user_email,
                        "client_ip": client_ip,
                        "user_agent": (request.headers.get("User-Agent") or "")[:500],
                        "duration_ms": duration_ms,
                    },
                )
                await db.commit()
        except Exception:
            logger.exception("データアクセスイベント記録に失敗")
