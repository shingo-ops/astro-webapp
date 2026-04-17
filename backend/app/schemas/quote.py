from __future__ import annotations

"""
見積もり（quotes / quote_items）用Pydanticスキーマ。

変更履歴:
  2026-04-17: 初版作成（Phase 2）
"""

from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field


class QuoteStatus(str, Enum):
    draft = "draft"
    sent = "sent"
    approved = "approved"
    rejected = "rejected"
    expired = "expired"


class QuoteItemInput(BaseModel):
    product_id: int | None = Field(default=None, ge=1)
    product_name: str = Field(min_length=1, max_length=255)
    quantity: int = Field(ge=1)
    unit_price: Decimal = Field(ge=0, max_digits=15, decimal_places=2)
    weight: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=3)


class QuoteCreate(BaseModel):
    deal_id: int | None = Field(default=None, ge=1)
    customer_id: int = Field(ge=1)
    currency: str = Field(default="JPY", max_length=10)
    shipping_fee: Decimal | None = Field(default=None, ge=0, max_digits=15, decimal_places=2)
    tax_amount: Decimal | None = Field(default=None, ge=0, max_digits=15, decimal_places=2)
    shipping_country: str | None = Field(default=None, max_length=100)
    shipping_carrier: str | None = Field(default=None, max_length=50)
    delivery_info: str | None = Field(default=None, max_length=5000)
    notes: str | None = Field(default=None, max_length=5000)
    validity_days: int = Field(default=30, ge=1, le=365)
    items: list[QuoteItemInput] = Field(min_length=1)


class QuoteUpdate(BaseModel):
    currency: str | None = Field(default=None, max_length=10)
    shipping_fee: Decimal | None = Field(default=None, ge=0, max_digits=15, decimal_places=2)
    tax_amount: Decimal | None = Field(default=None, ge=0, max_digits=15, decimal_places=2)
    shipping_country: str | None = Field(default=None, max_length=100)
    shipping_carrier: str | None = Field(default=None, max_length=50)
    delivery_info: str | None = Field(default=None, max_length=5000)
    notes: str | None = Field(default=None, max_length=5000)


class QuoteItemResponse(BaseModel):
    id: int
    product_id: int | None
    product_name: str
    quantity: int
    unit_price: Decimal
    weight: Decimal | None
    subtotal: Decimal
    sort_order: int

    model_config = {"from_attributes": True}


class QuoteResponse(BaseModel):
    id: int
    quote_code: str | None
    deal_id: int | None
    customer_id: int
    currency: str
    subtotal: Decimal | None
    shipping_fee: Decimal | None
    tax_amount: Decimal | None
    total_amount: Decimal | None
    status: str
    validity_date: date | None
    shipping_country: str | None
    shipping_carrier: str | None
    delivery_info: str | None
    pdf_url: str | None
    notes: str | None
    created_by: int | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class QuoteDetailResponse(QuoteResponse):
    items: list[QuoteItemResponse] = []
