from __future__ import annotations

"""
顧客（customers）テーブル用Pydanticスキーマ。

Phase 1 再設計（2026-04-23）で以下の正規化を実施:
  本体 customers:
    id, tenant_id, customer_code, lead_id, sales_rep_id, company_name,
    trust_level, priority_focus, per_order_amount, monthly_frequency,
    monthly_forecast / monthly_forecast_source / monthly_forecast_updated_at,
    meeting_requested, billing_display_name, payment_recipient_name,
    fedex_account, shipping_note, primary_contact_channel, status,
    created_at, updated_at
  副テーブル customer_addresses: 請求先/配送先の住所（1顧客に複数行）
  副テーブル customer_sales_channels: 販売チャネル（複数持てる中間テーブル）
  副テーブル customer_discord: Discord連携情報（任意の1対1）

変更履歴:
  2026-04-16: Phase 1拡張（請求先/配送先/ステータス/business_id等を追加）
  2026-04-23: Phase 1 再設計（副テーブル分離、billing_/delivery_ フラット列を廃止）
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.base import validate_phone, validate_email_loose


class CustomerStatus(str, Enum):
    active = "active"
    inactive = "inactive"
    archived = "archived"
    pending_dedup_review = "pending_dedup_review"


class MonthlyForecastSource(str, Enum):
    manual = "manual"
    ai_analysis = "ai_analysis"


class AddressType(str, Enum):
    billing = "billing"
    delivery = "delivery"


# ========== 副テーブル用スキーマ ==========


class CustomerAddressInput(BaseModel):
    """住所のリクエスト（create / update 時のネスト）"""
    address_type: AddressType
    name: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=255)
    telephone: str | None = Field(default=None, max_length=50)
    tax_id: str | None = Field(default=None, max_length=100)
    address_line_1: str | None = Field(default=None, max_length=255)
    address_line_2: str | None = Field(default=None, max_length=255)
    address_line_3: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, max_length=100)
    state: str | None = Field(default=None, max_length=100)
    zip: str | None = Field(default=None, max_length=50)
    country_code: str | None = Field(default=None, min_length=2, max_length=2, description="ISO 3166-1 alpha-2")

    @field_validator("email")
    @classmethod
    def _check_email(cls, v: str | None) -> str | None:
        return validate_email_loose(v)

    @field_validator("telephone")
    @classmethod
    def _check_phone(cls, v: str | None) -> str | None:
        return validate_phone(v)


class CustomerAddressResponse(CustomerAddressInput):
    """住所のレスポンス（id 付き）"""
    id: int

    model_config = {"from_attributes": True}


class CustomerDiscordInput(BaseModel):
    """Discord 連携情報のリクエスト"""
    is_joined: bool = False
    channel_id: str | None = Field(default=None, max_length=50)
    user_id: str | None = Field(default=None, max_length=50)
    invoice_webhook: str | None = None
    shipment_webhook: str | None = None


class CustomerDiscordResponse(CustomerDiscordInput):
    """Discord 連携情報のレスポンス"""
    model_config = {"from_attributes": True}


# ========== 本体 ==========


class CustomerCreate(BaseModel):
    """顧客登録リクエスト（ネスト構造）"""
    customer_code: str | None = Field(
        default=None, max_length=20,
        description="CT-00001 形式。未指定ならサーバー側で自動採番",
    )
    lead_id: int | None = Field(default=None, description="出自リード（任意）")
    sales_rep_id: int | None = Field(default=None, description="担当スタッフ id")
    company_name: str | None = Field(default=None, max_length=255)
    trust_level: int | None = Field(default=None, ge=1, le=5)
    priority_focus: str | None = Field(default=None, max_length=50)
    per_order_amount: Decimal | None = None
    monthly_frequency: int | None = Field(default=None, ge=0)
    monthly_forecast: Decimal | None = None
    monthly_forecast_source: MonthlyForecastSource | None = None
    meeting_requested: bool = False
    billing_display_name: str | None = Field(default=None, max_length=255)
    payment_recipient_name: str | None = Field(default=None, max_length=255)
    fedex_account: str | None = Field(default=None, max_length=100)
    shipping_note: str | None = None
    primary_contact_channel: str | None = Field(default=None, max_length=30)
    status: CustomerStatus = CustomerStatus.active
    # ネスト副テーブル（任意）
    addresses: list[CustomerAddressInput] = Field(default_factory=list)
    sales_channels: list[str] = Field(default_factory=list)
    discord: CustomerDiscordInput | None = None


class CustomerUpdate(BaseModel):
    """顧客更新リクエスト（部分更新）"""
    lead_id: int | None = None
    sales_rep_id: int | None = None
    company_name: str | None = Field(default=None, max_length=255)
    trust_level: int | None = Field(default=None, ge=1, le=5)
    priority_focus: str | None = Field(default=None, max_length=50)
    per_order_amount: Decimal | None = None
    monthly_frequency: int | None = Field(default=None, ge=0)
    monthly_forecast: Decimal | None = None
    monthly_forecast_source: MonthlyForecastSource | None = None
    meeting_requested: bool | None = None
    billing_display_name: str | None = Field(default=None, max_length=255)
    payment_recipient_name: str | None = Field(default=None, max_length=255)
    fedex_account: str | None = Field(default=None, max_length=100)
    shipping_note: str | None = None
    primary_contact_channel: str | None = Field(default=None, max_length=30)
    status: CustomerStatus | None = None
    # ネスト副テーブル更新。None=触らない、[]=空に置換
    addresses: list[CustomerAddressInput] | None = None
    sales_channels: list[str] | None = None
    discord: CustomerDiscordInput | None = None


class CustomerResponse(BaseModel):
    """顧客情報レスポンス（ネスト構造）"""
    id: int
    tenant_id: int
    customer_code: str
    lead_id: int | None
    sales_rep_id: int | None
    company_name: str | None
    trust_level: int | None
    priority_focus: str | None
    per_order_amount: Decimal | None
    monthly_frequency: int | None
    monthly_forecast: Decimal | None
    monthly_forecast_source: Literal["manual", "ai_analysis"] | None
    monthly_forecast_updated_at: datetime | None
    meeting_requested: bool
    billing_display_name: str | None
    payment_recipient_name: str | None
    fedex_account: str | None
    shipping_note: str | None
    primary_contact_channel: str | None
    status: str
    addresses: list[CustomerAddressResponse] = Field(default_factory=list)
    sales_channels: list[str] = Field(default_factory=list)
    discord: CustomerDiscordResponse | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
