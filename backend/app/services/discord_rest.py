"""Discord REST API 共通レジリエンスレイヤー (Sprint D2 / F6).

全 Discord REST 呼び出しをここに集約し、以下を一元処理:
  - 429 Rate Limit: retry_after を尊重してリトライ (AC6.1)
  - 5xx Server Error: 指数バックオフでリトライ (base 5s, max 60s, max 5回) (AC6.2)
  - 最大リトライ消費後: DiscordAPIError を raise + 全コンテキストをログ (AC6.3)
  - 全呼び出しを INFO / WARNING / ERROR レベルでログ (AC6.4)
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_DISCORD_API_BASE = "https://discord.com/api/v10"
_TIMEOUT_SEC = 10.0
_MAX_RETRIES = 5
_BACKOFF_BASE_SEC = 5
_BACKOFF_MAX_SEC = 60


class DiscordAPIError(Exception):
    """Discord REST API 呼び出し失敗（最大リトライ消費後）。"""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


async def discord_api_request(
    *,
    method: str,
    path: str,
    bot_token: str,
    json: dict[str, Any] | None = None,
    expected_statuses: tuple[int, ...] = (200, 201, 204),
) -> dict[str, Any] | None:
    """Discord REST API を呼び出す共通関数。

    Returns:
        成功時: JSON レスポンス dict。204 No Content の場合は None。

    Raises:
        DiscordAPIError: 最大リトライ消費後、または非リトライエラー。
    """
    url = f"{_DISCORD_API_BASE}{path}"
    headers = {
        "Authorization": f"Bot {bot_token}",
        "Content-Type": "application/json",
    }

    backoff = _BACKOFF_BASE_SEC
    attempt = 0

    while True:
        attempt += 1
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT_SEC) as client:
                response = await client.request(
                    method,
                    url,
                    json=json,
                    headers=headers,
                )
        except httpx.RequestError as exc:
            logger.warning(
                "[discord_rest] network error method=%s path=%s attempt=%d/%d: %s",
                method, path, attempt, _MAX_RETRIES, exc,
            )
            if attempt >= _MAX_RETRIES:
                raise DiscordAPIError(
                    f"Discord API ネットワークエラー: {exc}"
                ) from exc
            await asyncio.sleep(min(backoff, _BACKOFF_MAX_SEC))
            backoff = min(backoff * 2, _BACKOFF_MAX_SEC)
            continue

        http_status = response.status_code

        if http_status in expected_statuses:
            logger.info(
                "[discord_rest] success method=%s path=%s status=%d attempt=%d",
                method, path, http_status, attempt,
            )
            if http_status == 204:
                return None
            return response.json()

        # AC6.1: Rate limit — retry_after を尊重
        if http_status == 429:
            try:
                retry_after = float(response.json().get("retry_after", 1.0))
            except Exception:
                retry_after = 1.0
            logger.warning(
                "[discord_rest] rate limited method=%s path=%s retry_after=%.1fs attempt=%d/%d",
                method, path, retry_after, attempt, _MAX_RETRIES,
            )
            if attempt >= _MAX_RETRIES:
                raise DiscordAPIError(
                    f"Discord API レートリミット: {_MAX_RETRIES}回リトライ後も超過",
                    status_code=429,
                )
            await asyncio.sleep(retry_after)
            continue  # backoff を進めない

        # AC6.2: Server error — 指数バックオフ
        if 500 <= http_status < 600:
            body = response.text[:200]
            logger.warning(
                "[discord_rest] server error method=%s path=%s status=%d attempt=%d/%d body=%s",
                method, path, http_status, attempt, _MAX_RETRIES, body,
            )
            if attempt >= _MAX_RETRIES:
                raise DiscordAPIError(
                    f"Discord API サーバーエラー: HTTP {http_status}",
                    status_code=http_status,
                )
            await asyncio.sleep(min(backoff, _BACKOFF_MAX_SEC))
            backoff = min(backoff * 2, _BACKOFF_MAX_SEC)
            continue

        # その他のエラー: リトライしない
        body = response.text[:300]
        logger.error(
            "[discord_rest] api error method=%s path=%s status=%d body=%s",
            method, path, http_status, body,
        )
        raise DiscordAPIError(
            f"Discord API エラー: HTTP {http_status}: {body}",
            status_code=http_status,
        )
