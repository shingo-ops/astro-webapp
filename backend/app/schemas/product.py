from __future__ import annotations

"""
商品（products）テーブル用Pydanticスキーマ。

変更履歴:
  2026-04-17: 初版作成（Phase 2）
"""

from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field


class ProductStatus(str, Enum):
    active = "active"
    discontinued = "discontinued"


class ProductCreate(BaseModel):
    name_ja: str = Field(min_length=1, max_length=255)
    name_en: str | None = Field(default=None, max_length=255)
    category: str | None = Field(default=None, max_length=100)
    mark: str | None = Field(default=None, max_length=100)
    status: ProductStatus = Field(default=ProductStatus.active)
    condition: str | None = Field(default=None, max_length=50)
    unit_price: Decimal | None = Field(default=None, ge=0, max_digits=15, decimal_places=2)
    quantity: int = Field(default=0, ge=0)
    weight: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=3)
    notes: str | None = Field(default=None, max_length=5000)
    release_date: date | None = None


class ProductUpdate(BaseModel):
    name_ja: str | None = Field(default=None, min_length=1, max_length=255)
    name_en: str | None = Field(default=None, max_length=255)
    category: str | None = Field(default=None, max_length=100)
    mark: str | None = Field(default=None, max_length=100)
    status: ProductStatus | None = None
    condition: str | None = Field(default=None, max_length=50)
    unit_price: Decimal | None = Field(default=None, ge=0, max_digits=15, decimal_places=2)
    quantity: int | None = Field(default=None, ge=0)
    weight: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=3)
    notes: str | None = Field(default=None, max_length=5000)
    release_date: date | None = None


class ProductResponse(BaseModel):
    id: int
    product_code: str | None
    name_ja: str
    name_en: str | None
    category: str | None
    mark: str | None
    status: str
    condition: str | None
    unit_price: Decimal | None
    quantity: int
    weight: Decimal | None
    notes: str | None
    release_date: date | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class InventoryCheckResponse(BaseModel):
    product_id: int
    product_name: str
    available: bool
    current_quantity: int
    requested_quantity: int
