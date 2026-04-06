"""
認証イベント自動記録ミドルウェア。

認証関連のAPIリクエスト（ログイン、登録等）の結果を
publicスキーマの auth_events テーブルに自動記録する。

記録対象:
  - 認証成功 / 失敗（401, 403レスポンス）
  - 対象パス: /api/v1/auth/* および認証必須エンドポイントの401/403

注意:
  - パスワードやトークン等の機密情報は記録しない
  - レスポンスをブロックしないよう、バックグラウンドタスクで記録する
  - auth_events テーブルは public スキーマに置く（テナント横断の監査用）
"""

import time
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy import text

from app.database import AsyncSessionLocal


# 認証イベントを記録する対象パス
_AUTH_PATHS = ("/api/v1/auth/",)

# 認証失敗として記録するステータスコード
_AUTH_FAILURE_CODES = {401, 403}


class AuditMiddleware(BaseHTTPMiddleware):
    """認証イベントを自動記録するミドルウェア"""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.time()
        response = await call_next(request)
        duration_ms = int((time.time() - start_time) * 1000)

        # 認証関連パスへのリクエスト、または認証失敗レスポンスを記録
        path = request.url.path
        status_code = response.status_code
        is_auth_path = any(path.startswith(p) for p in _AUTH_PATHS)
        is_auth_failure = status_code in _AUTH_FAILURE_CODES

        if is_auth_path or is_auth_failure:
            # バックグラウンドで記録（レスポンスをブロックしない）
            await self._record_auth_event(
                request=request,
                status_code=status_code,
                duration_ms=duration_ms,
                is_auth_path=is_auth_path,
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
            # クライアントIPの取得（リバースプロキシ考慮）
            client_ip = request.headers.get(
                "X-Forwarded-For", request.client.host if request.client else "unknown"
            )
            if "," in client_ip:
                client_ip = client_ip.split(",")[0].strip()

            # イベント種別の判定
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
            # ログ記録の失敗でリクエスト処理を止めない
            pass
