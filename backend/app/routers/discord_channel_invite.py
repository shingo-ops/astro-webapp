"""Discord チャンネル招待メッセージ送信 API (ADR-091 KPI5).

担当者が Sales Anchor アプリから顧客の Discord チケットチャンネルへ
規模別専用チャンネルへの案内メッセージを送信するエンドポイント。

顧客の estimated_scale (Small/Large) に対応する専用チャンネルへの
Discord チャンネルメンション付きメッセージをチケットチャンネルに投稿する。

API:
  POST /api/v1/discord/channel-invite/{lead_id} — 招待メッセージ送信

権限: leads.edit
"""
from __future__ import annotations

import logging
import os

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import (
    get_current_tenant,
    get_current_user,
    require_permission,
    reset_tenant_context,
    tenant_table_ref,
)
from app.database import get_db
from app.discord_gateway.config import load_tenant_bot_configs
from app.models import User
from app.services.audit import record_audit_log

logger = logging.getLogger(__name__)
router = APIRouter()

# estimated_scale → メッセージ文言のマッピング
_SCALE_LABEL: dict[str, str] = {
    "Small": "小口",
    "Medium": "一般",
    "Large": "大口",
}


def _get_bot_token(tenant_id: int) -> str | None:
    token = os.environ.get(f"DISCORD_BOT_TOKEN_{tenant_id}")
    if token:
        return token
    cfg = next((c for c in load_tenant_bot_configs() if c.tenant_id == tenant_id), None)
    return cfg.bot_token if cfg else None


class ChannelInviteResponse(BaseModel):
    lead_id: int
    target_channel_id: str
    ticket_channel_id: str
    message_id: str


@router.post(
    "/discord/channel-invite/{lead_id}",
    response_model=ChannelInviteResponse,
    dependencies=[Depends(require_permission("leads.edit"))],
)
async def send_channel_invite(
    lead_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
) -> ChannelInviteResponse:
    """顧客の規模別専用チャンネルへの案内メッセージをチケットチャンネルに送信する。

    前提条件:
    - leads.discord_guild_channel_id (チケットチャンネル) が設定済み
    - tenant_discord_ticket_config.small_channel_id または large_channel_id が設定済み
    - estimated_scale が Small または Large
    """
    leads_t = tenant_table_ref(db, tenant_id, "leads")

    # リード情報取得
    lead_result = await db.execute(
        text(
            f"SELECT estimated_scale, discord_guild_channel_id "
            f"FROM {leads_t} WHERE id = :id"
        ),
        {"id": lead_id},
    )
    lead_row = lead_result.mappings().first()
    if not lead_row:
        raise HTTPException(status_code=404, detail="リードが見つかりません")

    ticket_channel_id = lead_row["discord_guild_channel_id"]
    if not ticket_channel_id:
        raise HTTPException(
            status_code=409,
            detail="チケットチャンネルが未作成です。先にチケットチャンネルを作成してください。",
        )

    estimated_scale = lead_row["estimated_scale"]

    # 規模別チャンネル設定取得
    config_result = await db.execute(
        text(
            "SELECT small_channel_id, large_channel_id "
            "FROM public.tenant_discord_ticket_config WHERE tenant_id = :tid"
        ),
        {"tid": tenant_id},
    )
    config_row = config_result.mappings().first()
    if not config_row:
        raise HTTPException(status_code=422, detail="Discord チケット設定が未設定です。")

    # 規模に対応するチャンネルID を選択
    if estimated_scale == "Small":
        target_channel_id = config_row["small_channel_id"]
    elif estimated_scale == "Large":
        target_channel_id = config_row["large_channel_id"]
    else:
        raise HTTPException(
            status_code=422,
            detail=f"estimated_scale '{estimated_scale}' に対応する専用チャンネルがありません（Small/Large のみ対応）。",
        )

    if not target_channel_id:
        scale_label = _SCALE_LABEL.get(estimated_scale, estimated_scale)
        raise HTTPException(
            status_code=422,
            detail=f"{scale_label}向けチャンネルIDが設定されていません。Discord 設定ページで設定してください。",
        )

    # Bot トークン取得
    bot_token = _get_bot_token(tenant_id)
    if not bot_token:
        raise HTTPException(
            status_code=503,
            detail="Bot トークンが設定されていません。",
        )

    # チケットチャンネルへ案内メッセージを送信
    scale_label = _SCALE_LABEL.get(estimated_scale, estimated_scale)
    message_content = (
        f"【お知らせ】{scale_label}のお客様向けの専用チャンネルをご案内します。\n"
        f"以下のチャンネルで最新情報・お得な情報をご確認ください👇\n"
        f"<#{target_channel_id}>"
    )

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"https://discord.com/api/v10/channels/{ticket_channel_id}/messages",
            headers={
                "Authorization": f"Bot {bot_token}",
                "Content-Type": "application/json",
            },
            json={"content": message_content},
        )

    if resp.status_code not in (200, 201):
        logger.error(
            "[discord_channel_invite] failed tenant=%d lead=%d ch=%s status=%d body=%s",
            tenant_id, lead_id, ticket_channel_id, resp.status_code, resp.text[:200],
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
        table_name="discord_channel_invite",
        record_id=lead_id,
        new_data={
            "lead_id": lead_id,
            "ticket_channel_id": ticket_channel_id,
            "target_channel_id": target_channel_id,
            "scale": estimated_scale,
            "message_id": message_id,
        },
    )
    await db.commit()
    await reset_tenant_context(db, tenant_id)

    logger.info(
        "[discord_channel_invite] sent tenant=%d lead=%d ticket_ch=%s target_ch=%s by user=%d",
        tenant_id, lead_id, ticket_channel_id, target_channel_id, current_user.id,
    )
    return ChannelInviteResponse(
        lead_id=lead_id,
        target_channel_id=str(target_channel_id),
        ticket_channel_id=str(ticket_channel_id),
        message_id=message_id,
    )
