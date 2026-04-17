from __future__ import annotations

"""
仕入注文（purchase_orders / purchase_order_items）用Pydanticスキーマ。

変更履歴:
  2026-04-17: 初版作成（Phase 3）
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field


class POStatus(str, Enum):
    draft = "draft"
    ordered = "ordered"
    received = "received"
    cancelled = "cancelled"


class POItemInput(BaseModel):
    product_id: int = Field(ge=1)
    quantity: int = Field(ge=1)
    unit_cost: Decimal = Field(ge=0, max_digits=15, decimal_places=2)


class POCreate(BaseModel):
    supplier_id: int = Field(ge=1)
    notes: str | None = Field(default=None, max_length=5000)
    items: list[POItemInput] = Field(min_length=1)


class POUpdate(BaseModel):
    notes: str | None = Field(default=None, max_length=5000)


class POItemResponse(BaseModel):
    id: int
    product_id: int
    quantity: int
    unit_cost: Decimal
    subtotal: Decimal
    sort_order: int

    model_config = {"from_attributes": True}


class POResponse(BaseModel):
    id: int
    po_number: str | None
    supplier_id: int
    status: str
    total_amount: Decimal | None
    ordered_at: datetime | None
    received_at: datetime | None
    notes: str | None
    created_by: int | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PODetailResponse(POResponse):
    items: list[POItemResponse] = []
