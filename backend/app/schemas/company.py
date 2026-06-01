from __future__ import annotations

"""
会社（companies）テーブル用 Pydantic スキーマ。Phase 1-B-2 Step 5b-1 で新設。

本体 companies:
  id, tenant_id, company_code, lead_id, sales_rep_id,
  name, name_en, normalized_name, industry, website,
  trust_level, priority_focus, per_order_amount, monthly_frequency,
  monthly_forecast / monthly_forecast_source / monthly_forecast_updated_at,
  billing_display_name, payment_recipient_name, fedex_account, shipping_note,
  status, notes, created_at, updated_at

副テーブル（別スキーマで表現）:
  company_addresses   - 複数拠点対応（branch_name）
  company_sales_channels - 販売チャネル

関連テーブル contacts は schemas/contact.py に別途定義。

注: is_individual カラムは Phase 1-B-2 Step 5a で削除済（個人/法人区別撤廃）。
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field, field_validator

from app.schemas.base import validate_email_loose, validate_phone


class CompanyStatus(str, Enum):
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


# ========== 副テーブル ==========


class CompanyAddressInput(BaseModel):
    """会社住所のリクエスト。branch_name + address_type で複数拠点対応"""
    address_type: AddressType
    branch_name: str | None = Field(default=None, max_length=100, description="支店・拠点名")
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
    is_default: bool = Field(default=False, description="会社内で当該 address_type のデフォルトかどうか")

    @field_validator("email")
    @classmethod
    def _check_email(cls, v: str | None) -> str | None:
        return validate_email_loose(v)

    @field_validator("telephone")
    @classmethod
    def _check_phone(cls, v: str | None) -> str | None:
        return validate_phone(v)


class CompanyAddressResponse(CompanyAddressInput):
    id: int
    model_config = {"from_attributes": True}


class CompanyDiscordInput(BaseModel):
    """Discord webhook 設定（company_discord 副テーブル）。"""
    is_joined: bool = False
    channel_id: str | None = Field(default=None, max_length=50)
    user_id: str | None = Field(default=None, max_length=50)
    invoice_webhook: str | None = None
    shipment_webhook: str | None = None


class CompanyDiscordResponse(CompanyDiscordInput):
    company_id: int
    model_config = {"from_attributes": True}


# ========== 本体 ==========


class CompanyCreate(BaseModel):
    company_code: str | None = Field(
        default=None, max_length=20,
        description="CO-00001 形式。未指定ならサーバー側で自動採番",
    )
    lead_id: int | None = Field(default=None, description="出自リード（任意）")
    sales_rep_id: int | None = Field(default=None, description="担当スタッフ id")
    name: str = Field(min_length=1, max_length=255)
    name_en: str | None = Field(default=None, max_length=255)
    normalized_name: str | None = Field(default=None, max_length=255)
    industry: str | None = Field(default=None, max_length=100)
    website: str | None = Field(default=None, max_length=255)
    trust_level: int | None = Field(default=None, ge=1, le=5)
    priority_focus: str | None = Field(default=None, max_length=50)
    per_order_amount: Decimal | None = None
    monthly_frequency: int | None = Field(default=None, ge=0)
    monthly_forecast: Decimal | None = None
    monthly_forecast_source: MonthlyForecastSource | None = None
    billing_display_name: str | None = Field(default=None, max_length=255)
    payment_recipient_name: str | None = Field(default=None, max_length=255)
    fedex_account: str | None = Field(default=None, max_length=100)
    shipping_note: str | None = None
    status: CompanyStatus = CompanyStatus.active
    notes: str | None = None
    # 副テーブル（ネスト、任意）
    addresses: list[CompanyAddressInput] = Field(default_factory=list)
    sales_channels: list[str] = Field(default_factory=list)


class CompanyUpdate(BaseModel):
    lead_id: int | None = None
    sales_rep_id: int | None = None
    name: str | None = Field(default=None, min_length=1, max_length=255)
    name_en: str | None = Field(default=None, max_length=255)
    normalized_name: str | None = Field(default=None, max_length=255)
    industry: str | None = Field(default=None, max_length=100)
    website: str | None = Field(default=None, max_length=255)
    trust_level: int | None = Field(default=None, ge=1, le=5)
    priority_focus: str | None = Field(default=None, max_length=50)
    per_order_amount: Decimal | None = None
    monthly_frequency: int | None = Field(default=None, ge=0)
    monthly_forecast: Decimal | None = None
    monthly_forecast_source: MonthlyForecastSource | None = None
    billing_display_name: str | None = Field(default=None, max_length=255)
    payment_recipient_name: str | None = Field(default=None, max_length=255)
    fedex_account: str | None = Field(default=None, max_length=100)
    shipping_note: str | None = None
    status: CompanyStatus | None = None
    notes: str | None = None
    # 副テーブル更新。None=触らない、[]=空に置換
    addresses: list[CompanyAddressInput] | None = None
    sales_channels: list[str] | None = None
    # Discord webhook。None=触らない（省略時）、null=行削除、object=upsert
    discord: CompanyDiscordInput | None = None


class CompanyResponse(BaseModel):
    id: int
    tenant_id: int
    company_code: str
    lead_id: int | None
    sales_rep_id: int | None
    name: str
    name_en: str | None
    normalized_name: str | None
    industry: str | None
    website: str | None
    trust_level: int | None
    priority_focus: str | None
    per_order_amount: Decimal | None
    monthly_frequency: int | None
    monthly_forecast: Decimal | None
    monthly_forecast_source: str | None
    monthly_forecast_updated_at: datetime | None
    billing_display_name: str | None
    payment_recipient_name: str | None
    fedex_account: str | None
    shipping_note: str | None
    status: str
    notes: str | None
    addresses: list[CompanyAddressResponse] = Field(default_factory=list)
    sales_channels: list[str] = Field(default_factory=list)
    discord: CompanyDiscordResponse | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ========== 重複マージ（A-4: PR #145 + #152 follow-up） ==========


class CompanyMergeRequest(BaseModel):
    """会社の重複マージリクエスト本体。

    `master_id` / `merge_id` は URL / query で指定するため body には含めない。
    `reason` は監査ログ (audit_logs) に残す任意のテキスト（運用者の判断根拠を後から追える）。
    """
    reason: str | None = Field(
        default=None,
        max_length=500,
        description="マージ判断の根拠（任意）。audit_logs.new_data._merge.reason に記録される",
    )
