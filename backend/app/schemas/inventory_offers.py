"""Pydantic schemas for `/super-admin/inventory-offers/*` endpoints.

spec.md v1.3 F11 / AC11.5:
  - 中央 admin が public.inventory (仕入元現在オファー) を一覧 / 編集 / 追加 / 削除する
  - UNIQUE (supplier_id, product_id, condition) で 1 行に集約
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

InventoryStatus = Literal["in_stock", "out_of_stock", "reserved", "archived"]
InventorySource = Literal["manual", "discord_parsed", "csv_import", "f6_approved"]


class InventoryOfferBase(BaseModel):
    """共通フィールド (新規作成 / 更新で共有)。"""

    supplier_id: int = Field(..., gt=0)
    product_id: int = Field(..., gt=0)
    condition: str = Field(..., min_length=1, max_length=50)
    quantity: int = Field(..., ge=0)
    unit_price: int = Field(..., ge=0)
    status: InventoryStatus = "in_stock"
    notes_ja: str | None = Field(default=None, max_length=2000)
    notes_en: str | None = Field(default=None, max_length=2000)
    expires_at: datetime | None = None
    source: InventorySource = "manual"


class InventoryOfferCreate(InventoryOfferBase):
    """新規 INSERT 用。UNIQUE 衝突は 409 を返す。"""


class InventoryOfferUpdate(BaseModel):
    """PATCH 用。すべて任意。supplier_id / product_id / condition は変更不可
    (UNIQUE キー、変更したい場合は DELETE + INSERT)。"""

    quantity: int | None = Field(default=None, ge=0)
    unit_price: int | None = Field(default=None, ge=0)
    status: InventoryStatus | None = None
    notes_ja: str | None = Field(default=None, max_length=2000)
    notes_en: str | None = Field(default=None, max_length=2000)
    expires_at: datetime | None = None


class InventoryOfferResponse(InventoryOfferBase):
    """list / detail レスポンス。supplier_name / product 情報を join 結果として埋める。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    offered_at: datetime
    created_at: datetime
    updated_at: datetime

    # JOIN 結果 (admin UI 表示用、任意)
    supplier_name: str | None = None
    product_code: str | None = None
    product_name: str | None = None


class InventoryOfferListResponse(BaseModel):
    """ページング付き一覧。"""

    items: list[InventoryOfferResponse]
    total: int
    page: int
    per_page: int


__all__ = [
    "InventoryOfferBase",
    "InventoryOfferCreate",
    "InventoryOfferUpdate",
    "InventoryOfferResponse",
    "InventoryOfferListResponse",
    "InventoryStatus",
    "InventorySource",
]
