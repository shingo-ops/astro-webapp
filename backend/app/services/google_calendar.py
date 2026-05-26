from __future__ import annotations

"""
Google Calendar OAuth 2.0 + Calendar API サービス。

担当範囲:
  - OAuth 認証 URL 生成（state 発行 → Google 同意画面 URL 返却）
  - code → access/refresh token 交換（OAuth callback）
  - アクセストークン自動更新（1時間失効 → refresh_token で更新）
  - テナント接続情報の DB 読み書き（Fernet 暗号化）
  - Calendar API CRUD（イベント一覧・作成・更新・削除）

設計判断:
  - テナント共通接続: 管理者が1回接続 → public.tenant_google_calendar_config に保存
    → 全スタッフが同一カレンダーを読み書き
  - OAuth State は `google_cal_oauth_state:` プレフィックスで Redis に保存（meta と分離）
  - トークンは METADATA_FERNET_KEY (shared Fernet key) で暗号化保存
  - google-auth-oauthlib の Flow を使い、googleapis REST API は googleapiclient で呼び出す

環境変数:
  GOOGLE_CALENDAR_CLIENT_ID        - OAuth 2.0 クライアント ID
  GOOGLE_CALENDAR_CLIENT_SECRET    - OAuth 2.0 クライアントシークレット
  GOOGLE_CALENDAR_REDIRECT_URI     - callback URL（Google Console に登録済み）
  METADATA_FERNET_KEY              - 暗号化鍵（Meta Inbox と共通）
"""

import json
import logging
import os
import secrets
from datetime import datetime, timezone
from typing import Optional

from app.cache import get_redis
from app.services import encryption

logger = logging.getLogger(__name__)

_SCOPES = ["https://www.googleapis.com/auth/calendar"]
_REDIS_KEY_PREFIX = "google_cal_oauth_state:"
_STATE_TTL_SECONDS = 600  # 10 分


# ---------------------------------------------------------------------------
# 環境変数ヘルパー
# ---------------------------------------------------------------------------


def _get_client_id() -> str:
    v = os.getenv("GOOGLE_CALENDAR_CLIENT_ID", "")
    if not v:
        raise RuntimeError("GOOGLE_CALENDAR_CLIENT_ID が未設定です")
    return v


def _get_client_secret() -> str:
    v = os.getenv("GOOGLE_CALENDAR_CLIENT_SECRET", "")
    if not v:
        raise RuntimeError("GOOGLE_CALENDAR_CLIENT_SECRET が未設定です")
    return v


def _get_redirect_uri() -> str:
    v = os.getenv("GOOGLE_CALENDAR_REDIRECT_URI", "")
    if not v:
        raise RuntimeError("GOOGLE_CALENDAR_REDIRECT_URI が未設定です")
    return v


# ---------------------------------------------------------------------------
# OAuth State（CSRF 防止）
# ---------------------------------------------------------------------------


async def issue_state(tenant_id: int, user_id: int) -> str:
    """CSRF 防止用 state を発行して Redis に保存する（10 分 TTL）。"""
    r = get_redis()
    if r is None:
        raise RuntimeError("Redis 未接続のため OAuth state を発行できません")

    state = secrets.token_urlsafe(32)
    payload = json.dumps(
        {"tenant_id": int(tenant_id), "user_id": int(user_id), "nonce": secrets.token_hex(8)},
        separators=(",", ":"),
    )
    encrypted = encryption.encrypt(payload)
    key = f"{_REDIS_KEY_PREFIX}{state}"
    await r.setex(key, _STATE_TTL_SECONDS, encrypted)
    return state


async def consume_state(state: str) -> Optional[dict]:
    """state を検証して payload を返す（同時に Redis から削除 → 1回限り使用）。"""
    if not state:
        return None
    r = get_redis()
    if r is None:
        raise RuntimeError("Redis 未接続のため OAuth state を検証できません")

    key = f"{_REDIS_KEY_PREFIX}{state}"
    async with r.pipeline(transaction=True) as pipe:
        pipe.get(key)
        pipe.delete(key)
        results = await pipe.execute()
    encrypted = results[0]
    if not encrypted:
        return None
    try:
        plain = encryption.decrypt(encrypted)
        return json.loads(plain)
    except Exception:
        logger.exception("Google Calendar OAuth state の復号 / parse に失敗")
        return None


