"""
backend/app/services/messaging_window.py の単体テスト
（Phase 1-D Sprint 5、spec §3-3 / §5-4 / §5-5）。

24h / 7d ルールの境界値、`force_human_agent_tag` の挙動、
naive datetime の UTC 化、now 注入の挙動を網羅する。

実行:
    pytest backend/tests/test_messaging_window.py -v
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.messaging_window import (
    WindowState,
    compute_state,
    compute_window,
    messaging_type_for_state,
)


_NOW = datetime(2026, 4, 30, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# compute_state
# ---------------------------------------------------------------------------


def test_state_no_inbound_when_last_is_none():
    assert compute_state(None, now=_NOW) is WindowState.NO_INBOUND


def test_state_within_24h_when_1h_ago():
    last = _NOW - timedelta(hours=1)
    assert compute_state(last, now=_NOW) is WindowState.WITHIN_24H


def test_state_within_24h_at_exact_24h_boundary():
    """24h ちょうどは WITHIN_24H に含まれる（<= で判定）。"""
    last = _NOW - timedelta(hours=24)
    assert compute_state(last, now=_NOW) is WindowState.WITHIN_24H


def test_state_within_human_agent_just_after_24h():
    last = _NOW - timedelta(hours=24, seconds=1)
    assert compute_state(last, now=_NOW) is WindowState.WITHIN_HUMAN_AGENT


def test_state_within_human_agent_at_3_days():
    last = _NOW - timedelta(days=3)
    assert compute_state(last, now=_NOW) is WindowState.WITHIN_HUMAN_AGENT


def test_state_within_human_agent_at_exact_7d_boundary():
    """7d ちょうどは WITHIN_HUMAN_AGENT（境界は inclusive）。"""
    last = _NOW - timedelta(days=7)
    assert compute_state(last, now=_NOW) is WindowState.WITHIN_HUMAN_AGENT


def test_state_expired_just_after_7d():
    last = _NOW - timedelta(days=7, seconds=1)
    assert compute_state(last, now=_NOW) is WindowState.EXPIRED


def test_state_expired_at_30d():
    last = _NOW - timedelta(days=30)
    assert compute_state(last, now=_NOW) is WindowState.EXPIRED


def test_state_naive_datetime_treated_as_utc():
    """tzinfo がない datetime は UTC とみなす。"""
    last_naive = (_NOW - timedelta(hours=1)).replace(tzinfo=None)
    assert compute_state(last_naive, now=_NOW) is WindowState.WITHIN_24H


def test_state_uses_real_now_when_not_provided(monkeypatch):
    """now を明示しないとき datetime.now(UTC) を使う。"""
    import app.services.messaging_window as mod

    fake_now = datetime(2030, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

    class _DT(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return fake_now if tz is not None else fake_now.replace(tzinfo=None)

    monkeypatch.setattr(mod, "datetime", _DT)
    last = fake_now - timedelta(hours=2)
    assert compute_state(last) is WindowState.WITHIN_24H


# ---------------------------------------------------------------------------
# compute_window
# ---------------------------------------------------------------------------


def test_window_no_inbound_returns_all_false():
    win = compute_window(None, now=_NOW)
    assert win["last_inbound_at"] is None
    assert win["expires_at"] is None
    assert win["can_send_response"] is False
    assert win["requires_human_agent_tag"] is False
    assert win["can_send_at_all"] is False


def test_window_within_24h():
    last = _NOW - timedelta(hours=2)
    win = compute_window(last, now=_NOW)
    assert win["can_send_response"] is True
    assert win["requires_human_agent_tag"] is False
    assert win["can_send_at_all"] is True
    # expires_at = last_inbound_at + 24h
    assert win["expires_at"] == (last + timedelta(hours=24)).isoformat()
    assert win["last_inbound_at"] == last.isoformat()


def test_window_within_human_agent():
    last = _NOW - timedelta(days=3)
    win = compute_window(last, now=_NOW)
    assert win["can_send_response"] is False
    assert win["requires_human_agent_tag"] is True
    assert win["can_send_at_all"] is True


def test_window_expired():
    last = _NOW - timedelta(days=8)
    win = compute_window(last, now=_NOW)
    assert win["can_send_response"] is False
    assert win["requires_human_agent_tag"] is False
    assert win["can_send_at_all"] is False


def test_window_naive_input_is_normalized_to_utc_in_iso_output():
    """naive datetime を渡しても last_inbound_at は ISO + tz を含む。"""
    last_naive = datetime(2026, 4, 30, 11, 0, 0)  # naive
    win = compute_window(last_naive, now=_NOW)
    assert win["last_inbound_at"] is not None
    assert "+00:00" in win["last_inbound_at"]


# ---------------------------------------------------------------------------
# messaging_type_for_state
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("state,expected", [
    (WindowState.NO_INBOUND, (None, None)),
    (WindowState.EXPIRED, (None, None)),
])
def test_messaging_type_returns_none_for_expired_or_no_inbound(state, expected):
    assert messaging_type_for_state(state) == expected


def test_messaging_type_within_24h_default_response():
    # HUMAN_AGENT auto-apply 仕様 (dac01e3) に追随:
    # 24h 以内でも force 不要で MESSAGE_TAG=HUMAN_AGENT を付与する
    assert messaging_type_for_state(WindowState.WITHIN_24H) == ("MESSAGE_TAG", "HUMAN_AGENT")


def test_messaging_type_within_24h_with_force_returns_human_agent():
    """24h 以内でも `force_human_agent_tag=True` で MESSAGE_TAG=HUMAN_AGENT。"""
    assert messaging_type_for_state(WindowState.WITHIN_24H, force_human_agent_tag=True) == (
        "MESSAGE_TAG", "HUMAN_AGENT",
    )


def test_messaging_type_within_human_agent_returns_message_tag():
    assert messaging_type_for_state(WindowState.WITHIN_HUMAN_AGENT) == (
        "MESSAGE_TAG", "HUMAN_AGENT",
    )


def test_messaging_type_force_does_not_override_expired():
    """force でも EXPIRED は送信不可（None, None を返す）。"""
    assert messaging_type_for_state(WindowState.EXPIRED, force_human_agent_tag=True) == (None, None)
