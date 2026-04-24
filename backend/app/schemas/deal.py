from __future__ import annotations

"""
商談（deals）テーブル用Pydanticスキーマ。

テナントスキーマの deals テーブル定義（Phase 1拡張版）:
  id, tenant_id, deal_code, customer_id, lead_id, title, amount,
  currency, status, stage, probability, lost_reason, assigned_to,
  expected_close_date, notes, created_at, updated_at

変更履歴:
  2026-04-16: Phase 1拡張（deal_code, lead_id, assigned_to, stage,
    probability, lost_reason, currency を追加）
"""

from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field


class DealStatus(str, Enum):
    """商談ステータスの定義値"""
    open = "open"
    won = "won"
    lost = "lost"
    negotiating = "negotiating"
    on_hold = "on_hold"


class DealStage(str, Enum):
    """商談ステージ（進捗段階）"""
    open = "open"
    negotiating = "negotiating"
    proposal = "proposal"
    won = "won"
    lost = "lost"
    on_hold = "on_hold"


class Currency(str, Enum):
    JPY = "JPY"
    USD = "USD"
    EUR = "EUR"


class DealCreate(BaseModel):
    """商談登録リクエスト"""
    customer_id: int = Field(ge=1, description="顧客ID（旧モデル、Step 5d まで必須）")
    # Phase 1-B-2 Step 5b-2: 新 B2B モデル（company + contact）の移行フィールド
    # 互換性のため当面 optional。frontend は Step 5c で移行する
    company_id: int | None = Field(default=None, ge=1, description="会社ID（新モデル）")
    contact_id: int | None = Field(default=None, ge=1, description="担当者ID（新モデル）")
    lead_id: int | None = Field(default=None, ge=1, description="変換元リードID")
    title: str = Field(min_length=1, max_length=255, description="商談タイトル")
    amount: Decimal | None = Field(default=None, ge=0, max_digits=15, decimal_places=2, description="金額")
    currency: Currency = Field(default=Currency.JPY, description="通貨")
    status: DealStatus = Field(default=DealStatus.open, description="ステータス")
    stage: DealStage = Field(default=DealStage.open, description="ステージ")
    probability: int | None = Field(default=None, ge=0, le=100, description="成約確率(%)")
    lost_reason: str | None = Field(default=None, max_length=255)
    assigned_to: int | None = Field(default=None, ge=1, description="担当者ユーザーID")
    expected_close_date: date | None = Field(default=None, description="成約予定日")
    notes: str | None = Field(default=None, max_length=5000, description="備考")


class DealUpdate(BaseModel):
    """商談更新リクエスト（部分更新）"""
    customer_id: int | None = Field(default=None, ge=1)
    # Phase 1-B-2 Step 5b-2: 新 B2B モデル
    company_id: int | None = Field(default=None, ge=1)
    contact_id: int | None = Field(default=None, ge=1)
    lead_id: int | None = Field(default=None, ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=255)
    amount: Decimal | None = Field(default=None, ge=0, max_digits=15, decimal_places=2)
    currency: Currency | None = None
    status: DealStatus | None = None
    stage: DealStage | None = None
    probability: int | None = Field(default=None, ge=0, le=100)
    lost_reason: str | None = Field(default=None, max_length=255)
    assigned_to: int | None = Field(default=None, ge=1)
    expected_close_date: date | None = None
    notes: str | None = Field(default=None, max_length=5000)


class DealResponse(BaseModel):
    """商談情報レスポンス"""
    id: int
    deal_code: str | None
    customer_id: int | None
    # Phase 1-B-2 Step 5b-2: 新 B2B モデル
    company_id: int | None = None
    contact_id: int | None = None
    lead_id: int | None
    title: str
    amount: Decimal | None
    currency: str | None
    status: str
    stage: str | None
    probability: int | None
    lost_reason: str | None
    assigned_to: int | None
    expected_close_date: date | None
    notes: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
