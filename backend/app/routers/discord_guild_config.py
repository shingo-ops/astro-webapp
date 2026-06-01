"""Discord Guild 設定 API (Sprint D2 / F5 subset).

テナント admin が Discord サーバー (Guild) の設定を管理するエンドポイント。
ロールマッピングは固定 (Small→Member, Large→Partner) なので設定不要。

API:
  GET  /api/v1/admin/discord-config   — 現在の設定取得
  PUT  /api/v1/admin/discord-config   — guild_id 設定 / 更新

権限:
  GET: tenant.profile.view
  PUT: tenant.profile.edit
"""
from __future__ import annotations

import logging
import re

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_tenant, get_current_user, require_permission, reset_tenant_context
from app.database import get_db
from app.models import User
from app.services.audit import record_audit_log

logger = logging.getLogger(__name__)
router = APIRouter()

_GUILD_ID_RE = re.compile(r"^\d{17,20}$")


class DiscordConfigResponse(BaseModel):
    guild_id: str | None = None
    role_member: str = "Member"
    role_partner: str = "Partner"


class DiscordConfigUpdate(BaseModel):
    guild_id: str = Field(..., min_length=17, max_length=20)

    @field_validator("guild_id")
    @classmethod
    def validate_guild_id(cls, v: str) -> str:
        if not _GUILD_ID_RE.match(v):
            raise ValueError("Guild ID は17〜20桁の数字で入力してください")
        return v


@router.get(
    "/admin/discord-config",
    response_model=DiscordConfigResponse,
    dependencies=[Depends(require_permission("tenant.profile.view"))],
)
async def get_discord_config(
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
) -> DiscordConfigResponse:
    """Discord Guild 設定を取得する。未設定の場合は guild_id=None を返す。"""
    result = await db.execute(
        text(
            "SELECT guild_id FROM public.tenant_discord_config WHERE tenant_id = :tid"
        ),
        {"tid": tenant_id},
    )
    row = result.first()
    return DiscordConfigResponse(guild_id=str(row[0]) if row else None)


@router.put(
    "/admin/discord-config",
    response_model=DiscordConfigResponse,
    dependencies=[Depends(require_permission("tenant.profile.edit"))],
)
async def update_discord_config(
    data: DiscordConfigUpdate,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
) -> DiscordConfigResponse:
    """Discord Guild ID を設定 / 更新する (upsert)。"""
    await db.execute(
        text("""
            INSERT INTO public.tenant_discord_config (tenant_id, guild_id)
            VALUES (:tid, :guild_id)
            ON CONFLICT (tenant_id)
            DO UPDATE SET guild_id = EXCLUDED.guild_id, updated_at = NOW()
        """),
        {"tid": tenant_id, "guild_id": data.guild_id},
    )
    await record_audit_log(
        db=db,
        tenant_id=tenant_id,
        user_id=current_user.id,
        action="update",
        table_name="tenant_discord_config",
        record_id=tenant_id,
        new_data={"guild_id": data.guild_id},
    )
    await db.commit()
    await reset_tenant_context(db, tenant_id)  # ADR-072: commit 後の search_path 復元

    logger.info(
        "[discord_config] updated tenant=%d guild_id=%s by user=%d",
        tenant_id, data.guild_id, current_user.id,
    )
    return DiscordConfigResponse(guild_id=data.guild_id)