# ---------------------------------------------------------------------------
# OAuth URL 生成
# ---------------------------------------------------------------------------


async def get_auth_url(tenant_id: int, user_id: int) -> str:
    """Google OAuth 同意画面 URL を生成する。"""
    from google_auth_oauthlib.flow import Flow  # type: ignore[import]

    state = await issue_state(tenant_id, user_id)
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": _get_client_id(),
                "client_secret": _get_client_secret(),
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [_get_redirect_uri()],
            }
        },
        scopes=_SCOPES,
        redirect_uri=_get_redirect_uri(),
    )
    flow.code_verifier = None  # PKCE 不使用（server-side flow）
    auth_url, _ = flow.authorization_url(
        state=state,
        access_type="offline",
        include_granted_scopes="false",
        prompt="consent",  # refresh_token を確実に取得するため毎回 consent を要求
    )
    return auth_url


# ---------------------------------------------------------------------------
# code → token 交換
# ---------------------------------------------------------------------------


async def exchange_code(code: str, state: str) -> dict:
    """認可コードを access_token / refresh_token と交換する。

    Returns:
        {
            "tenant_id": int,
            "user_id": int,
            "access_token": str,
            "refresh_token": str,
            "expiry": datetime | None,
        }

    Raises:
        ValueError: state が無効（CSRF 検出 or 期限切れ）
        RuntimeError: token 交換失敗
    """
    from google_auth_oauthlib.flow import Flow  # type: ignore[import]

    payload = await consume_state(state)
    if payload is None:
        raise ValueError("OAuth state が無効です（CSRF または期限切れ）")

    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": _get_client_id(),
                "client_secret": _get_client_secret(),
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [_get_redirect_uri()],
            }
        },
        scopes=_SCOPES,
        redirect_uri=_get_redirect_uri(),
        state=state,
    )
    try:
        flow.fetch_token(code=code)
    except Exception as e:
        raise RuntimeError(f"Google token 交換に失敗: {e}") from e

    creds = flow.credentials
    if not creds.refresh_token:
        raise RuntimeError(
            "refresh_token が取得できませんでした。Google Console で既存の接続を削除してから再接続してください"
        )

    expiry: Optional[datetime] = None
    if creds.expiry:
        expiry = creds.expiry.replace(tzinfo=timezone.utc) if creds.expiry.tzinfo is None else creds.expiry

    return {
        "tenant_id": payload["tenant_id"],
        "user_id": payload["user_id"],
        "access_token": creds.token,
        "refresh_token": creds.refresh_token,
        "expiry": expiry,
    }


# ---------------------------------------------------------------------------
# アクセストークン自動更新
# ---------------------------------------------------------------------------


def _build_credentials(access_token: str, refresh_token: str, expiry: Optional[datetime]):
    """google.oauth2.credentials.Credentials を生成する。"""
    from google.oauth2.credentials import Credentials  # type: ignore[import]

    return Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=_get_client_id(),
        client_secret=_get_client_secret(),
        scopes=_SCOPES,
        expiry=expiry,
    )


def _is_token_expired(expiry: Optional[datetime]) -> bool:
    if expiry is None:
        return True
    now = datetime.now(timezone.utc)
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    # 5 分バッファ（期限 5 分前に更新）
    from datetime import timedelta
    return now >= expiry - timedelta(minutes=5)


async def _refresh_if_needed(
    db,
    tenant_id: int,
    access_token_encrypted: str,
    refresh_token_encrypted: str,
    token_expiry: Optional[datetime],
) -> str:
    """アクセストークンが失効していれば refresh して DB を更新し、有効なアクセストークンを返す。"""
    access_token = encryption.decrypt(access_token_encrypted)
    refresh_token = encryption.decrypt(refresh_token_encrypted)

    if not _is_token_expired(token_expiry):
        return access_token

    from google.auth.transport.requests import Request  # type: ignore[import]

    creds = _build_credentials(access_token, refresh_token, token_expiry)
    try:
        creds.refresh(Request())
    except Exception as e:
        raise RuntimeError(f"アクセストークンの更新に失敗しました: {e}") from e

    new_access = creds.token
    new_expiry = creds.expiry
    if new_expiry and new_expiry.tzinfo is None:
        new_expiry = new_expiry.replace(tzinfo=timezone.utc)

    from sqlalchemy import text

    await db.execute(
        text(
            "UPDATE tenant_google_calendar_config"
            " SET access_token_encrypted = :at, token_expiry = :exp, updated_at = NOW()"
            " WHERE tenant_id = :tid"
        ),
        {
            "at": encryption.encrypt(new_access),
            "exp": new_expiry,
            "tid": tenant_id,
        },
    )
    await db.commit()
    return new_access


