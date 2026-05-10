from __future__ import annotations

"""
テナント別の報酬計算設定（tenant_commission_settings）テーブル用 Pydantic スキーマ。

ADR-021 Phase 5 / Sprint 5: 担当者報酬計算 MVP
  1 テナント = 1 行（tenant_id UNIQUE）。OrderFlow Manager の現行 5 ロール
  （sales / order / ship / purchase / trouble）の報酬計算式を 1 つの JSONB
  に集約してテナント別にカスタマイズできるようにする。

ロール別計算タイプ:
  - rate: commission_base_amount × value（営業・受注に該当、デフォルト 10%）
  - fixed: value 固定（発送 200 円・仕入 100 円・トラブル 500 円）

変更履歴:
  2026-05-11: 初版（ADR-021 Phase 5 / Sprint 5）
"""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


# 5 ロールの識別子（DB CHECK 制約と一致させること）
RoleLiteral = Literal["sales", "order", "ship", "purchase", "trouble"]
ALL_ROLES: tuple[str, ...] = ("sales", "order", "ship", "purchase", "trouble")

# rate (売上ベースの率) / fixed (固定額) の 2 種類
RateTypeLiteral = Literal["rate", "fixed"]


class CommissionRate(BaseModel):
    """1 ロール分の rate 設定。

    type=rate のとき value は売上に対する率（0.10 = 10%）。
    type=fixed のとき value は円単位の固定額（200, 100, 500 など）。
    JSONB に保存する都合で Decimal を float としてシリアライズしやすい
    値域に収める前提（テナント側がカスタマイズしても合計値が overflow しないこと）。
    """
    type: RateTypeLiteral
    value: Decimal = Field(ge=0, max_digits=14, decimal_places=4)


class CommissionRatesConfig(BaseModel):
    """5 ロール分の rate 設定。順序は OrderFlow 表示と揃える。"""
    sales: CommissionRate
    order: CommissionRate
    ship: CommissionRate
    purchase: CommissionRate
    trouble: CommissionRate


# 既定の rate 設定（OrderFlow 現行式に揃える）
DEFAULT_COMMISSION_RATES: CommissionRatesConfig = CommissionRatesConfig(
    sales=CommissionRate(type="rate", value=Decimal("0.10")),
    order=CommissionRate(type="rate", value=Decimal("0.10")),
    ship=CommissionRate(type="fixed", value=Decimal("200")),
    purchase=CommissionRate(type="fixed", value=Decimal("100")),
    trouble=CommissionRate(type="fixed", value=Decimal("500")),
)


class TenantCommissionSettingsResponse(BaseModel):
    """テナント別 rate 設定の取得レスポンス。"""
    id: int
    tenant_id: int
    commission_rates: CommissionRatesConfig
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TenantCommissionSettingsUpdate(BaseModel):
    """PATCH 用ボディ。commission_rates のみ更新可能。"""
    commission_rates: CommissionRatesConfig
