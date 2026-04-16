from __future__ import annotations

"""
顧客（customers）テーブル用Pydanticスキーマ。

テナントスキーマの customers テーブル定義（Phase 1拡張版）:
  id, tenant_id, customer_code, name, email, phone, company,
  registration_source, status,
  billing_name/phone/email/address,
  delivery_name/phone/email/address/country,
  business_id, transaction_count, last_transaction_date,
  notes, created_at, updated_at

変更履歴:
  2026-04-16: Phase 1拡張（請求先/配送先/ステータス/business_id等を追加）
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, field_validator

from app.schemas.base import validate_phone, validate_email_loose


class CustomerStatus(str, Enum):
    active = "active"
    inactive = "inactive"


class CustomerCreate(BaseModel):
    """顧客登録リクエスト"""
    name: str = Field(min_length=1, max_length=255, description="顧客名")
    email: str | None = Field(default=None, max_length=255, description="メールアドレス")
    phone: str | None = Field(default=None, max_length=50, description="電話番号")
    company: str | None = Field(default=None, max_length=255, description="会社名")
    registration_source: str | None = Field(default=None, max_length=50, description="登録元")
    status: CustomerStatus = Field(default=CustomerStatus.active, description="ステータス")
    billing_name: str | None = Field(default=None, max_length=255)
    billing_phone: str | None = Field(default=None, max_length=50)
    billing_email: str | None = Field(default=None, max_length=255)
    billing_address: str | None = Field(default=None, max_length=5000)
    delivery_name: str | None = Field(default=None, max_length=255)
    delivery_phone: str | None = Field(default=None, max_length=50)
    delivery_email: str | None = Field(default=None, max_length=255)
    delivery_address: str | None = Field(default=None, max_length=5000)
    delivery_country: str | None = Field(default=None, max_length=100)
    business_id: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=5000, description="備考")

    @field_validator("email", "billing_email", "delivery_email")
    @classmethod
    def check_email(cls, v: str | None) -> str | None:
        return validate_email_loose(v)

    @field_validator("phone", "billing_phone", "delivery_phone")
    @classmethod
    def check_phone(cls, v: str | None) -> str | None:
        return validate_phone(v)


class CustomerUpdate(BaseModel):
    """顧客更新リクエスト（部分更新: 指定したフィールドのみ更新）"""
    name: str | None = Field(default=None, min_length=1, max_length=255)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    company: str | None = Field(default=None, max_length=255)
    registration_source: str | None = Field(default=None, max_length=50)
    status: CustomerStatus | None = None
    billing_name: str | None = Field(default=None, max_length=255)
    billing_phone: str | None = Field(default=None, max_length=50)
    billing_email: str | None = Field(default=None, max_length=255)
    billing_address: str | None = Field(default=None, max_length=5000)
    delivery_name: str | None = Field(default=None, max_length=255)
    delivery_phone: str | None = Field(default=None, max_length=50)
    delivery_email: str | None = Field(default=None, max_length=255)
    delivery_address: str | None = Field(default=None, max_length=5000)
    delivery_country: str | None = Field(default=None, max_length=100)
    business_id: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=5000)

    @field_validator("email", "billing_email", "delivery_email")
    @classmethod
    def check_email(cls, v: str | None) -> str | None:
        return validate_email_loose(v)

    @field_validator("phone", "billing_phone", "delivery_phone")
    @classmethod
    def check_phone(cls, v: str | None) -> str | None:
        return validate_phone(v)


class CustomerResponse(BaseModel):
    """顧客情報レスポンス"""
    id: int
    customer_code: str | None
    name: str
    email: str | None
    phone: str | None
    company: str | None
    registration_source: str | None
    status: str | None
    billing_name: str | None
    billing_phone: str | None
    billing_email: str | None
    billing_address: str | None
    delivery_name: str | None
    delivery_phone: str | None
    delivery_email: str | None
    delivery_address: str | None
    delivery_country: str | None
    business_id: str | None
    transaction_count: int | None
    last_transaction_date: datetime | None
    notes: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