# ---------------------------------------------------------------------------
# Calendar API: イベント CRUD
# ---------------------------------------------------------------------------


async def _get_service(db, tenant_id: int):
    """Calendar API サービスオブジェクトを返す（トークン自動更新込み）。"""
    from googleapiclient.discovery import build  # type: ignore[import]
    from sqlalchemy import text

    row = await db.execute(
        text(
            "SELECT access_token_encrypted, refresh_token_encrypted, token_expiry"
            " FROM tenant_google_calendar_config"
            " WHERE tenant_id = :tid"
        ),
        {"tid": tenant_id},
    )
    record = row.first()
    if record is None:
        raise RuntimeError("Google Calendar が接続されていません")

    access_token = await _refresh_if_needed(
        db,
        tenant_id,
        record[0],
        record[1],
        record[2],
    )
    refresh_token = encryption.decrypt(record[1])

    creds = _build_credentials(access_token, refresh_token, None)
    service = build("calendar", "v3", credentials=creds, cache_discovery=False)
    return service


async def get_calendar_id(db, tenant_id: int) -> str:
    """テナント設定の calendar_id を取得する（デフォルト 'primary'）。"""
    from sqlalchemy import text

    row = await db.execute(
        text("SELECT calendar_id FROM tenant_google_calendar_config WHERE tenant_id = :tid"),
        {"tid": tenant_id},
    )
    record = row.first()
    if record is None:
        return "primary"
    return record[0] or "primary"


async def get_events(db, tenant_id: int, *, time_min: str, time_max: str) -> list[dict]:
    """指定期間のカレンダーイベント一覧を返す。

    Args:
        time_min: RFC 3339 形式（例 "2025-05-01T00:00:00Z"）
        time_max: RFC 3339 形式
    """
    service = await _get_service(db, tenant_id)
    calendar_id = await get_calendar_id(db, tenant_id)

    try:
        result = (
            service.events()
            .list(
                calendarId=calendar_id,
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy="startTime",
                maxResults=500,
            )
            .execute()
        )
    except Exception as e:
        raise RuntimeError(f"イベント取得に失敗: {e}") from e

    return result.get("items", [])


async def create_event(db, tenant_id: int, event_body: dict) -> dict:
    """イベントを作成して Google Calendar API レスポンスを返す。"""
    service = await _get_service(db, tenant_id)
    calendar_id = await get_calendar_id(db, tenant_id)

    try:
        return (
            service.events()
            .insert(calendarId=calendar_id, body=event_body)
            .execute()
        )
    except Exception as e:
        raise RuntimeError(f"イベント作成に失敗: {e}") from e


async def update_event(db, tenant_id: int, event_id: str, event_body: dict) -> dict:
    """イベントを更新して Google Calendar API レスポンスを返す。"""
    service = await _get_service(db, tenant_id)
    calendar_id = await get_calendar_id(db, tenant_id)

    try:
        return (
            service.events()
            .patch(calendarId=calendar_id, eventId=event_id, body=event_body)
            .execute()
        )
    except Exception as e:
        raise RuntimeError(f"イベント更新に失敗: {e}") from e


async def delete_event(db, tenant_id: int, event_id: str) -> None:
    """イベントを削除する。"""
    service = await _get_service(db, tenant_id)
    calendar_id = await get_calendar_id(db, tenant_id)

    try:
        service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
    except Exception as e:
        raise RuntimeError(f"イベント削除に失敗: {e}") from e


__all__ = [
    "issue_state",
    "consume_state",
    "get_auth_url",
    "exchange_code",
    "get_events",
    "create_event",
    "update_event",
    "delete_event",
]
