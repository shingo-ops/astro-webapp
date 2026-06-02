"""Discord 顧客削除操作 API (ADR-091 KPI6).

担当者が Sales Anchor アプリから顧客を Discord チャンネル・サーバーから削除するエンドポイント。

API:
  POST /api/v1/discord/remove-from-channel/{lead_id} — チケットチャンネルから顧客を削除
  POST /api/v1/discord/kick/{lead_id}                — サーバーから Kick（再参加可）
  POST /api/v1/discord/ban/{lead_id}                 — サーバーから BAN（再参加不可）

権限: leads.delete
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


def _get_bot_token(tenant_id: int) -> str | None:
    token = os.environ.get(f"DISCORD_BOT_TOKEN_{tenant_id}")
    if token:
        return token
    cfg = next((c for c in load_tenant_bot_configs() if c.tenant_id == tenant_id), None)
    return cfg.bot_token if cfg else None


async def _get_lead_discord_info(
    db: AsyncSession, tenant_id: int, lead_id: int
) -> tuple[str, str]:
    """リードの (discord_user_id, discord_guild_channel_id) を返す。未設定なら 422。"""
    leads_t = tenant_table_ref(db, tenant_id, "leads")
    result = await db.execute(
        text(f"SELECT discord_user_id, discord_guild_channel_id FROM {leads_t} WHERE id = :id"),
        {"id": lead_id},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="リードが見つかりません")
    discord_user_id = row["discord_user_id"]
    if not discord_user_id:
        raise HTTPException(status_code=409, detail="このリードには Discord ユーザーID が設定されていません。")
    return str(discord_user_id), str(row["discord_guild_channel_id"] or "")


async def _get_guild_id(db: AsyncSession, tenant_id: int) -> str:
    result = await db.execute(
        text("SELECT guild_id FROM public.tenant_discord_config WHERE tenant_id = :tid"),
        {"tid": tenant_id},
    )
    row = result.first()
    if not row or not row[0]:
        raise HTTPException(status_code=422, detail="Discord Guild ID が設定されていません。")
    return str(row[0])


class RemoveResponse(BaseModel):
    lead_id: int
    action: str  # "remove_from_channel" | "kick" | "ban"


@router.post(
    "/discord/remove-from-channel/{lead_id}",
    response_model=RemoveResponse,
    dependencies=[Depends(require_permission("leads.delete"))],
)
async def remove_from_channel(
    lead_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
) -> RemoveResponse:
    """チケットチャンネルから顧客の閲覧権限を削除する。

    チャンネルのユーザー固有 permission overwrite を削除し、
    @everyone のデフォルト（非表示）に戻す。
    leads.discord_guild_channel_id を NULL にクリアする。
    """
    discord_user_id, channel_id = await _get_lead_discord_info(db, tenant_id, lead_id)
    if not channel_id:
        raise HTTPException(status_code=409, detail="チケットチャンネルが設定されていません。")

    bot_token = _get_bot_token(tenant_id)
    if not bot_token:
        raise HTTPException(status_code=503, detail="Bot トークンが設定されていません。")

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.delete(
            f"https://discord.com/api/v10/channels/{channel_id}/permissions/{discord_user_id}",
            headers={"Authorization": f"Bot {bot_token}"},
        )

    if resp.status_code not in (204,):
        logger.error(
            "[discord_remove] remove-from-channel failed tenant=%d lead=%d ch=%s user=%s status=%d",
            tenant_id, lead_id, channel_id, discord_user_id, resp.status_code,
        )
        raise HTTPException(
            status_code=502,
            detail=f"Discord API エラー ({resp.status_code}): チャンネルIDとBot権限を確認してください。",
        )

    # leads.discord_guild_channel_id をクリア
    leads_t = tenant_table_ref(db, tenant_id, "leads")
    await db.execute(
        text(f"UPDATE {leads_t} SET discord_guild_channel_id = NULL WHERE id = :id"),
        {"id": lead_id},
    )
    await record_audit_log(
        db=db, tenant_id=tenant_id, user_id=current_user.id,
        action="delete", table_name="discord_channel_member",
        record_id=lead_id,
        new_data={"lead_id": lead_id, "channel_id": channel_id, "discord_user_id": discord_user_id},
    )
    await db.commit()
    await reset_tenant_context(db, tenant_id)

    logger.info(
        "[discord_remove] removed from channel tenant=%d lead=%d ch=%s user=%s by user=%d",
        tenant_id, lead_id, channel_id, discord_user_id, current_user.id,
    )
    return RemoveResponse(lead_id=lead_id, action="remove_from_channel")


@router.post(
    "/discord/kick/{lead_id}",
    response_model=RemoveResponse,
    dependencies=[Depends(require_permission("leads.delete"))],
)
async def kick_member(
    lead_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
) -> RemoveResponse:
    """顧客を Discord サーバーから Kick する（再参加可能）。"""
    discord_user_id, _ = await _get_lead_discord_info(db, tenant_id, lead_id)
    guild_id = await _get_guild_id(db, tenant_id)
    bot_token = _get_bot_token(tenant_id)
    if not bot_token:
        raise HTTPException(status_code=503, detail="Bot トークンが設定されていません。")

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.delete(
            f"https://discord.com/api/v10/guilds/{guild_id}/members/{discord_user_id}",
            headers={"Authorization": f"Bot {bot_token}"},
        )

    if resp.status_code not in (204,):
        logger.error(
            "[discord_remove] kick failed tenant=%d lead=%d guild=%s user=%s status=%d",
            tenant_id, lead_id, guild_id, discord_user_id, resp.status_code,
        )
        raise HTTPException(
            status_code=502,
            detail=f"Discord API エラー ({resp.status_code}): Guild IDとBot権限を確認してください。",
        )

    await record_audit_log(
        db=db, tenant_id=tenant_id, user_id=current_user.id,
        action="delete", table_name="discord_guild_member",
        record_id=lead_id,
        new_data={"lead_id": lead_id, "guild_id": guild_id, "discord_user_id": discord_user_id, "action": "kick"},
    )
    await db.commit()
    await reset_tenant_context(db, tenant_id)

    logger.info(
        "[discord_remove] kicked tenant=%d lead=%d guild=%s user=%s by user=%d",
        tenant_id, lead_id, guild_id, discord_user_id, current_user.id,
    )
    return RemoveResponse(lead_id=lead_id, action="kick")


@router.post(
    "/discord/ban/{lead_id}",
    response_model=RemoveResponse,
    dependencies=[Depends(require_permission("leads.delete"))],
)
async def ban_member(
    lead_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
) -> RemoveResponse:
    """顧客を Discord サーバーから BAN する（再参加不可）。"""
    discord_user_id, _ = await _get_lead_discord_info(db, tenant_id, lead_id)
    guild_id = await _get_guild_id(db, tenant_id)
    bot_token = _get_bot_token(tenant_id)
    if not bot_token:
        raise HTTPException(status_code=503, detail="Bot トークンが設定されていません。")

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.put(
            f"https://discord.com/api/v10/guilds/{guild_id}/bans/{discord_user_id}",
            headers={"Authorization": f"Bot {bot_token}", "Content-Type": "application/json"},
            json={},
        )

    if resp.status_code not in (200, 204):
        logger.error(
            "[discord_remove] ban failed tenant=%d lead=%d guild=%s user=%s status=%d",
            tenant_id, lead_id, guild_id, discord_user_id, resp.status_code,
        )
        raise HTTPException(
            status_code=502,
            detail=f"Discord API エラー ({resp.status_code}): Guild IDとBot権限を確認してください。",
        )

    await record_audit_log(
        db=db, tenant_id=tenant_id, user_id=current_user.id,
        action="delete", table_name="discord_guild_member",
        record_id=lead_id,
        new_data={"lead_id": lead_id, "guild_id": guild_id, "discord_user_id": discord_user_id, "action": "ban"},
    )
    await db.commit()
    await reset_tenant_context(db, tenant_id)

    logger.info(
        "[discord_remove] banned tenant=%d lead=%d guild=%s user=%s by user=%d",
        tenant_id, lead_id, guild_id, discord_user_id, current_user.id,
    )
    return RemoveResponse(lead_id=lead_id, action="ban")
