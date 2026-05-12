from __future__ import annotations

"""
業務日（JST）基準の時刻ヘルパ。

ADR-021 J2 fix (2026-05-13):
  月次集計 (/financials/monthly, /commissions/monthly) の境界を
  JST 暦月で扱うために導入。

設計:
  - 業務日締めは JST 23:59:59 固定。テナント別の TZ カスタマイズは
    非対応（Non-goal N3）。
  - SQL バインドは UTC aware datetime を渡し、TIMESTAMPTZ 比較で
    自然に正しく評価させる。テスト DB の SQLite では ISO 形式 UTC
    文字列の辞書順比較で順序が保たれる前提。
  - SQL 側で `AT TIME ZONE` 等を使うと SQLite テストで動かないため、
    変換は Python 側で完結させる。

参照:
  spec.md `## J2 設計詳細：JST 月次境界`
"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

# 業務日（JST 固定）
JST = ZoneInfo("Asia/Tokyo")


def _jst_month_range_utc(year: int, month: int) -> tuple[datetime, datetime]:
    """JST の暦月 [year-month-01 00:00:00, +1 month) を UTC datetime で返す。

    返り値は両方とも tzinfo=UTC（aware）。SQL バインドで TIMESTAMPTZ
    比較に使うほか、テスト DB の TEXT 比較でも ISO UTC 文字列として
    辞書順比較が成立する。

    例:
        _jst_month_range_utc(2026, 5)
        → (datetime(2026, 4, 30, 15, 0, 0, tzinfo=UTC),
           datetime(2026, 5, 31, 15, 0, 0, tzinfo=UTC))
        # JST 2026-05-01 00:00 〜 JST 2026-06-01 00:00 に対応

    Args:
        year: 西暦年（2000-2999 想定。バリデーションは router 側）
        month: 月（1-12 想定。バリデーションは router 側）

    Returns:
        (start_utc, end_utc) のタプル。半開区間 [start, end)。
    """
    start_jst = datetime(year, month, 1, 0, 0, 0, tzinfo=JST)
    if month == 12:
        end_jst = datetime(year + 1, 1, 1, 0, 0, 0, tzinfo=JST)
    else:
        end_jst = datetime(year, month + 1, 1, 0, 0, 0, tzinfo=JST)
    return start_jst.astimezone(timezone.utc), end_jst.astimezone(timezone.utc)
