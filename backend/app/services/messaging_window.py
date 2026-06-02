from __future__ import annotations

"""
Meta Messenger / Instagram の 24h ルール（messaging window）判定ヘルパ。

Phase 1-D Sprint 5 で `backend/app/routers/leads.py` から切り出し
（Sprint 4 Reviewer F5 follow-up）。Sprint 5 の送信判定（`POST
/api/v1/leads/{lead_id}/messages`）でも同じロジックを再利用する。

たとえ話:
  「お客さんから最後に話しかけられた時刻」を起点に、
    - 24 時間以内: 通常の RESPONSE で返信できる
    - 24 時間〜7 日: Human Agent Tag を付ければ返信できる
    - 7 日超過: もう Meta 経由では送信不可
  という Meta の仕様を、サーバー側で一元的に判定する。

設計判断:
  - 純関数として実装し、DB / 認証 / ロギングに依存しない
  - timezone-aware UTC datetime を期待する。naive 値が来た場合は UTC とみなす
  - `compute_state(...)` は WindowState（IntEnum）を返す。
    `compute_window(...)` は spec §5-4 の messaging_window レスポンス構造を
    そのまま返す（既存 leads.py の `_compute_messaging_window` 互換）

使い方::

    from app.services import messaging_window as mw

    state = mw.compute_state(last_inbound_at)
    if state == mw.WindowState.EXPIRED:
        raise HTTPException(400, "...")
    if state == mw.WindowState.WITHIN_HUMAN_AGENT:
        messaging_type, tag = "MESSAGE_TAG", "HUMAN_AGENT"
    else:
        messaging_type, tag = "RESPONSE", None
"""

from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional

# spec §3-3 / §5-4 / §5-5 の messaging window 境界
RESPONSE_WINDOW_HOURS = 24
HUMAN_AGENT_WINDOW_DAYS = 7


class WindowState(str, Enum):
    """messaging window の 4 状態。

    値は判定結果のラベル。`Enum.value` を直接 audit_log 等に出して可読。
    """

    NO_INBOUND = "no_inbound"            # inbound 履歴なし → 送信不可
    WITHIN_24H = "within_24h"            # 24 時間以内 → RESPONSE
    WITHIN_HUMAN_AGENT = "within_human_agent"  # 24h-7d → MESSAGE_TAG=HUMAN_AGENT
    EXPIRED = "expired"                  # 7d 超 → 送信不可


def _to_aware_utc(value: Optional[datetime]) -> Optional[datetime]:
    """naive datetime を UTC とみなして tz-aware にする。None はそのまま。"""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def compute_state(
    last_inbound_at: Optional[datetime],
    *,
    now: Optional[datetime] = None,
) -> WindowState:
    """24h / 7d ルールに基づき WindowState を返す。

    Args:
        last_inbound_at: 最新の inbound メッセージの created_at。None なら inbound 履歴なし扱い。
        now: 評価時刻（テスト用に注入可能）。None のとき datetime.now(UTC)。

    Returns:
        WindowState の 4 値のいずれか。
    """
    last = _to_aware_utc(last_inbound_at)
    if last is None:
        return WindowState.NO_INBOUND
    current = _to_aware_utc(now) if now is not None else datetime.now(timezone.utc)
    elapsed = current - last
    if elapsed <= timedelta(hours=RESPONSE_WINDOW_HOURS):
        return WindowState.WITHIN_24H
    if elapsed <= timedelta(days=HUMAN_AGENT_WINDOW_DAYS):
        return WindowState.WITHIN_HUMAN_AGENT
    return WindowState.EXPIRED


def compute_window(
    last_inbound_at: Optional[datetime],
    *,
    now: Optional[datetime] = None,
) -> dict:
    """spec §5-4 の `messaging_window` レスポンス構造を組み立てる。

    返却 keys:
        last_inbound_at, expires_at, can_send_response,
        requires_human_agent_tag, can_send_at_all

    各 bool は 4 つの WindowState から派生:
        - WITHIN_24H              -> can_send_response=True / can_send_at_all=True
        - WITHIN_HUMAN_AGENT      -> requires_human_agent_tag=True / can_send_at_all=True
        - EXPIRED, NO_INBOUND     -> 全 False

    Frontend の `MessagingWindowBanner` は can_send_response → 緑、
    requires_human_agent_tag → 黄、!can_send_at_all → 赤、で 3 段階表示する。
    """
    last = _to_aware_utc(last_inbound_at)
    state = compute_state(last, now=now)

    if last is None:
        return {
            "last_inbound_at": None,
            "expires_at": None,
            "can_send_response": False,
            "requires_human_agent_tag": False,
            "can_send_at_all": False,
        }

    expires_at = last + timedelta(hours=RESPONSE_WINDOW_HOURS)
    return {
        "last_inbound_at": last.isoformat(),
        "expires_at": expires_at.isoformat(),
        "can_send_response": state == WindowState.WITHIN_24H,
        "requires_human_agent_tag": state == WindowState.WITHIN_HUMAN_AGENT,
        "can_send_at_all": state in (WindowState.WITHIN_24H, WindowState.WITHIN_HUMAN_AGENT),
    }


def messaging_type_for_state(
    state: WindowState,
    *,
    force_human_agent_tag: bool = False,  # 後方互換のため引数は残す（無視）
) -> tuple[Optional[str], Optional[str]]:
    """送信時の (messaging_type, message_tag) を決める。

    - EXPIRED / NO_INBOUND → (None, None)（呼び出し側が 400 を返すべき）
    - WITHIN_24H → ("RESPONSE", None)
    - WITHIN_HUMAN_AGENT → ("MESSAGE_TAG", "HUMAN_AGENT")（Meta要審査承認）
    """
    if state in (WindowState.EXPIRED, WindowState.NO_INBOUND):
        return (None, None)
    if state == WindowState.WITHIN_HUMAN_AGENT:
        return ("MESSAGE_TAG", "HUMAN_AGENT")
    return ("RESPONSE", None)


__all__ = [
    "WindowState",
    "RESPONSE_WINDOW_HOURS",
    "HUMAN_AGENT_WINDOW_DAYS",
    "compute_state",
    "compute_window",
    "messaging_type_for_state",
]
