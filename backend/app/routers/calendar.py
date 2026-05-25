from __future__ import annotations

"""
アプリ内カレンダー CRUD エンドポイント。

エンドポイント一覧:
  GET    /calendar/events         — イベント一覧（期間・タイプ指定）
  POST   /calendar/events         — イベント作成（DB保存 → Google同期）
  PATCH  /calendar/events/{id}    — イベント更新
  DELETE /calendar/events/{id}    — イベント削除
  GET    /calendar/sync-mode      — 同期モード確認
  PATCH  /calendar/sync-mode      — 同期モード変更（admin のみ）

認証: 全エンドポイントで Bearer トークン必須（get_current_tenant）
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_tenant, get_current_user
from app.database import get_db
from app.models import User
from app.services import calendar_service as cal_svc

logger = logging.getLogger(__name__)

router = APIRouter()

_VALID_SYNC_MODES = ("bidirectional", "read_only", "write_only", "none")


def _require_admin(user: User) -> None:
    if getattr(user, "role", None) != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="この操作は管理者のみ実行できます",
        )


# ---------------------------------------------------------------------------
# Pydantic モデル
# ---------------------------------------------------------------------------


class CreateEventBody(BaseModel):
    title: str
    start_datetime: str
    end_datetime: str
    calendar_type: str = "shared"
    description: Optional[str] = None
    location: Optional[str] = None
    is_all_day: bool = False


class UpdateEventBody(BaseModel):
    title: Optional[str] = None
    start_datetime: Optional[str] = None
    end_datetime: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    is_all_day: Optional[bool] = None


class SyncModeBody(BaseModel):
    sync_mode: str


# ---------------------------------------------------------------------------
# イベント一覧
# ---------------------------------------------------------------------------


@router.get("/calendar/events", tags=["calendar"])
async def list_events(
    start: str = Query(..., description="ISO 8601 形式 例: 2025-05-01T00:00:00Z"),
    end: str = Query(..., description="ISO 8601 形式 例: 2025-05-31T23:59:59Z"),
    type: Optional[str] = Query(None, description="'shared' | 'personal' | None（両方）"),
    tenant_id: int = Depends(get_current_tenant),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """カレンダーイベントを期間・タイプで取得する。"""
    events = await cal_svc.list_events(
        db,
        tenant_id=tenant_id,
        start=start,
        end=end,
        calendar_type=type,
        user_id=user.id,
    )
    return {"events": events}


# ---------------------------------------------------------------------------
# イベント作成
# ---------------------------------------------------------------------------


@router.post("/calendar/events", status_code=status.HTTP_201_CREATED, tags=["calendar"])
async def create_event(
    body: CreateEventBody,
    tenant_id: int = Depends(get_current_tenant),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """アプリ内にイベントを作成し、Google Calendar に同期する。"""
    if body.calendar_type not in ("shared", "personal"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="calendar_type は 'shared' または 'personal' を指定してください",
        )
    try:
        result = await cal_svc.create_event(
            db,
            tenant_id=tenant_id,
            user_id=user.id,
            payload=body.model_dump(exclude_none=True),
        )
    except Exception as e:
        logger.error("イベント作成エラー: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="イベントの作成に失敗しました",
        )
    return result


# ---------------------------------------------------------------------------
# イベント更新
# ---------------------------------------------------------------------------


@router.patch("/calendar/events/{event_id}", tags=["calendar"])
async def update_event(
    event_id: int,
    body: UpdateEventBody,
    tenant_id: int = Depends(get_current_tenant),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """アプリ内のイベントを更新し、Google Calendar に同期する。"""
    payload = body.model_dump(exclude_none=True)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="更新フィールドが指定されていません",
        )

    # 権限確認: 自分のイベントか channels.manage 権限保持者のみ
    row = await db.execute(
        text("SELECT created_by_user_id, calendar_type FROM calendar_events WHERE id = :id"),
        {"id": event_id},
    )
    record = row.first()
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="イベントが見つかりません")

    created_by, calendar_type = record[0], record[1]
    if created_by != user.id and getattr(user, "role", None) != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="編集権限がありません")

    try:
        result = await cal_svc.update_event(
            db,
            tenant_id=tenant_id,
            event_id=event_id,
            user_id=user.id,
            payload=payload,
        )
    except Exception as e:
        logger.error("イベント更新エラー: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="イベントの更新に失敗しました",
        )
    return result


# ---------------------------------------------------------------------------
# イベント削除
# ---------------------------------------------------------------------------


@router.delete("/calendar/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["calendar"])
async def delete_event(
    event_id: int,
    tenant_id: int = Depends(get_current_tenant),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """アプリ内のイベントを削除し、Google Calendar からも削除する。"""
    row = await db.execute(
        text("SELECT created_by_user_id FROM calendar_events WHERE id = :id"),
        {"id": event_id},
    )
    record = row.first()
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="イベントが見つかりません")

    if record[0] != user.id and getattr(user, "role", None) != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="削除権限がありません")

    await cal_svc.delete_event(db, tenant_id=tenant_id, event_id=event_id)


# ---------------------------------------------------------------------------
# 同期モード確認 / 変更
# ---------------------------------------------------------------------------


@router.get("/calendar/sync-mode", tags=["calendar"])
async def get_sync_mode(
    tenant_id: int = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """現在の同期モードを返す。"""
    row = await db.execute(
        text(
            "SELECT sync_mode FROM tenant_google_calendar_config WHERE tenant_id = :tid"
        ),
        {"tid": tenant_id},
    )
    record = row.first()
    return {"sync_mode": record[0] if record else "none"}


@router.patch("/calendar/sync-mode", tags=["calendar"])
async def update_sync_mode(
    body: SyncModeBody,
    tenant_id: int = Depends(get_current_tenant),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """同期モードを変更する（admin のみ）。"""
    _require_admin(user)

    if body.sync_mode not in _VALID_SYNC_MODES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"sync_mode は {_VALID_SYNC_MODES} のいずれかを指定してください",
        )

    await db.execute(
        text(
            "UPDATE tenant_google_calendar_config"
            " SET sync_mode = :mode, updated_at = NOW()"
            " WHERE tenant_id = :tid"
        ),
        {"mode": body.sync_mode, "tid": tenant_id},
    )
    await db.commit()

    # Webhook の登録/解除を同期モードに合わせて調整
    from app.services import google_webhook as webhook_svc

    if body.sync_mode in ("bidirectional", "read_only"):
        await webhook_svc.register_webhook(db, tenant_id)
    else:
        await webhook_svc.stop_webhook(db, tenant_id)

    return {"sync_mode": body.sync_mode}
