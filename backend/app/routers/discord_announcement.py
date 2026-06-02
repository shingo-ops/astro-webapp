"""Discord アナウンス投稿 API (ADR-091 KPI4).

テナント admin が Discord チャンネルへアナウンスを投稿するエンドポイント。
SalesAnchor から直接投稿することで Discord を開かずにアプリ内で完結させる（KGI）。

API:
  POST /api/v1/discord/announce — 指定チャンネルへメッセージ投稿

権限: tenant.profile.edit
"""
from __future__ import annotations

import logging
import os

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_tenant, get_current_user, require_permission
from app.database import get_db, reset_tenant_context
from app.discord_gateway.config import load_tenant_bot_configs
from app.models import User
from app.services.audit import record_audit_log

logger = logging.getLogger(__name__)
router = APIRouter()

_MESSAGE_MAX = 2000  # Discord のメッセージ文字数上限


class AnnounceRequest(BaseModel):
    channel_id: str = Field(..., min_length=17, max_length=20, pattern=r"^\d{17,20}$")
    message: str = Field(..., min_length=1, max_length=_MESSAGE_MAX)


class AnnounceResponse(BaseModel):
    message_id: str
    channel_id: str


def _get_bot_token(tenant_id: int) -> str | None:
    token = os.environ.get(f"DISCORD_BOT_TOKEN_{tenant_id}")
    if token:
        return token
    cfg = next((c for c in load_tenant_bot_configs() if c.tenant_id == tenant_id), None)
    return cfg.bot_token if cfg else None


@router.post(
    "/discord/announce",
    response_model=AnnounceResponse,
    dependencies=[Depends(require_permission("tenant.profile.edit"))],
)
async def post_announcement(
    data: AnnounceRequest,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
) -> AnnounceResponse:
    """Discord チャンネルにアナウンスを投稿する。"""
    bot_token = _get_bot_token(tenant_id)
    if not bot_token:
        raise HTTPException(
            status_code=503,
            detail="Bot トークンが設定されていません。環境変数 DISCORD_BOT_TOKEN_{tenant_id} を確認してください。",
        )

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"https://discord.com/api/v10/channels/{data.channel_id}/messages",
            headers={
                "Authorization": f"Bot {bot_token}",
                "Content-Type": "application/json",
            },
            json={"content": data.message},
        )

    if resp.status_code not in (200, 201):
        logger.error(
            "[discord_announce] failed tenant=%d ch=%s status=%d body=%s",
            tenant_id, data.channel_id, resp.status_code, resp.text[:200],
        )
        raise HTTPException(
            status_code=502,
            detail=f"Discord API エラー ({resp.status_code}): チャンネルIDとBot権限を確認してください。",
        )

    message_id = resp.json().get("id", "")
    await record_audit_log(
        db=db,
        tenant_id=tenant_id,
        user_id=current_user.id,
        action="create",
        table_name="discord_announcement",
        record_id=tenant_id,
        new_data={"channel_id": data.channel_id, "message_id": message_id},
    )
    await db.commit()
    await reset_tenant_context(db, tenant_id)

    logger.info(
        "[discord_announce] posted tenant=%d ch=%s msg=%s by user=%d",
        tenant_id, data.channel_id, message_id, current_user.id,
    )
    return AnnounceResponse(message_id=message_id, channel_id=data.channel_id)
