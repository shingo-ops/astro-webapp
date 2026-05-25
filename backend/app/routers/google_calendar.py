from __future__ import annotations

"""
Google Calendar 連携エンドポイント。

Public（認証不要）:
  GET  /google-calendar/connect/callback  — Google OAuth callback（Bearerトークン不要）
  POST /google-calendar/webhook           — Push Notification 受信（Google から Bearer なし）

Tenant 認証必須:
  GET    /google-calendar/connect/start     — OAuth URL 返却（admin のみ）
  DELETE /google-calendar/connect           — 接続解除（admin のみ）
  GET    /google-calendar/status            — 接続状態確認
  GET    /google-calendar/events            — イベント一覧
  POST   /google-calendar/events            — イベント作成
  PATCH  /google-calendar/events/{id}       — イベント更新
  DELETE /google-calendar/events/{id}       — イベント削除
"""

import logging
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import (
    get_current_tenant,
    get_current_user,
    reset_tenant_context,
)
from app.database import get_db
from app.models import User
from app.services import google_calendar as cal_svc

logger = logging.getLogger(__name__)

# Public ルーター（main.py で認証なしに登録）
public_router = APIRouter()

# 認証必須ルーター（main.py で get_current_tenant 付きに登録）
router = APIRouter()


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------


def _frontend_base_url() -> str:
    explicit = os.getenv("FRONTEND_BASE_URL", "")
    if explicit:
        return explicit.rstrip("/")
    origins = os.getenv("ALLOWED_ORIGINS", "")
    first = next((o.strip() for o in origins.split(",") if o.strip()), "")
    return (first or "https://app.salesanchor.jp").rstrip("/")


def _require_admin(user: User) -> None:
    if getattr(user, "role", None) != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="この操作は管理者のみ実行できます",
        )


# ---------------------------------------------------------------------------
# Pydantic モデル
# ---------------------------------------------------------------------------


class EventBody(BaseModel):
    summary: str
    start: dict  # {"dateTime": "...", "timeZone": "..."}
    end: dict
    description: Optional[str] = None
    location: Optional[str] = None


class EventPatchBody(BaseModel):
    summary: Optional[str] = None
    start: Optional[dict] = None
    end: Optional[dict] = None
    description: Optional[str] = None
    location: Optional[str] = None


# ---------------------------------------------------------------------------
# Public: OAuth callback（Google から Bearer なしでリダイレクト）
# ---------------------------------------------------------------------------


@public_router.get(
    "/google-calendar/connect/callback",
    tags=["google-calendar"],
    include_in_schema=False,  # Swagger から隠す（public 且つ redirect のため）
)
async def connect_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Google から認可コードを受け取り、トークンを DB に保存する。

    この endpoint は Bearer トークンなしで Google からリダイレクトされるため
    public_router（認証なし）に属する。state 検証でテナントを特定する。
    """
    frontend_schedule = f"{_frontend_base_url()}/schedule"

    try:
        result = await cal_svc.exchange_code(code, state)
    except ValueError as e:
        logger.warning("Google Calendar callback: state 検証失敗 %s", e)
        return RedirectResponse(f"{frontend_schedule}?connected=false&error=invalid_state")
    except RuntimeError as e:
        logger.error("Google Calendar callback: token 交換失敗 %s", e)
        return RedirectResponse(f"{frontend_schedule}?connected=false&error=token_exchange")

    tenant_id = result["tenant_id"]
    user_id = result["user_id"]
    from app.services.encryption import encrypt

    access_enc = encrypt(result["access_token"])
    refresh_enc = encrypt(result["refresh_token"])
    expiry = result["expiry"]

    try:
        await db.execute(
            text(
                """
                INSERT INTO tenant_google_calendar_config
                  (tenant_id, access_token_encrypted, refresh_token_encrypted,
                   token_expiry, connected_by_user_id, connected_at, updated_at)
                VALUES
                  (:tid, :at, :rt, :exp, :uid, NOW(), NOW())
                ON CONFLICT (tenant_id) DO UPDATE SET
                  access_token_encrypted  = EXCLUDED.access_token_encrypted,
                  refresh_token_encrypted = EXCLUDED.refresh_token_encrypted,
                  token_expiry            = EXCLUDED.token_expiry,
                  connected_by_user_id    = EXCLUDED.connected_by_user_id,
                  connected_at            = NOW(),
                  updated_at              = NOW()
                """
            ),
            {"tid": tenant_id, "at": access_enc, "rt": refresh_enc, "exp": expiry, "uid": user_id},
        )
        await db.commit()
        await reset_tenant_context(db, tenant_id)  # ADR-072 Phase 2.5
    except Exception as e:
        await db.rollback()
        logger.error("Google Calendar callback: DB 保存失敗 %s", e)
        return RedirectResponse(f"{frontend_schedule}?connected=false&error=db_error")

    return RedirectResponse(f"{frontend_schedule}?connected=true")


# ---------------------------------------------------------------------------
# Authenticated: 接続開始
# ---------------------------------------------------------------------------


@router.get(
    "/google-calendar/connect/start",
    tags=["google-calendar"],
)
async def connect_start(
    tenant_id: int = Depends(get_current_tenant),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Google OAuth 同意画面の URL を返す（admin 専用）。"""
    _require_admin(user)

    try:
        auth_url = await cal_svc.get_auth_url(tenant_id, user.id)
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )

    return {"auth_url": auth_url}


