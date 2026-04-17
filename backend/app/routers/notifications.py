from __future__ import annotations

"""
Discord通知管理API + 通知送信サービス。

Webhook URL設定 + イベント発火時にDiscordに自動送信。

変更履歴:
  2026-04-17: 初版作成（Phase 4）
"""

import json
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, get_current_tenant, require_permission
from app.database import get_db
from app.models import User
from app.services.audit import record_audit_log

logger = logging.getLogger(__name__)
router = APIRouter()


class ChannelCreate(BaseModel):
    channel_name: str = Field(min_length=1, max_length=100)
    webhook_url: str = Field(min_length=1, max_length=500)
    event_types: list[str] = Field(default_factory=lambda: ["customer_created", "deal_won", "invoice_issued"])


class ChannelUpdate(BaseModel):
    channel_name: str | None = Field(default=None, max_length=100)
    webhook_url: str | None = Field(default=None, max_length=500)
    event_types: list[str] | None = None
    is_active: bool | None = None


class ChannelResponse(BaseModel):
    id: int
    channel_name: str
    webhook_url: str
    event_types: str
    is_active: bool
    created_at: str
    model_config = {"from_attributes": True}


_COLS = "id, channel_name, webhook_url, event_types, is_active, created_at, updated_at"
_UPDATABLE = {"channel_name", "webhook_url", "event_types", "is_active"}


@router.get("/notification-channels", response_model=list[ChannelResponse],
            dependencies=[Depends(require_permission("notifications.view"))])
async def list_channels(db: AsyncSession = Depends(get_db),
                        tenant_id: int = Depends(get_current_tenant),
                        current_user: User = Depends(get_current_user)):
    result = await db.execute(text(f"SELECT {_COLS} FROM notification_channels ORDER BY channel_name"))
    return [ChannelResponse(**row) for row in result.mappings().all()]


@router.post("/notification-channels", response_model=ChannelResponse, status_code=201,
             dependencies=[Depends(require_permission("notifications.manage"))])
async def create_channel(data: ChannelCreate, db: AsyncSession = Depends(get_db),
                         tenant_id: int = Depends(get_current_tenant),
                         current_user: User = Depends(get_current_user)):
    result = await db.execute(
        text(f"""
            INSERT INTO notification_channels (tenant_id, channel_name, webhook_url, event_types)
            VALUES (:tid, :name, :url, :events)
            RETURNING {_COLS}
        """),
        {"tid": tenant_id, "name": data.channel_name, "url": data.webhook_url,
         "events": json.dumps(data.event_types)},
    )
    row = result.mappings().first()
    await record_audit_log(db=db, tenant_id=tenant_id, user_id=current_user.id,
                           action="create", table_name="notification_channels", record_id=row["id"],
                           new_data={"channel_name": data.channel_name})
    await db.commit()
    return ChannelResponse(**dict(row))


@router.delete("/notification-channels/{channel_id}", status_code=204,
               dependencies=[Depends(require_permission("notifications.manage"))])
async def delete_channel(channel_id: int, db: AsyncSession = Depends(get_db),
                         tenant_id: int = Depends(get_current_tenant),
                         current_user: User = Depends(get_current_user)):
    r = await db.execute(text("DELETE FROM notification_channels WHERE id = :id RETURNING id"), {"id": channel_id})
    if not r.first():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="チャンネルが見つかりません")
    await record_audit_log(db=db, tenant_id=tenant_id, user_id=current_user.id,
                           action="delete", table_name="notification_channels", record_id=channel_id)
    await db.commit()


async def send_discord_notification(db: AsyncSession, tenant_id: int, event_type: str, title: str, message: str) -> None:
    """Discord Webhookに通知を送信する（バックグラウンド実行用）"""
    try:
        result = await db.execute(
            text("SELECT id, webhook_url FROM notification_channels WHERE is_active = TRUE AND event_types LIKE :pattern"),
            {"pattern": f"%{event_type}%"},
        )
        channels = result.mappings().all()
        async with httpx.AsyncClient(timeout=10.0) as client:
            for ch in channels:
                try:
                    payload = {"embeds": [{"title": title, "description": message, "color": 3447003}]}
                    resp = await client.post(ch["webhook_url"], json=payload)
                    status_val = "sent" if resp.status_code < 300 else "failed"
                    await db.execute(
                        text("""
                            INSERT INTO notification_logs (tenant_id, channel_id, event_type, title, message, status, sent_at)
                            VALUES (:tid, :cid, :etype, :title, :msg, :status, NOW())
                        """),
                        {"tid": tenant_id, "cid": ch["id"], "etype": event_type,
                         "title": title, "msg": message, "status": status_val},
                    )
                except Exception as e:
                    logger.warning("Discord送信失敗 channel=%d: %s", ch["id"], e)
        await db.commit()
    except Exception as e:
        logger.warning("Discord通知処理失敗: %s", e)
