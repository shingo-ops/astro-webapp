from __future__ import annotations

"""
見積もり（quotes / quote_items）用Pydanticスキーマ。

変更履歴:
  2026-04-17: 初版作成（Phase 2）
  2026-04-27: Phase 1-B-2 Step 5d — 旧 customer_id を撤去し、
    company_id / contact_id を必須化（新 B2B モデル唯一の正）
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
    """見積登録リクエスト（Step 5d 以降は company_id + contact_id 必須）"""
    deal_id: int | None = Field(default=None, ge=1)
    company_id: int = Field(ge=1, description="会社ID")
    contact_id: int = Field(ge=1, description="担当者ID")
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
    """見積情報レスポンス。

    Note: PR γ (Step 5d) で `contact_id` を必須化したが、対象は tenant_004 のみ
    (migration 035 の precondition で 0 件保証)。後発作成テナント (例: tenant_006
    /tenant_review) には migration 035 が遡及適用されず、demo/seed で
    contact_id IS NULL の行が存在しうる。一覧/詳細レスポンスがそれで 500 に
    ならないよう `int | None` で許容する (作成リクエスト QuoteCreate は引き続き必須)。
    """
    id: int
    quote_code: str | None
    deal_id: int | None
    company_id: int
    contact_id: int | None
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
