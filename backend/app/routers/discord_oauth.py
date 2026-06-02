"""Discord OAuth2 Bot Invite フロー (ADR-091 拡張)

Bot をテナントの Discord サーバーに招待し、guild_id を自動保存する。

API:
  POST /discord/oauth/start    — Invite URL を発行（認証必須）
  GET  /discord/oauth/callback — Discord からのコールバック（公開エンドポイント）

フロー:
  1. フロントが POST /start → invite_url を受け取る
  2. ユーザーが invite_url を開き Discord サーバーを選択
  3. Discord が GET /callback?guild_id=...&state=... にリダイレクト
  4. state 検証 → guild_id を tenant_discord_config に保存
  5. フロントエンドの /channels?discord_status=connected にリダイレクト

前提:
  Discord Developer Portal → OAuth2 → Redirects に
  https://api.salesanchor.jp/api/v1/discord/oauth/callback を登録済みであること。
"""
from __future__ import annotations

import logging
import os
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
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
from app.services import oauth_state
from app.services.audit import record_audit_log

logger = logging.getLogger(__name__)
router = APIRouter()

_DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID", "1499458730171961535")
_DISCORD_PERMISSIONS = "268504082"
_DISCORD_CALLBACK_URL = os.getenv(
    "DISCORD_CALLBACK_URL",
    "https://api.salesanchor.jp/api/v1/discord/oauth/callback",
)
_FRONTEND_BASE_URL = os.getenv("FRONTEND_BASE_URL") or "https://app.salesanchor.jp"


def _build_invite_url(state: str) -> str:
    params = {
        "client_id": _DISCORD_CLIENT_ID,
        "permissions": _DISCORD_PERMISSIONS,
        "integration_type": "0",
        "scope": "bot",
        "redirect_uri": _DISCORD_CALLBACK_URL,
        "state": state,
    }
    return f"https://discord.com/oauth2/authorize?{urlencode(params)}"


# ---------------------------------------------------------------------------
# POST /discord/oauth/start
# ---------------------------------------------------------------------------


@router.post(
    "/discord/oauth/start",
    dependencies=[Depends(require_permission("channels.manage"))],
)
async def discord_oauth_start(
    current_user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
) -> dict:
    """Discord Bot Invite URL を発行し、state を Redis に保存する。"""
    try:
        issued = await oauth_state.issue_state(
            tenant_id=tenant_id,
            staff_id=current_user.id,
        )
    except oauth_state.OAuthStateError as e:
        logger.error("[discord_oauth] state 発行失敗: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="一時的に Discord 連携を開始できません（Redis 接続失敗）",
        )

    invite_url = _build_invite_url(issued["state"])  # type: ignore[arg-type]
    logger.info("[discord_oauth] invite URL 発行 tenant=%d", tenant_id)
    return {
        "invite_url": invite_url,
        "state": issued["state"],
        "expires_at": issued["expires_at"],
    }


# ---------------------------------------------------------------------------
# GET /discord/oauth/callback  （公開エンドポイント: Discord からのリダイレクト）
# ---------------------------------------------------------------------------


@router.get("/discord/oauth/callback")
async def discord_oauth_callback(
    guild_id: str | None = Query(None),
    state: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """Discord からのコールバック。guild_id を tenant_discord_config に保存する。

    このエンドポイントは Discord からのリダイレクトなので JWT 認証なし。
    tenant_id は state ペイロードから取得する（CSRF 対策: state は one-time 使用）。
    """
    channels_url = f"{_FRONTEND_BASE_URL}/channels"

    if not state:
        return RedirectResponse(f"{channels_url}?discord_status=error&reason=missing_state")

    if not guild_id:
        # ユーザーがサーバー選択をキャンセルした場合など
        return RedirectResponse(f"{channels_url}?discord_status=error&reason=missing_guild_id")

    # state 検証（one-time: 検証後に Redis から削除）
    try:
        payload = await oauth_state.consume_state(state)
    except oauth_state.OAuthStateError:
        logger.error("[discord_oauth] Redis 接続失敗")
        return RedirectResponse(f"{channels_url}?discord_status=error&reason=redis_error")

    if payload is None:
        logger.warning("[discord_oauth] 無効な state（期限切れ・改ざん・再利用の可能性）")
        return RedirectResponse(f"{channels_url}?discord_status=error&reason=invalid_state")

    tenant_id = payload.get("tenant_id")
    staff_id = payload.get("staff_id")
    if not tenant_id:
        return RedirectResponse(f"{channels_url}?discord_status=error&reason=invalid_payload")

    tenant_id = int(tenant_id)

    # guild_id を upsert
    await db.execute(
        text("""
            INSERT INTO public.tenant_discord_config (tenant_id, guild_id)
            VALUES (:tid, :guild_id)
            ON CONFLICT (tenant_id)
            DO UPDATE SET guild_id = EXCLUDED.guild_id, updated_at = NOW()
        """),
        {"tid": tenant_id, "guild_id": guild_id},
    )
    await record_audit_log(
        db=db,
        tenant_id=tenant_id,
        user_id=int(staff_id) if staff_id else tenant_id,
        action="update",
        table_name="tenant_discord_config",
        record_id=tenant_id,
        new_data={"guild_id": guild_id, "source": "discord_oauth_callback"},
    )
    await db.commit()
    await reset_tenant_context(db, tenant_id)  # ADR-072

    logger.info(
        "[discord_oauth] guild_id 保存 tenant=%d guild_id=%s", tenant_id, guild_id
    )
    return RedirectResponse(f"{channels_url}?discord_status=connected")
