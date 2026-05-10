from __future__ import annotations

"""
受注ごとの担当者別報酬（order_commissions）テーブル用 Pydantic スキーマ。

ADR-021 Phase 5 / Sprint 5: 担当者報酬計算 MVP
  1 受注 × 5 ロール（sales / order / ship / purchase / trouble）= 最大 5 行。
  UNIQUE (order_id, role) で UPSERT を可能にする。

各ロールの計算規則は services.commission_calculator.calculate を参照。
ロール別「キャンセル時 0 適用範囲」が異なる点が肝（営業/受注/発送のみキャンセル時 0、
仕入/トラブルはキャンセル判定なし）。

変更履歴:
  2026-05-11: 初版（ADR-021 Phase 5 / Sprint 5）
"""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.schemas.tenant_commission_settings import RoleLiteral


class OrderCommissionAssignmentRequest(BaseModel):
    """`POST /orders/{id}/commissions/assign` リクエスト。

    role と staff_id を 1 ペア指定して UPSERT する。
    staff_id=None で「担当解除（行は残し staff_id を NULL に戻す）」も可能。
    """
    role: RoleLiteral
    staff_id: int | None = Field(default=None, ge=1)


class OrderCommissionResponse(BaseModel):
    """1 ロール分の報酬レコードレスポンス。"""
    id: int
    order_id: int
    tenant_id: int
    role: str
    staff_id: int | None
    staff_name: str | None = None
    calculated_amount: Decimal
    calculated_at: datetime | None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class OrderCommissionsBundleResponse(BaseModel):
    """`GET /orders/{id}/commissions` のレスポンス。

    5 ロール分（未登録ロールは null）を一度に返す。フロント側で個別ロール
    へアクセスしやすいよう dict 形式で返す（Pydantic v2 が dict[str, ...] を
    そのままシリアライズする）。
    """
    order_id: int
    commissions: dict[str, OrderCommissionResponse | None]


class MonthlyByStaffItem(BaseModel):
    """月次集計の by_staff 1 件分。"""
    staff_id: int | None  # None は未割当（担当者解除済みの行）
    staff_name: str | None = None
    total: Decimal


class MonthlyByRoleItem(BaseModel):
    """月次集計の by_role 1 件分。"""
    role: str
    total: Decimal


class MonthlyCommissionSummaryResponse(BaseModel):
    """`GET /commissions/monthly?year=&month=` のレスポンス。

    AC-5.6: by_staff / by_role / total を返す。
    集計範囲は order_commissions.calculated_at が指定月内のレコードのみ。
    """
    year: int
    month: int
    by_staff: list[MonthlyByStaffItem]
    by_role: list[MonthlyByRoleItem]
    total: Decimal
