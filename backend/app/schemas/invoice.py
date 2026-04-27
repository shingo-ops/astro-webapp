from __future__ import annotations

"""
請求書（invoices / invoice_items）用Pydanticスキーマ。

変更履歴:
  2026-04-17: 初版作成（Phase 2）
  2026-04-27: Phase 1-B-2 Step 5d — 旧 customer_id を撤去し、
    company_id / contact_id を必須化（新 B2B モデル唯一の正）
"""

from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field


class InvoiceStatus(str, Enum):
    draft = "draft"
    issued = "issued"
    paid = "paid"
    overdue = "overdue"
    voided = "voided"


class InvoiceItemInput(BaseModel):
    product_id: int | None = Field(default=None, ge=1)
    product_name: str = Field(min_length=1, max_length=255)
    quantity: int = Field(ge=1)
    unit_price: Decimal = Field(ge=0, max_digits=15, decimal_places=2)
    weight: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=3)


class InvoiceCreate(BaseModel):
    """請求書登録リクエスト（Step 5d 以降は company_id + contact_id 必須）"""
    company_id: int = Field(ge=1, description="会社ID")
    contact_id: int = Field(ge=1, description="担当者ID")
    currency: str = Field(default="JPY", max_length=10)
    shipping_fee: Decimal | None = Field(default=None, ge=0, max_digits=15, decimal_places=2)
    tax_amount: Decimal | None = Field(default=None, ge=0, max_digits=15, decimal_places=2)
    exchange_rate_jpy: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=4)
    exchange_rate_usd: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=4)
    payment_method: str | None = Field(default=None, max_length=50)
    due_date: date | None = None
    notes: str | None = Field(default=None, max_length=5000)
    items: list[InvoiceItemInput] = Field(min_length=1)


class InvoiceUpdate(BaseModel):
    payment_method: str | None = Field(default=None, max_length=50)
    due_date: date | None = None
    exchange_rate_jpy: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=4)
    exchange_rate_usd: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=4)
    notes: str | None = Field(default=None, max_length=5000)


class VoidRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class InvoiceItemResponse(BaseModel):
    id: int
    product_id: int | None
    product_name: str
    quantity: int
    unit_price: Decimal
    weight: Decimal | None
    subtotal: Decimal
    sort_order: int

    model_config = {"from_attributes": True}


class InvoiceResponse(BaseModel):
    """請求書情報レスポンス。

    Note: `contact_id` は Step 5d 以降必須にする方針だが、PR α merge 直後は
    legacy 行が DB に残るため Optional のまま。PR γ (resolver 撤去) と同
    タイミングで `contact_id: int` 必須に昇格する。
    """
    id: int
    invoice_number: str | None
    quote_id: int | None
    company_id: int
    contact_id: int | None = None  # PR γ で `int` 必須化予定
    currency: str
    subtotal: Decimal | None
    shipping_fee: Decimal | None
    tax_amount: Decimal | None
    total_amount: Decimal | None
    exchange_rate_jpy: Decimal | None
    exchange_rate_usd: Decimal | None
    amount_jpy: Decimal | None
    amount_usd: Decimal | None
    payment_method: str | None
    status: str
    branch_number: int | None
    pdf_url: str | None
    erp_key: str | None
    issued_at: datetime | None
    due_date: date | None
    paid_at: datetime | None
    voided_at: datetime | None
    void_reason: str | None
    notes: str | None
    created_by: int | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class InvoiceDetailResponse(InvoiceResponse):
    items: list[InvoiceItemResponse] = []
