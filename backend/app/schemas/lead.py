from __future__ import annotations

"""
リード（leads）テーブル用Pydanticスキーマ。

変更履歴:
  2026-04-16: 初版作成（Phase 1）
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field, field_validator

from app.schemas.base import validate_phone, validate_email_loose


class LeadStatus(str, Enum):
    new = "新規"
    contacting = "コンタクト中"
    proposing = "提案中"
    converted = "案件化"
    lost = "失注"
    on_hold = "保留"


class LeadType(str, Enum):
    inbound = "Inbound"
    outbound = "Outbound"


class LeadTemperature(str, Enum):
    hot = "Hot"
    warm = "Warm"
    cold = "Cold"


class LeadScale(str, Enum):
    small = "Small"
    medium = "Medium"
    large = "Large"


class LeadCustomerType(str, Enum):
    trust = "信頼重視"
    price = "価格重視"


class LeadResponseSpeed(str, Enum):
    within_24h = "24h以内"
    within_3d = "3日以内"
    over_3d = "3日超"


class LeadCreate(BaseModel):
    """リード登録リクエスト"""
    customer_name: str = Field(min_length=1, max_length=255)
    company_name: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    source: str | None = Field(default=None, max_length=50)
    type: LeadType | None = None
    status: LeadStatus = Field(default=LeadStatus.new)
    temperature: LeadTemperature | None = None
    estimated_scale: LeadScale | None = None
    customer_type: LeadCustomerType | None = None
    response_speed: LeadResponseSpeed | None = None
    monthly_forecast: Decimal | None = Field(default=None, ge=0, max_digits=15, decimal_places=2)
    assigned_to: int | None = Field(default=None, ge=1)
    notes: str | None = Field(default=None, max_length=5000)

    @field_validator("email")
    @classmethod
    def check_email(cls, v: str | None) -> str | None:
        return validate_email_loose(v)

    @field_validator("phone")
    @classmethod
    def check_phone(cls, v: str | None) -> str | None:
        return validate_phone(v)


class LeadUpdate(BaseModel):
    """リード更新リクエスト（部分更新）"""
    customer_name: str | None = Field(default=None, min_length=1, max_length=255)
    company_name: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    source: str | None = Field(default=None, max_length=50)
    type: LeadType | None = None
    status: LeadStatus | None = None
    temperature: LeadTemperature | None = None
    estimated_scale: LeadScale | None = None
    customer_type: LeadCustomerType | None = None
    response_speed: LeadResponseSpeed | None = None
    monthly_forecast: Decimal | None = Field(default=None, ge=0, max_digits=15, decimal_places=2)
    assigned_to: int | None = Field(default=None, ge=1)
    notes: str | None = Field(default=None, max_length=5000)

    @field_validator("email")
    @classmethod
    def check_email(cls, v: str | None) -> str | None:
        return validate_email_loose(v)

    @field_validator("phone")
    @classmethod
    def check_phone(cls, v: str | None) -> str | None:
        return validate_phone(v)


class LeadResponse(BaseModel):
    """リード情報レスポンス"""
    id: int
    lead_code: str | None
    customer_name: str
    company_name: str | None
    email: str | None
    phone: str | None
    source: str | None
    type: str | None
    status: str
    temperature: str | None
    estimated_scale: str | None
    customer_type: str | None
    response_speed: str | None
    monthly_forecast: Decimal | None
    prospect_rank: str | None
    assigned_to: int | None
    converted_deal_id: int | None
    notes: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class LeadConvertRequest(BaseModel):
    """リード→案件変換リクエスト"""
    customer_id: int = Field(ge=1, description="既存顧客ID（必須）")
    title: str = Field(min_length=1, max_length=255, description="案件タイトル")
    amount: Decimal | None = Field(default=None, ge=0, max_digits=15, decimal_places=2)
    assigned_to: int | None = Field(default=None, ge=1, description="担当者（省略時はリードの担当者を引き継ぐ）")
    notes: str | None = Field(default=None, max_length=5000)
