"""Discord DM 受信 → 受信箱 DB 書き込みヘルパ。

Discord Bot が顧客からの DM を受信した際に呼ばれる。
仕入元の guild メッセージを処理する `inbound_writer.py` とは独立した経路。

### 設計判断

1. **テナントスキーマ切替**: Gateway は通常 FastAPI とは別プロセス（別コンテナ）で
   動作する。テナントスキーマに直接 INSERT するため、`SET search_path` を明示的に
   実行する。`tenant_id → schema = tenant_{id:03d}` の変換規則は `app.auth.dependencies`
   と同じ。

2. **Lead upsert**: `source = 'discord:<discord_user_id>'` を一意キーとして使用。
   既存の Messenger（`source = 'messenger:<PSID>'`）・Instagram（`source = 'instagram:<IGSID>'`）
   と同じパターン。

3. **meta_messages への格納**: `platform = 'discord'`, `direction = 'inbound'`。
   既存の `/conversations` API は `meta_messages` を検索するため追加変更不要。

4. **冪等性**: `discord_message_id → message_id` に格納し
   `ON CONFLICT (message_id) WHERE message_id IS NOT NULL DO NOTHING` で保護。
   `meta_messages.message_id` はテキスト型（migration 加工済み）。

5. **discord_dm_channel_id の保存**: 受信時に channel.id から取得し leads に保存。
   送信側（discord_sender.py）が DM チャンネルへの返信に使用する。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


def _schema(tenant_id: int) -> str:
    return f"tenant_{tenant_id:03d}"


async def _set_search_path(db: AsyncSession, tenant_id: int) -> None:
    schema = _schema(tenant_id)
    await db.execute(text(f"SET search_path TO {schema}, public"))


async def upsert_lead_and_message(
    db: AsyncSession,
    *,
    tenant_id: int,
    discord_user_id: str,
    sender_name: str,
    dm_channel_id: str,
    message_text: str,
    discord_message_id: str,
    created_at: datetime,
) -> None:
    """Discord DM 1 件を受信箱に反映する。

    処理:
      1. leads で source='discord:<user_id>' の行を検索、なければ新規作成
      2. discord_dm_channel_id が未設定なら UPDATE（チャンネル ID は固定）
      3. meta_messages に platform='discord', direction='inbound' で冪等 INSERT

    Args:
        db: AsyncSession（search_path を上書きして使用）
        tenant_id: テナント ID（スキーマ名の生成と RLS 用）
        discord_user_id: Discord ユーザー Snowflake ID（文字列）
        sender_name: discord.Member.display_name
        dm_channel_id: DMChannel の Snowflake ID（送信用）
        message_text: メッセージ本文
        discord_message_id: Discord Message Snowflake ID（冪等キー）
        created_at: message.created_at（Discord 側のタイムスタンプ）
    """
    await _set_search_path(db, tenant_id)
    schema = _schema(tenant_id)

    received_at = created_at
    if received_at.tzinfo is None:
        received_at = received_at.replace(tzinfo=timezone.utc)

    source = f"discord:{discord_user_id}"

    # --- 1. Lead の検索または新規作成 ---
    lead_row = await db.execute(
        text(f"SELECT id, discord_dm_channel_id FROM {schema}.leads "
             "WHERE source = :source AND tenant_id = :tenant_id LIMIT 1"),
        {"source": source, "tenant_id": tenant_id},
    )
    lead = lead_row.first()

    if lead is None:
        # 新規 lead 作成
        insert_lead = await db.execute(
            text(f"""
                INSERT INTO {schema}.leads
                    (tenant_id, customer_name, source, type, status,
                     discord_user_id, discord_dm_channel_id, created_at, updated_at)
                VALUES
                    (:tenant_id, :name, :source, 'prospect', '新規',
                     :discord_user_id, :dm_channel_id, NOW(), NOW())
                ON CONFLICT (source) WHERE source LIKE 'discord:%'
                DO NOTHING
                RETURNING id
            """),
            {
                "tenant_id": tenant_id,
                "name": sender_name or f"Discord User {discord_user_id}",
                "source": source,
                "discord_user_id": discord_user_id,
                "dm_channel_id": dm_channel_id,
            },
        )
        row = insert_lead.first()
        if row is None:
            # ON CONFLICT で既存行に負けた場合は再検索
            lead_row2 = await db.execute(
                text(f"SELECT id, discord_dm_channel_id FROM {schema}.leads "
                     "WHERE source = :source AND tenant_id = :tenant_id LIMIT 1"),
                {"source": source, "tenant_id": tenant_id},
            )
            lead = lead_row2.first()
            if lead is None:
                logger.error(
                    "[dm_writer] lead 取得失敗 tenant=%d user=%s", tenant_id, discord_user_id
                )
                await db.rollback()
                return
            lead_id = int(lead[0])
            existing_dm_channel_id = lead[1]
        else:
            lead_id = int(row[0])
            existing_dm_channel_id = None

        logger.info(
            "[dm_writer] 新規 lead 作成 tenant=%d lead_id=%d discord_user=%s",
            tenant_id, lead_id, discord_user_id,
        )
    else:
        lead_id = int(lead[0])
        existing_dm_channel_id = lead[1]

    # --- 2. discord_dm_channel_id が未設定なら更新 ---
    if existing_dm_channel_id is None:
        await db.execute(
            text(f"""
                UPDATE {schema}.leads
                   SET discord_user_id       = :user_id,
                       discord_dm_channel_id = :ch_id,
                       updated_at            = NOW()
                 WHERE id = :lead_id AND tenant_id = :tenant_id
            """),
            {
                "user_id": discord_user_id,
                "ch_id": dm_channel_id,
                "lead_id": lead_id,
                "tenant_id": tenant_id,
            },
        )

    # --- 3. meta_messages に冪等 INSERT ---
    insert_msg = await db.execute(
        text(f"""
            INSERT INTO {schema}.meta_messages
                (tenant_id, lead_id, platform, sender_id, sender_name,
                 message_text, direction, message_id, created_at)
            VALUES
                (:tenant_id, :lead_id, 'discord', :sender_id, :sender_name,
                 :text, 'inbound', :message_id, :created_at)
            ON CONFLICT (message_id) WHERE message_id IS NOT NULL
            DO NOTHING
            RETURNING id
        """),
        {
            "tenant_id": tenant_id,
            "lead_id": lead_id,
            "sender_id": discord_user_id,
            "sender_name": sender_name,
            "text": message_text,
            "message_id": discord_message_id,
            "created_at": received_at,
        },
    )
    msg_row = insert_msg.first()
    if msg_row is None:
        logger.debug(
            "[dm_writer] duplicate discord_message_id=%s skip", discord_message_id
        )
    else:
        logger.info(
            "[dm_writer] inbound 記録 tenant=%d lead=%d msg_id=%s",
            tenant_id, lead_id, discord_message_id,
        )

    await db.commit()
