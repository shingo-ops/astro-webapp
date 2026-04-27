from __future__ import annotations

"""
注文（orders）テーブル用Pydanticスキーマ。

変更履歴:
  2026-04-17: Phase 2拡張（配送情報、ステータス拡張、invoice_id追加）
  2026-04-27: Phase 1-B-2 Step 5d — 旧 customer_id を撤去し、
    company_id / contact_id を必須化（新 B2B モデル唯一の正）
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field


class OrderStatus(str, Enum):
    pending = "pending"
    confirmed = "confirmed"
    processing = "processing"
    shipped = "shipped"
    delivered = "delivered"
    returned = "returned"
    cancelled = "cancelled"


class OrderCreate(BaseModel):
    """注文登録リクエスト（Step 5d 以降は company_id + contact_id 必須）"""
    company_id: int = Field(ge=1, description="会社ID")
    contact_id: int = Field(ge=1, description="担当者ID")
    deal_id: int | None = Field(default=None, ge=1)
    invoice_id: int | None = Field(default=None, ge=1)
    order_number: str = Field(min_length=1, max_length=100)
    total_amount: Decimal | None = Field(default=None, ge=0, max_digits=15, decimal_places=2)
    currency: str = Field(default="JPY", max_length=10)
    status: OrderStatus = Field(default=OrderStatus.pending)
    shipping_carrier: str | None = Field(default=None, max_length=50)
    shipping_fee: Decimal | None = Field(default=None, ge=0, max_digits=15, decimal_places=2)
    shipping_country: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=5000)


class OrderUpdate(BaseModel):
    # 注意: company_id / contact_id / deal_id / invoice_id は
    # 作成後の変更を禁止（FK 整合性保護ポリシー）。router の _UPDATABLE_COLUMNS にも含まない。
    # schema にも出さないことで API コントラクトと router 挙動を一致させる。
    deal_id: int | None = Field(default=None, ge=1)
    invoice_id: int | None = Field(default=None, ge=1)
    order_number: str | None = Field(default=None, min_length=1, max_length=100)
    total_amount: Decimal | None = Field(default=None, ge=0, max_digits=15, decimal_places=2)
    currency: str | None = Field(default=None, max_length=10)
    status: OrderStatus | None = None
    shipping_carrier: str | None = Field(default=None, max_length=50)
    shipping_fee: Decimal | None = Field(default=None, ge=0, max_digits=15, decimal_places=2)
    tracking_number: str | None = Field(default=None, max_length=200)
    shipping_country: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=5000)


class OrderResponse(BaseModel):
    """注文情報レスポンス。

    Note: `contact_id` は Step 5d 以降必須にする方針だが、PR α merge 直後は
    legacy 行が DB に残るため Optional のまま。PR γ (resolver 撤去) と同
    タイミングで `contact_id: int` 必須に昇格する。
    """
    id: int
    company_id: int
    contact_id: int | None = None  # PR γ で `int` 必須化予定
    deal_id: int | None
    invoice_id: int | None
    order_number: str
    total_amount: Decimal | None
    currency: str | None
    status: str
    shipping_carrier: str | None
    shipping_fee: Decimal | None
    tracking_number: str | None
    shipped_at: datetime | None
    delivered_at: datetime | None
    shipping_country: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
