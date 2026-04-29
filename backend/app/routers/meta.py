"""
Meta Data Deletion Callback (B1-B5)

Meta App Review チェックリスト v1.1 §B 対応の認証不要エンドポイント。
仕様書: data_deletion_instructions.docx v1.0 / 設計書: docs/data_deletion_callback_design.md

- POST /api/v1/meta/data-deletion: Meta から署名付きリクエストを受信し削除処理を非同期 enqueue
- GET  /api/v1/meta/deletion-status: 確認コードからステータスを返却（公開、salesanchor.jp 経由）
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Form, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import text

from app.database import AsyncSessionLocal

router = APIRouter()
logger = logging.getLogger(__name__)

_PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "https://salesanchor.jp")
_CONFIRMATION_CODE_RE = re.compile(r"^DEL-\d{8}-[A-Za-z0-9]+$")


# ───────────────────────────────────────
# 内部ユーティリティ
# ───────────────────────────────────────

def _b64url_decode(data: str) -> bytes:
    """base64url のパディングを補完してデコードする。"""
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def parse_signed_request(signed_request: str, app_secret: str) -> Optional[dict]:
    """
    Meta signed_request をパースして HMAC-SHA256 検証する。

    signed_request の形式: "<sig_b64url>.<payload_b64url>"
    payload は JSON で {algorithm, issued_at, user_id} 等を含む。

    Returns:
        dict: 検証成功時の payload（user_id を含む）
        None: 形式不正 / 署名不一致 / payload 不正
    """
    if not signed_request or "." not in signed_request:
        return None

    try:
        sig_b64, payload_b64 = signed_request.split(".", 1)
    except ValueError:
        return None

    try:
        sig = _b64url_decode(sig_b64)
    except (ValueError, base64.binascii.Error):
        return None

    expected = hmac.new(
        app_secret.encode("utf-8"),
        payload_b64.encode("utf-8"),  # payload_b64 は base64url 文字列のまま署名対象
        hashlib.sha256,
    ).digest()

    if not hmac.compare_digest(sig, expected):
        return None

    try:
        payload_bytes = _b64url_decode(payload_b64)
        payload = json.loads(payload_bytes.decode("utf-8"))
    except (ValueError, json.JSONDecodeError):
        return None

    if payload.get("algorithm") != "HMAC-SHA256":
        return None
    if not payload.get("user_id"):
        return None

    return payload


def _generate_codes(now: datetime) -> tuple[str, str]:
    """REQ-YYYYMMDD-xxx と DEL-YYYYMMDD-xxxx を生成する。"""
    date_part = now.strftime("%Y%m%d")
    request_id = f"REQ-{date_part}-{secrets.token_hex(3)}"  # 6 hex chars
    confirmation_code = f"DEL-{date_part}-{secrets.token_hex(4)}"  # 8 hex chars
    return request_id, confirmation_code


# ───────────────────────────────────────
# POST /api/v1/meta/data-deletion (B1-B4)
# Meta Platform から signed_request を受信
# ───────────────────────────────────────

@router.post("/meta/data-deletion")
async def data_deletion_callback(
    signed_request: str = Form(""),
):
    """
    Meta Data Deletion Callback。

    1. signed_request を HMAC-SHA256 検証（App Secret = META_APP_SECRET）
    2. payload から user_id を取得
    3. data_deletion_logs に INSERT (status='received')
    4. Celery task で非同期に削除処理を enqueue
    5. Meta 仕様の unquoted JSON で応答（3 秒以内）

    Meta 仕様の unquoted JSON:
        { url: '...', confirmation_code: '...' }
    （標準 JSON ではなく JS オブジェクトリテラル形式。spec docx §2.3）
    """
    app_secret = os.getenv("META_APP_SECRET", "")
    if not app_secret:
        logger.error("[meta-data-deletion] META_APP_SECRET is not configured")
        raise HTTPException(status_code=500, detail="Server misconfigured")

    payload = parse_signed_request(signed_request, app_secret)
    if payload is None:
        logger.warning("[meta-data-deletion] Invalid signed_request")
        raise HTTPException(status_code=400, detail="Invalid signed_request")

    user_id = payload["user_id"]
    now = datetime.now(timezone.utc)
    request_id, confirmation_code = _generate_codes(now)

    # data_deletion_logs に受領記録を保存（status='received'）
    async with AsyncSessionLocal() as session:
        await session.execute(
            text("""
                INSERT INTO public.data_deletion_logs (
                    request_id, confirmation_code, channel, user_type,
                    identifier_type, identifier_value, requested_at,
                    status, handled_by
                )
                VALUES (
                    :request_id, :confirmation_code, 'meta_callback', 'end_user',
                    'meta_user_id', :user_id, :requested_at,
                    'received', 'meta_callback_auto'
                )
            """),
            {
                "request_id": request_id,
                "confirmation_code": confirmation_code,
                "user_id": str(user_id),
                "requested_at": now,
            },
        )
        await session.commit()

    # Celery task で非同期に削除処理（メール送信含む）
    # import を関数内にする: 循環 import 回避、Meta callback は最低限の依存で動く
    try:
        from app.tasks.data_deletion import process_data_deletion
        process_data_deletion.delay(request_id)
    except Exception as e:  # noqa: BLE001
        # 監査ログ記録は成功しているので Meta への応答は成功とする
        # 削除処理失敗は監査ログ status から手動リカバリ可能
        logger.error(f"[meta-data-deletion] enqueue failed: {e}", exc_info=True)

    # Meta 仕様の unquoted JSON 応答（template literal 相当）
    status_url = f"{_PUBLIC_BASE_URL}/deletion-status?code={confirmation_code}"
    body = f"{{ url: '{status_url}', confirmation_code: '{confirmation_code}' }}"
    return Response(content=body, media_type="application/json")


# ───────────────────────────────────────
# GET /api/v1/meta/deletion-status (B5 backend)
# 確認コードからステータスを返却（公開、CORS で salesanchor.jp 許可）
# ───────────────────────────────────────

@router.get("/meta/deletion-status")
async def deletion_status(code: str = Query(..., min_length=10, max_length=64)):
    """
    確認コード（DEL-YYYYMMDD-xxxx）から削除ステータスを返却。

    機密情報は返さない（identifier_value, error_message 等は除外）。
    """
    if not _CONFIRMATION_CODE_RE.match(code):
        raise HTTPException(status_code=400, detail="Invalid confirmation code format")

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("""
                SELECT
                    confirmation_code,
                    channel,
                    user_type,
                    status,
                    requested_at,
                    started_at,
                    completed_at
                FROM public.data_deletion_logs
                WHERE confirmation_code = :code
                LIMIT 1
            """),
            {"code": code},
        )
        row = result.first()

    if row is None:
        raise HTTPException(status_code=404, detail="Confirmation code not found")

    return {
        "confirmation_code": row[0],
        "channel": row[1],
        "user_type": row[2],
        "status": row[3],
        "requested_at": row[4].isoformat() if row[4] else None,
        "started_at": row[5].isoformat() if row[5] else None,
        "completed_at": row[6].isoformat() if row[6] else None,
    }
