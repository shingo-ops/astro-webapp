from __future__ import annotations

"""
注文（orders）テーブル用Pydanticスキーマ。

変更履歴:
  2026-04-17: Phase 2拡張（配送情報、ステータス拡張、invoice_id追加）
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
    customer_id: int = Field(ge=1)
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
    customer_id: int | None = Field(default=None, ge=1)
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
    id: int
    customer_id: int
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
