"""Discord チケット機能設定 API (ADR-091 KPI3 Phase 1).

テナント admin がチケット機能の設定を管理するエンドポイント。
- カテゴリID（プライベートDM専用カテゴリ）
- ボタン設置チャンネルID
- 担当者ロールID（任意）
- ウェルカムメッセージテンプレート

API:
  GET  /api/v1/admin/discord-ticket-config   — 現在の設定取得
  PUT  /api/v1/admin/discord-ticket-config   — 設定保存 (upsert)

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

from app.auth.dependencies import (
    get_current_tenant,
    get_current_user,
    require_permission,
    reset_tenant_context,
)
from app.database import get_db
from app.models import User
from app.services.audit import record_audit_log

logger = logging.getLogger(__name__)
router = APIRouter()

_SNOWFLAKE_RE = re.compile(r"^\d{17,20}$")
_WELCOME_TEMPLATE_MAX = 500


def _is_valid_snowflake(value: str) -> bool:
    return bool(_SNOWFLAKE_RE.match(value))


class DiscordTicketConfigResponse(BaseModel):
    ticket_category_id: str | None = None
    ticket_button_channel_id: str | None = None
    staff_role_id: str | None = None
    welcome_template: str = "ご連絡ありがとうございます。こちらのチャンネルでサポートいたします。"


class DiscordTicketConfigUpdate(BaseModel):
    ticket_category_id: str = Field(..., min_length=17, max_length=20)
    ticket_button_channel_id: str = Field(..., min_length=17, max_length=20)
    staff_role_id: str | None = Field(default=None, min_length=17, max_length=20)
    welcome_template: str = Field(
        default="ご連絡ありがとうございます。こちらのチャンネルでサポートいたします。",
        max_length=_WELCOME_TEMPLATE_MAX,
    )

    @field_validator("ticket_category_id", "ticket_button_channel_id")
    @classmethod
    def validate_snowflake(cls, v: str) -> str:
        if not _is_valid_snowflake(v):
            raise ValueError("ID は17〜20桁の数字で入力してください")
        return v

    @field_validator("staff_role_id")
    @classmethod
    def validate_staff_role_id(cls, v: str | None) -> str | None:
        if v is not None and not _is_valid_snowflake(v):
            raise ValueError("ロールID は17〜20桁の数字で入力してください")
        return v


@router.get(
    "/admin/discord-ticket-config",
    response_model=DiscordTicketConfigResponse,
    dependencies=[Depends(require_permission("tenant.profile.view"))],
)
async def get_discord_ticket_config(
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
) -> DiscordTicketConfigResponse:
    """チケット機能設定を取得する。未設定の場合はデフォルト値を返す。"""
    result = await db.execute(
        text("""
            SELECT ticket_category_id, ticket_button_channel_id,
                   staff_role_id, welcome_template
            FROM public.tenant_discord_ticket_config
            WHERE tenant_id = :tid
        """),
        {"tid": tenant_id},
    )
    row = result.mappings().first()
    if not row:
        return DiscordTicketConfigResponse()
    return DiscordTicketConfigResponse(
        ticket_category_id=str(row["ticket_category_id"]),
        ticket_button_channel_id=str(row["ticket_button_channel_id"]),
        staff_role_id=str(row["staff_role_id"]) if row["staff_role_id"] else None,
        welcome_template=row["welcome_template"],
    )


@router.put(
    "/admin/discord-ticket-config",
    response_model=DiscordTicketConfigResponse,
    dependencies=[Depends(require_permission("tenant.profile.edit"))],
)
async def update_discord_ticket_config(
    data: DiscordTicketConfigUpdate,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
) -> DiscordTicketConfigResponse:
    """チケット機能設定を保存する (upsert)。"""
    await db.execute(
        text("""
            INSERT INTO public.tenant_discord_ticket_config
                (tenant_id, ticket_category_id, ticket_button_channel_id,
                 staff_role_id, welcome_template, updated_at)
            VALUES
                (:tid, :category_id, :button_channel_id,
                 :staff_role_id, :welcome_template, NOW())
            ON CONFLICT (tenant_id) DO UPDATE SET
                ticket_category_id      = EXCLUDED.ticket_category_id,
                ticket_button_channel_id = EXCLUDED.ticket_button_channel_id,
                staff_role_id           = EXCLUDED.staff_role_id,
                welcome_template        = EXCLUDED.welcome_template,
                updated_at              = NOW()
        """),
        {
            "tid": tenant_id,
            "category_id": data.ticket_category_id,
            "button_channel_id": data.ticket_button_channel_id,
            "staff_role_id": data.staff_role_id,
            "welcome_template": data.welcome_template,
        },
    )
    await record_audit_log(
        db=db,
        tenant_id=tenant_id,
        user_id=current_user.id,
        action="update",
        table_name="tenant_discord_ticket_config",
        record_id=tenant_id,
        new_data={
            "ticket_category_id": data.ticket_category_id,
            "ticket_button_channel_id": data.ticket_button_channel_id,
            "staff_role_id": data.staff_role_id,
        },
    )
    await db.commit()
    await reset_tenant_context(db, tenant_id)

    logger.info(
        "[discord_ticket_config] updated tenant=%d category=%s button_channel=%s by user=%d",
        tenant_id, data.ticket_category_id, data.ticket_button_channel_id, current_user.id,
    )
    return DiscordTicketConfigResponse(
        ticket_category_id=data.ticket_category_id,
        ticket_button_channel_id=data.ticket_button_channel_id,
        staff_role_id=data.staff_role_id,
        welcome_template=data.welcome_template,
    )
