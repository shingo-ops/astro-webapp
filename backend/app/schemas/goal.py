from __future__ import annotations

"""
目標管理 (goals) 用 Pydantic スキーマ。

変更履歴:
  2026-05-25: 初版作成（ダッシュボード強化）
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

KpiType = Literal["revenue", "deal_count", "close_rate", "lead_count", "conversion_rate"]
PeriodType = Literal["monthly", "weekly"]


class GoalCreate(BaseModel):
    """目標作成リクエスト"""
    user_id: int | None = Field(default=None, ge=1, description="個人目標の場合のユーザーID")
    team_id: int | None = Field(default=None, ge=1, description="チーム目標の場合のチームID")
    period_type: PeriodType
    period_year: int = Field(ge=2020, le=2100)
    period_num: int = Field(ge=1, le=53, description="月の場合 1-12、週の場合 1-53")
    kpi_type: KpiType
    target_value: float = Field(ge=0)


class GoalUpdate(BaseModel):
    """目標更新リクエスト（target_value のみ更新可）"""
    target_value: float = Field(ge=0)


class GoalResponse(BaseModel):
    """目標レスポンス"""
    id: int
    user_id: int | None
    team_id: int | None
    period_type: PeriodType
    period_year: int
    period_num: int
    kpi_type: KpiType
    target_value: float
    created_by: int | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class GoalWithActual(BaseModel):
    """目標 + 実績（ダッシュボード表示用）"""
    id: int | None = None
    user_id: int | None = None
    team_id: int | None = None
    period_type: PeriodType
    period_year: int
    period_num: int
    kpi_type: KpiType
    target_value: float = 0.0
    actual_value: float = 0.0
    achievement_rate: float = 0.0  # actual / target * 100（target=0 の場合は 0）


class GoalSummaryResponse(BaseModel):
    """ダッシュボード固定エリア用：今月・今週の目標一覧"""
    monthly: list[GoalWithActual]
    weekly: list[GoalWithActual]
