from __future__ import annotations

"""
配送ゾーン・配送料金用Pydanticスキーマ。

変更履歴:
  2026-04-17: 初版作成（Phase 2）
"""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class ShippingZoneCreate(BaseModel):
    country_code: str = Field(min_length=2, max_length=3)
    country_name: str = Field(min_length=1, max_length=100)
    carrier: str = Field(min_length=1, max_length=50)
    zone: str = Field(min_length=1, max_length=20)


class ShippingZoneResponse(BaseModel):
    id: int
    country_code: str
    country_name: str
    carrier: str
    zone: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ShippingRateCreate(BaseModel):
    carrier: str = Field(min_length=1, max_length=50)
    zone: str = Field(min_length=1, max_length=20)
    weight_min: Decimal = Field(ge=0, max_digits=10, decimal_places=3)
    weight_max: Decimal = Field(gt=0, max_digits=10, decimal_places=3)
    price: Decimal = Field(ge=0, max_digits=15, decimal_places=2)
    currency: str = Field(default="JPY", max_length=10)


class ShippingRateResponse(BaseModel):
    id: int
    carrier: str
    zone: str
    weight_min: Decimal
    weight_max: Decimal
    price: Decimal
    currency: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ShippingCalcRequest(BaseModel):
    country_code: str = Field(min_length=2, max_length=3)
    weight_kg: Decimal = Field(gt=0, max_digits=10, decimal_places=3)
    carrier: str | None = Field(default=None, max_length=50)


class ShippingCalcResult(BaseModel):
    carrier: str
    zone: str
    fee: Decimal
    currency: str


class ShippingCalcResponse(BaseModel):
    results: list[ShippingCalcResult]
    cheapest: ShippingCalcResult | None
