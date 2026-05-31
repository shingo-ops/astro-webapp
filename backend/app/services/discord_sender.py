"""Discord Bot HTTP API 経由で DM を送信するサービス。

Gateway（discord.py WebSocket）とは独立した httpx HTTP クライアント実装。
Gateway が別コンテナで動作していても使用可能。

### 設計判断

- Gateway と FastAPI は別プロセス（別コンテナ）のため、
  in-process bot registry は使用しない。
- Discord REST API v10 を httpx で直接叩く。
- Bot Token は環境変数 `DISCORD_BOT_TOKEN_<TENANT_ID>` から取得（Gateway と同じ）。
- `discord_dm_channel_id` は受信時に leads テーブルに保存済み。
  DM チャンネルは user-bot 固有の永続チャンネルで変わらない。
"""
from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger(__name__)

_DISCORD_API_BASE = "https://discord.com/api/v10"
_TIMEOUT_SEC = 10.0


class DiscordSendError(Exception):
    """Discord DM 送信失敗。"""


def _get_bot_token(tenant_id: int) -> str | None:
    """環境変数 DISCORD_BOT_TOKEN_<TENANT_ID> からトークンを取得する。"""
    return os.environ.get(f"DISCORD_BOT_TOKEN_{tenant_id}") or None


async def send_discord_dm(
    *,
    tenant_id: int,
    dm_channel_id: str,
    text: str,
) -> str:
    """Discord DM チャンネルにメッセージを送信し、送信済みメッセージの Snowflake ID を返す。

    Args:
        tenant_id: テナント ID（Bot Token の環境変数サフィックスに使用）
        dm_channel_id: 送信先 DM チャンネルの Snowflake ID（leads.discord_dm_channel_id）
        text: 送信するメッセージ本文（最大 2000 文字は呼び出し側で保証）

    Returns:
        送信済みメッセージの Snowflake ID（文字列）

    Raises:
        DiscordSendError: Bot Token 未設定 / Discord API エラー
    """
    token = _get_bot_token(tenant_id)
    if not token:
        raise DiscordSendError(
            f"DISCORD_BOT_TOKEN_{tenant_id} が未設定です。"
            "GitHub Secrets / VPS 環境変数を確認してください。"
        )

    url = f"{_DISCORD_API_BASE}/channels/{dm_channel_id}/messages"
    headers = {
        "Authorization": f"Bot {token}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=_TIMEOUT_SEC) as client:
        response = await client.post(url, json={"content": text}, headers=headers)

    if response.status_code not in (200, 201):
        body = response.text[:300]
        logger.warning(
            "[discord_sender] 送信失敗 tenant=%d ch=%s status=%d body=%s",
            tenant_id, dm_channel_id, response.status_code, body,
        )
        raise DiscordSendError(
            f"Discord API HTTP {response.status_code}: {body}"
        )

    data = response.json()
    msg_id = str(data.get("id", ""))
    logger.info(
        "[discord_sender] 送信成功 tenant=%d ch=%s discord_msg_id=%s",
        tenant_id, dm_channel_id, msg_id,
    )
    return msg_id
