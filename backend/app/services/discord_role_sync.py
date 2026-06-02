"""Discord ロール自動同期サービス (Sprint D2 / F2).

estimated_scale (Small/Large) → Discord ロール の自動付与。
ロール名は tenant_discord_ticket_config.small_role_name / large_role_name で設定可能。
ボットがロールを自動作成。CRM API レスポンスをブロックしない（非同期タスク）。

使用方法:
    asyncio.create_task(
        sync_lead_discord_role(
            tenant_id=tenant_id,
            lead_id=lead_id,
            discord_user_id=discord_user_id,
            new_scale="Large",
        )
    )

ロールマッピング（DB から取得、デフォルト値）:
  Small  → small_role_name (デフォルト: "Member", Bot が未存在時に自動作成)
  Large  → large_role_name (デフォルト: "Partner", Bot が未存在時に自動作成)
  Medium → マッピングなし（スキップ）
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from sqlalchemy import text

from app.services.discord_rest import DiscordAPIError, discord_api_request

logger = logging.getLogger(__name__)

# estimated_scale → DB カラム名のマッピング
_SCALE_TO_COLUMN: dict[str, str] = {
    "Small": "small_role_name",
    "Large": "large_role_name",
}

# デフォルト値（DB 未設定 / 行未作成時のフォールバック）
_DEFAULT_ROLE_NAMES: dict[str, str] = {
    "Small": "Member",
    "Large": "Partner",
}


def _get_bot_token(tenant_id: int) -> str | None:
    return os.environ.get(f"DISCORD_BOT_TOKEN_{tenant_id}") or None


async def _get_guild_and_role_names(
    tenant_id: int,
) -> tuple[str | None, str, str]:
    """tenant_discord_config と tenant_discord_ticket_config から
    guild_id / small_role_name / large_role_name を一括取得する。
    """
    from app.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            text("""
                SELECT dc.guild_id,
                       COALESCE(tc.small_role_name, 'Member')  AS small_role_name,
                       COALESCE(tc.large_role_name, 'Partner') AS large_role_name
                FROM public.tenant_discord_config dc
                LEFT JOIN public.tenant_discord_ticket_config tc
                       ON tc.tenant_id = dc.tenant_id
                WHERE dc.tenant_id = :tid
            """),
            {"tid": tenant_id},
        )
        row = result.mappings().first()
        if not row:
            return None, "Member", "Partner"
        return (
            str(row["guild_id"]) if row["guild_id"] else None,
            row["small_role_name"],
            row["large_role_name"],
        )


async def _get_or_create_role(
    bot_token: str,
    guild_id: str,
    role_name: str,
    existing_roles: list[dict[str, Any]],
) -> str:
    """ロール一覧から role_name を探し、なければ作成してロール ID を返す。

    AC2.2: ロールが存在しない場合、Bot が自動作成する。
    """
    for role in existing_roles:
        if role.get("name") == role_name:
            return str(role["id"])

    logger.info(
        "[discord_role_sync] creating role '%s' on guild %s",
        role_name, guild_id,
    )
    created = await discord_api_request(
        method="POST",
        path=f"/guilds/{guild_id}/roles",
        bot_token=bot_token,
        json={"name": role_name},
        expected_statuses=(200,),
    )
    assert created is not None
    return str(created["id"])


async def _update_sync_status(
    tenant_id: int,
    lead_id: int,
    sync_status: str,
) -> None:
    """leads テーブルの discord_role_sync_status を更新する。"""
    schema = f"tenant_{tenant_id:03d}"
    from app.database import AsyncSessionLocal
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(
                text(f"""
                    UPDATE {schema}.leads
                       SET discord_role_sync_status = :status,
                           discord_role_sync_at = NOW()
                     WHERE id = :lead_id
                """),
                {"status": sync_status, "lead_id": lead_id},
            )
            await db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[discord_role_sync] sync_status update failed lead=%d: %s",
            lead_id, exc,
        )


async def sync_lead_discord_role(
    *,
    tenant_id: int,
    lead_id: int,
    discord_user_id: str,
    new_scale: str,
) -> None:
    """estimated_scale 変更時に Discord ロールを非同期更新する。

    AC2.1: scale 変更から 10 秒以内に Discord ロール更新
    AC2.2: 未存在ロールは自動作成
    AC2.4: 429 → retry_after 尊重 (discord_rest 経由)
    AC2.5: 5xx → 指数バックオフ (discord_rest 経由)
    AC2.6: discord_user_id が NULL → 呼び出し元でスキップ済み（防御チェック）
    AC2.7: 非同期実行 (CRM API 応答をブロックしない)
    AC2.8: discord_role_sync_status を leads に記録
    """
    if not discord_user_id:
        logger.info(
            "[discord_role_sync] skip: discord_user_id null lead=%d", lead_id,
        )
        return

    if new_scale not in _SCALE_TO_COLUMN:
        # Medium など: マッピングなし → スキップ (info のみ)
        logger.info(
            "[discord_role_sync] skip: no role mapping for scale='%s' lead=%d",
            new_scale, lead_id,
        )
        return

    bot_token = _get_bot_token(tenant_id)
    if not bot_token:
        logger.warning(
            "[discord_role_sync] DISCORD_BOT_TOKEN_%d 未設定 lead=%d",
            tenant_id, lead_id,
        )
        await _update_sync_status(tenant_id, lead_id, "failed")
        return

    # DB からロール名と guild_id を取得
    guild_id, small_role_name, large_role_name = await _get_guild_and_role_names(tenant_id)
    if not guild_id:
        logger.info(
            "[discord_role_sync] guild_id 未設定 tenant=%d lead=%d — スキップ",
            tenant_id, lead_id,
        )
        return

    scale_to_role = {"Small": small_role_name, "Large": large_role_name}
    managed_role_names = frozenset(scale_to_role.values())
    role_name = scale_to_role[new_scale]

    try:
        # 1. ギルド全ロール取得
        all_roles = await discord_api_request(
            method="GET",
            path=f"/guilds/{guild_id}/roles",
            bot_token=bot_token,
            expected_statuses=(200,),
        ) or []

        # 2. 付与するロール ID を解決（なければ作成）
        target_role_id = await _get_or_create_role(
            bot_token, guild_id, role_name, all_roles,
        )

        # 3. 削除対象（他の管理ロール）の ID を収集
        other_managed_ids: set[str] = set()
        for r in all_roles:
            if r.get("name") in managed_role_names and r.get("name") != role_name:
                other_managed_ids.add(str(r["id"]))

        # 4. メンバーの現在ロール取得
        member = await discord_api_request(
            method="GET",
            path=f"/guilds/{guild_id}/members/{discord_user_id}",
            bot_token=bot_token,
            expected_statuses=(200,),
        ) or {}
        current_role_ids = {str(r) for r in member.get("roles", [])}

        # 5. 新ロール付与
        await discord_api_request(
            method="PUT",
            path=f"/guilds/{guild_id}/members/{discord_user_id}/roles/{target_role_id}",
            bot_token=bot_token,
            expected_statuses=(204,),
        )

        # 6. 旧管理ロール削除（現在保持しているもののみ）
        for old_id in other_managed_ids & current_role_ids:
            await discord_api_request(
                method="DELETE",
                path=f"/guilds/{guild_id}/members/{discord_user_id}/roles/{old_id}",
                bot_token=bot_token,
                expected_statuses=(204,),
            )

        logger.info(
            "[discord_role_sync] success tenant=%d lead=%d user=%s role=%s",
            tenant_id, lead_id, discord_user_id, role_name,
        )
        await _update_sync_status(tenant_id, lead_id, "success")

    except DiscordAPIError as exc:
        logger.error(
            "[discord_role_sync] failed tenant=%d lead=%d user=%s: %s",
            tenant_id, lead_id, discord_user_id, exc,
        )
        await _update_sync_status(tenant_id, lead_id, "failed")
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "[discord_role_sync] unexpected error tenant=%d lead=%d: %s",
            tenant_id, lead_id, exc,
        )
        await _update_sync_status(tenant_id, lead_id, "failed")
