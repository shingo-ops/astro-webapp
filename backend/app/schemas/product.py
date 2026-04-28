from __future__ import annotations

"""
商品（products）テーブル用Pydanticスキーマ。

変更履歴:
  2026-04-17: 初版作成（Phase 2）
  2026-04-28: Phase 1-C M-MVP（Q4/Q5/Q9 確定）で 11 列追加
              - jan_code, card_number, expansion_code, rarity, language
              - unit_price_usd, unit_price_eur, image_url
              - is_archived, archived_at, supplier_default_id
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

    # Phase 1-C M-MVP（2026-04-28）
    jan_code: str | None = Field(default=None, max_length=20)
    card_number: str | None = Field(default=None, max_length=50)
    expansion_code: str | None = Field(default=None, max_length=20)
    rarity: str | None = Field(default=None, max_length=20)
    language: str | None = Field(default=None, max_length=10)
    unit_price_usd: Decimal | None = Field(default=None, ge=0, max_digits=15, decimal_places=2)
    unit_price_eur: Decimal | None = Field(default=None, ge=0, max_digits=15, decimal_places=2)
    image_url: str | None = Field(default=None, max_length=500)
    is_archived: bool = Field(default=False)
    supplier_default_id: int | None = None


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

    # Phase 1-C M-MVP（2026-04-28）
    jan_code: str | None = Field(default=None, max_length=20)
    card_number: str | None = Field(default=None, max_length=50)
    expansion_code: str | None = Field(default=None, max_length=20)
    rarity: str | None = Field(default=None, max_length=20)
    language: str | None = Field(default=None, max_length=10)
    unit_price_usd: Decimal | None = Field(default=None, ge=0, max_digits=15, decimal_places=2)
    unit_price_eur: Decimal | None = Field(default=None, ge=0, max_digits=15, decimal_places=2)
    image_url: str | None = Field(default=None, max_length=500)
    is_archived: bool | None = None
    supplier_default_id: int | None = None


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

    # Phase 1-C M-MVP（2026-04-28）
    jan_code: str | None = None
    card_number: str | None = None
    expansion_code: str | None = None
    rarity: str | None = None
    language: str | None = None
    unit_price_usd: Decimal | None = None
    unit_price_eur: Decimal | None = None
    image_url: str | None = None
    is_archived: bool = False
    archived_at: datetime | None = None
    supplier_default_id: int | None = None

    model_config = {"from_attributes": True}


class ProductArchiveResponse(BaseModel):
    """DELETE /products/{id} で FK 参照ありのときに返す情報。

    Q9（2026-04-28 確定）: 物理削除しない、409 + アーカイブ推奨で返す。
    """

    id: int
    name_ja: str
    is_archived: bool
    blocking_references: list[str]  # 例: ["quote_items", "purchase_order_items"]
    detail: str = "下流参照があるため物理削除できません。is_archived=true でアーカイブしてください"


class InventoryCheckResponse(BaseModel):
    product_id: int
    product_name: str
    available: bool
    current_quantity: int
    requested_quantity: int
