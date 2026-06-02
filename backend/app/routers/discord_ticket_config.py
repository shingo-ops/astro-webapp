"""Discord チケット機能設定 API (ADR-091 KPI3/KPI5).

テナント admin がチケット機能の設定を管理するエンドポイント。
- カテゴリID（プライベートDM専用カテゴリ）
- ボタン設置チャンネルID
- 担当者ロールID（任意）
- ウェルカムメッセージテンプレート
- 小口/大口顧客向け専用チャンネルID（KPI5）

API:
  GET  /api/v1/admin/discord-ticket-config              — 現在の設定取得
  PUT  /api/v1/admin/discord-ticket-config              — 設定保存 (upsert)
  POST /api/v1/admin/discord-ticket-config/deploy-button — ボタンメッセージを Discord に投稿

権限:
  GET:    tenant.profile.view
  PUT:    tenant.profile.edit
  deploy: tenant.profile.edit
"""
from __future__ import annotations

import logging
import os
import re

import httpx
from fastapi import APIRouter, Depends, HTTPException
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
from app.discord_gateway.config import load_tenant_bot_configs
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
    small_channel_id: str | None = None
    large_channel_id: str | None = None


class DiscordTicketConfigUpdate(BaseModel):
    ticket_category_id: str = Field(..., min_length=17, max_length=20)
    ticket_button_channel_id: str = Field(..., min_length=17, max_length=20)
    staff_role_id: str | None = Field(default=None, min_length=17, max_length=20)
    welcome_template: str = Field(
        default="ご連絡ありがとうございます。こちらのチャンネルでサポートいたします。",
        max_length=_WELCOME_TEMPLATE_MAX,
    )
    small_channel_id: str | None = Field(default=None, min_length=17, max_length=20)
    large_channel_id: str | None = Field(default=None, min_length=17, max_length=20)

    @field_validator("ticket_category_id", "ticket_button_channel_id")
    @classmethod
    def validate_snowflake(cls, v: str) -> str:
        if not _is_valid_snowflake(v):
            raise ValueError("ID は17〜20桁の数字で入力してください")
        return v

    @field_validator("staff_role_id", "small_channel_id", "large_channel_id")
    @classmethod
    def validate_optional_snowflake(cls, v: str | None) -> str | None:
        if v is not None and not _is_valid_snowflake(v):
            raise ValueError("ID は17〜20桁の数字で入力してください")
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
                   staff_role_id, welcome_template,
                   small_channel_id, large_channel_id
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
        small_channel_id=str(row["small_channel_id"]) if row["small_channel_id"] else None,
        large_channel_id=str(row["large_channel_id"]) if row["large_channel_id"] else None,
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
                 staff_role_id, welcome_template,
                 small_channel_id, large_channel_id, updated_at)
            VALUES
                (:tid, :category_id, :button_channel_id,
                 :staff_role_id, :welcome_template,
                 :small_channel_id, :large_channel_id, NOW())
            ON CONFLICT (tenant_id) DO UPDATE SET
                ticket_category_id       = EXCLUDED.ticket_category_id,
                ticket_button_channel_id = EXCLUDED.ticket_button_channel_id,
                staff_role_id            = EXCLUDED.staff_role_id,
                welcome_template         = EXCLUDED.welcome_template,
                small_channel_id         = EXCLUDED.small_channel_id,
                large_channel_id         = EXCLUDED.large_channel_id,
                updated_at               = NOW()
        """),
        {
            "tid": tenant_id,
            "category_id": data.ticket_category_id,
            "button_channel_id": data.ticket_button_channel_id,
            "staff_role_id": data.staff_role_id,
            "welcome_template": data.welcome_template,
            "small_channel_id": data.small_channel_id,
            "large_channel_id": data.large_channel_id,
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
            "small_channel_id": data.small_channel_id,
            "large_channel_id": data.large_channel_id,
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
        small_channel_id=data.small_channel_id,
        large_channel_id=data.large_channel_id,
    )


class DeployButtonResponse(BaseModel):
    message_id: str
    channel_id: str


@router.post(
    "/admin/discord-ticket-config/deploy-button",
    response_model=DeployButtonResponse,
    dependencies=[Depends(require_permission("tenant.profile.edit"))],
)
async def deploy_ticket_button(
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
) -> DeployButtonResponse:
    """チケット開始ボタンを Discord チャンネルに投稿する (Phase 3).

    ticket_button_channel_id に「チケットを開く」ボタン付きメッセージを POST する。
    Bot トークンは環境変数 DISCORD_BOT_TOKEN_{tenant_id} から取得する。
    """
    # 設定取得
    result = await db.execute(
        text("""
            SELECT ticket_button_channel_id
            FROM public.tenant_discord_ticket_config
            WHERE tenant_id = :tid
        """),
        {"tid": tenant_id},
    )
    row = result.first()
    if not row or not row[0]:
        raise HTTPException(status_code=422, detail="チケット設定が未完了です。先にボタンチャンネルIDを設定してください。")

    channel_id = str(row[0])

    # Bot トークン取得
    bot_token: str | None = os.environ.get(f"DISCORD_BOT_TOKEN_{tenant_id}")
    if not bot_token:
        # load_tenant_bot_configs() でフォールバック検索
        configs = load_tenant_bot_configs()
        cfg = next((c for c in configs if c.tenant_id == tenant_id), None)
        bot_token = cfg.bot_token if cfg else None

    if not bot_token:
        raise HTTPException(status_code=503, detail="Bot トークンが設定されていません。環境変数 DISCORD_BOT_TOKEN_{tenant_id} を確認してください。")

    # Discord REST API でボタンメッセージを投稿
    payload = {
        "content": "サポートが必要な場合は下のボタンを押してください。",
        "components": [
            {
                "type": 1,  # ActionRow
                "components": [
                    {
                        "type": 2,  # Button
                        "style": 1,  # Primary (青)
                        "label": "チケットを開く",
                        "custom_id": "ticket_open",
                        "emoji": {"name": "🎫"},
                    }
                ],
            }
        ],
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"https://discord.com/api/v10/channels/{channel_id}/messages",
            headers={"Authorization": f"Bot {bot_token}", "Content-Type": "application/json"},
            json=payload,
        )

    if resp.status_code not in (200, 201):
        logger.error(
            "[discord_ticket_config] deploy-button failed tenant=%d ch=%s status=%d body=%s",
            tenant_id, channel_id, resp.status_code, resp.text[:200],
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
        table_name="discord_ticket_button",
        record_id=tenant_id,
        new_data={"channel_id": channel_id, "message_id": message_id},
    )
    await db.commit()
    await reset_tenant_context(db, tenant_id)

    logger.info(
        "[discord_ticket_config] deploy-button posted tenant=%d ch=%s msg=%s by user=%d",
        tenant_id, channel_id, message_id, current_user.id,
    )
    return DeployButtonResponse(message_id=message_id, channel_id=channel_id)
