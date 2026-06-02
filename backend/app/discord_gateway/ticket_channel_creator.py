"""チケットチャンネル作成サービス (ADR-091 KPI3 Phase 2).

顧客がボタンを押したとき、専用プライベートチャンネルを冪等に作成する。

フロー:
  1. DB から tenant_discord_ticket_config を取得
  2. leads で discord_user_id を検索（既存チャンネルID確認）
  3. チャンネルが既存なら Guild から取得して返す（冪等）
  4. 新規なら category 配下に private channel を作成
     - @everyone: view 禁止
     - member: view / send / history 許可
     - staff_role（設定済みなら）: view / send / history 許可
  5. ウェルカムメッセージを送信
  6. leads.discord_guild_channel_id を更新
"""
from __future__ import annotations

import logging
from typing import Any

import discord
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_DEFAULT_WELCOME = "ご連絡ありがとうございます。こちらのチャンネルでサポートいたします。"


async def get_ticket_config(session: AsyncSession, tenant_id: int) -> dict | None:
    """tenant_discord_ticket_config を取得する。未設定なら None。"""
    result = await session.execute(
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
        return None
    return dict(row)


async def _get_existing_channel_id(
    session: AsyncSession,
    tenant_id: int,
    discord_user_id: str,
) -> str | None:
    """leads.discord_guild_channel_id を返す。未設定なら None。"""
    schema = f"tenant_{tenant_id:03d}"
    result = await session.execute(
        text(f"""
            SELECT discord_guild_channel_id
            FROM {schema}.leads
            WHERE discord_user_id = :uid
            LIMIT 1
        """),  # noqa: S608
        {"uid": discord_user_id},
    )
    row = result.first()
    if not row or not row[0]:
        return None
    return str(row[0])


async def _update_lead_channel_id(
    session: AsyncSession,
    tenant_id: int,
    discord_user_id: str,
    channel_id: str,
) -> None:
    """leads.discord_guild_channel_id を更新する。"""
    schema = f"tenant_{tenant_id:03d}"
    await session.execute(
        text(f"""
            UPDATE {schema}.leads
            SET discord_guild_channel_id = :ch_id,
                updated_at = NOW()
            WHERE discord_user_id = :uid
        """),
        {"ch_id": channel_id, "uid": discord_user_id},
    )


def _channel_name_for(member: discord.Member) -> str:
    """チャンネル名を生成する。Discord の命名制限 (小文字・ハイフン) に準拠。"""
    safe_name = "".join(
        c if c.isalnum() or c == "-" else "-"
        for c in member.display_name.lower()
    ).strip("-")[:20] or "customer"
    user_suffix = str(member.id)[-4:]
    return f"ticket-{safe_name}-{user_suffix}"


async def get_or_create_ticket_channel(
    guild: discord.Guild,
    config: dict,
    member: discord.Member,
    tenant_id: int,
    db_factory: Any,
) -> discord.TextChannel | None:
    """チケットチャンネルを冪等に取得または作成する。

    Returns:
        作成/取得したチャンネル。設定不備 or 権限エラーの場合 None。
    """
    category_id = int(config["ticket_category_id"])
    staff_role_id = config.get("staff_role_id")
    welcome_template = config.get("welcome_template") or _DEFAULT_WELCOME

    category = guild.get_channel(category_id)
    if not isinstance(category, discord.CategoryChannel):
        logger.error(
            "[ticket] category not found or not a CategoryChannel: %s tenant=%d",
            category_id,
            tenant_id,
        )
        return None

    discord_user_id = str(member.id)

    # 既存チャンネル確認（冪等）
    async with db_factory() as session:
        existing_ch_id = await _get_existing_channel_id(session, tenant_id, discord_user_id)

    if existing_ch_id:
        ch = guild.get_channel(int(existing_ch_id))
        if isinstance(ch, discord.TextChannel):
            logger.info(
                "[ticket] existing channel %s returned for user=%s tenant=%d",
                existing_ch_id,
                discord_user_id,
                tenant_id,
            )
            return ch
        # チャンネルが削除済みの場合は再作成へ
        logger.warning(
            "[ticket] stored channel_id=%s not found in guild, recreating for user=%s",
            existing_ch_id,
            discord_user_id,
        )

    # 権限設定
    overwrites: dict[Any, discord.PermissionOverwrite] = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        member: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
        ),
    }
    if staff_role_id:
        staff_role = guild.get_role(int(staff_role_id))
        if staff_role:
            overwrites[staff_role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
            )
        else:
            logger.warning(
                "[ticket] staff_role_id=%s not found in guild tenant=%d",
                staff_role_id,
                tenant_id,
            )

    channel_name = _channel_name_for(member)
    try:
        new_channel = await guild.create_text_channel(
            name=channel_name,
            category=category,
            overwrites=overwrites,
            reason=f"SalesAnchor ticket for {member.display_name}",
        )
    except discord.Forbidden:
        logger.error(
            "[ticket] Forbidden: cannot create channel in category=%s tenant=%d",
            category_id,
            tenant_id,
        )
        return None
    except discord.HTTPException as exc:
        logger.error(
            "[ticket] HTTPException creating channel tenant=%d: %s",
            tenant_id,
            exc,
        )
        return None

    logger.info(
        "[ticket] created channel=%s (%s) for user=%s tenant=%d",
        new_channel.id,
        channel_name,
        discord_user_id,
        tenant_id,
    )

    # ウェルカムメッセージ送信
    try:
        await new_channel.send(welcome_template)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[ticket] failed to send welcome message: %s", exc)

    # leads.discord_guild_channel_id 更新
    async with db_factory() as session:
        await _update_lead_channel_id(
            session,
            tenant_id=tenant_id,
            discord_user_id=discord_user_id,
            channel_id=str(new_channel.id),
        )
        await session.commit()

    return new_channel
