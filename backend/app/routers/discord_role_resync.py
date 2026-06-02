"""Discord ロール手動再同期 API (ADR-091 KPI7).

estimated_scale に基づく Discord ロール同期を手動でトリガーするエンドポイント。
通常は estimated_scale 更新時に自動実行されるが、
discord_role_sync_status = 'failed' の場合などに手動でリトライできる。

API:
  POST /api/v1/discord/sync-role/{lead_id} — ロール同期を手動実行

権限: leads.edit
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import (
    get_current_tenant,
    require_permission,
    tenant_table_ref,
)
from app.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter()


class RoleSyncResponse(BaseModel):
    lead_id: int
    discord_user_id: str
    estimated_scale: str
    triggered: bool


@router.post(
    "/discord/sync-role/{lead_id}",
    response_model=RoleSyncResponse,
    dependencies=[Depends(require_permission("leads.edit"))],
)
async def resync_discord_role(
    lead_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
) -> RoleSyncResponse:
    """estimated_scale に基づく Discord ロール同期を手動トリガーする。

    discord_user_id または estimated_scale が未設定の場合は 409。
    ロール同期は非同期タスクとして実行（API はすぐに返す）。
    """
    leads_t = tenant_table_ref(db, tenant_id, "leads")
    result = await db.execute(
        text(f"SELECT discord_user_id, estimated_scale FROM {leads_t} WHERE id = :id"),
        {"id": lead_id},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="リードが見つかりません")

    discord_user_id = row["discord_user_id"]
    estimated_scale = row["estimated_scale"]

    if not discord_user_id:
        raise HTTPException(status_code=409, detail="discord_user_id が設定されていません。")
    if not estimated_scale:
        raise HTTPException(status_code=409, detail="estimated_scale が設定されていません。")

    from app.services.discord_role_sync import sync_lead_discord_role
    asyncio.create_task(
        sync_lead_discord_role(
            tenant_id=tenant_id,
            lead_id=lead_id,
            discord_user_id=str(discord_user_id),
            new_scale=str(estimated_scale),
        )
    )

    logger.info(
        "[discord_role_resync] triggered tenant=%d lead=%d user=%s scale=%s",
        tenant_id, lead_id, discord_user_id, estimated_scale,
    )
    return RoleSyncResponse(
        lead_id=lead_id,
        discord_user_id=str(discord_user_id),
        estimated_scale=str(estimated_scale),
        triggered=True,
    )