# ---------------------------------------------------------------------------
# Authenticated: 接続解除
# ---------------------------------------------------------------------------


@router.delete(
    "/google-calendar/connect",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["google-calendar"],
)
async def disconnect(
    tenant_id: int = Depends(get_current_tenant),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Google Calendar 接続を解除する（admin 専用）。"""
    _require_admin(user)

    await db.execute(
        text("DELETE FROM tenant_google_calendar_config WHERE tenant_id = :tid"),
        {"tid": tenant_id},
    )
    await db.commit()
    await reset_tenant_context(db, tenant_id)  # ADR-072 Phase 2.5


# ---------------------------------------------------------------------------
# Authenticated: 接続状態確認
# ---------------------------------------------------------------------------


@router.get(
    "/google-calendar/status",
    tags=["google-calendar"],
)
async def connection_status(
    tenant_id: int = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """テナントの Google Calendar 接続状態を返す。"""
    row = await db.execute(
        text(
            "SELECT calendar_id, connected_at FROM tenant_google_calendar_config"
            " WHERE tenant_id = :tid"
        ),
        {"tid": tenant_id},
    )
    record = row.first()
    if record is None:
        # 一度も連携したことがない
        return {"connected": False, "configured": False, "calendar_id": None}

    return {
        "connected": True,
        "configured": True,
        "calendar_id": record[0],
        "connected_at": record[1].isoformat() if record[1] else None,
    }


# ---------------------------------------------------------------------------
# Authenticated: イベント一覧
# ---------------------------------------------------------------------------


@router.get(
    "/google-calendar/events",
    tags=["google-calendar"],
)
async def list_events(
    start: str = Query(..., description="RFC 3339 形式 例: 2025-05-01T00:00:00Z"),
    end: str = Query(..., description="RFC 3339 形式 例: 2025-05-31T23:59:59Z"),
    tenant_id: int = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """指定期間のカレンダーイベント一覧を返す。"""
    try:
        events = await cal_svc.get_events(db, tenant_id, time_min=start, time_max=end)
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(e),
        )
    return {"events": events}


# ---------------------------------------------------------------------------
# Authenticated: イベント作成
# ---------------------------------------------------------------------------


@router.post(
    "/google-calendar/events",
    status_code=status.HTTP_201_CREATED,
    tags=["google-calendar"],
)
async def create_event(
    body: EventBody,
    tenant_id: int = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """カレンダーにイベントを作成する。"""
    event_body = body.model_dump(exclude_none=True)
    try:
        created = await cal_svc.create_event(db, tenant_id, event_body)
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(e),
        )
    return created


# ---------------------------------------------------------------------------
# Authenticated: イベント更新
# ---------------------------------------------------------------------------


@router.patch(
    "/google-calendar/events/{event_id}",
    tags=["google-calendar"],
)
async def update_event(
    event_id: str,
    body: EventPatchBody,
    tenant_id: int = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """カレンダーのイベントを部分更新する。"""
    event_body = body.model_dump(exclude_none=True)
    if not event_body:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="更新フィールドが指定されていません",
        )
    try:
        updated = await cal_svc.update_event(db, tenant_id, event_id, event_body)
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(e),
        )
    return updated


# ---------------------------------------------------------------------------
# Authenticated: イベント削除
# ---------------------------------------------------------------------------


@router.delete(
    "/google-calendar/events/{event_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["google-calendar"],
)
async def delete_event(
    event_id: str,
    tenant_id: int = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """カレンダーのイベントを削除する。"""
    try:
        await cal_svc.delete_event(db, tenant_id, event_id)
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(e),
        )


# ---------------------------------------------------------------------------
# Public: Google Calendar Webhook 受信
# ---------------------------------------------------------------------------


@public_router.post(
    "/google-calendar/webhook",
    tags=["google-calendar"],
    include_in_schema=False,  # Google から Bearer なしで POST されるため public
)
async def receive_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Google Calendar Push Notification を受信してイベント差分を DB に反映する。

    Google はこのエンドポイントに Bearer トークンなしで POST するため
    public_router（認証なし）に属する。
    テナントの特定は X-Goog-Channel-ID → google_webhook_subscriptions で行う。
    """
    channel_id = request.headers.get("X-Goog-Channel-ID", "")
    resource_state = request.headers.get("X-Goog-Resource-State", "")

    if not channel_id:
        # 不明なチャンネルは 200 を返して無視（Google がリトライしないようにするため）
        return JSONResponse(status_code=200, content={"ok": True})

    from app.services import google_webhook as webhook_svc

    try:
        await webhook_svc.handle_webhook_notification(db, channel_id, resource_state)
    except Exception as e:
        logger.error("Webhook 処理エラー (channel=%s): %s", channel_id, e)
        # Google には常に 200 を返す（5xx を返すと通知チャンネルが無効化される）

    return JSONResponse(status_code=200, content={"ok": True})
