from __future__ import annotations

"""
担当者（contacts）テーブル用 Pydantic スキーマ。Phase 1-B-2 Step 5b-1 で新設。

本体 contacts:
  id, tenant_id, company_id, contact_code, lead_id,
  surname, given_name, display_name, job_title, department,
  is_primary_contact, primary_email, primary_phone,
  status, notes, created_at, updated_at

副テーブル:
  contact_emails            - 追加メール
  contact_discord           - Discord 連携（1対1 任意）
  contact_contact_channels  - 連絡ツール（多対多、Phase 1-B-1 踏襲）
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, field_validator

from app.schemas.base import validate_email_loose, validate_phone


class ContactStatus(str, Enum):
    active = "active"
    inactive = "inactive"
    archived = "archived"
    # PR #145 Q2 / PR #163: contacts.status の CHECK 制約は当初 3 値
    # ('active','inactive','archived') のみだったが、PR #163 で companies と揃えて
    # pending_dedup_review を Pydantic enum として正式に許容するとともに、
    # migration 037 で DB 側の CHECK 制約にも 'pending_dedup_review' を追加した。
    # これにより、重複候補として暫定投入された担当者を UI の「別人として確定」操作で
    # active に戻す解消フローが本番 PostgreSQL でも 500 にならず動く。
    pending_dedup_review = "pending_dedup_review"


# ========== 副テーブル ==========


class ContactEmailInput(BaseModel):
    email: str = Field(max_length=255)
    purpose: str | None = Field(default=None, max_length=50)

    @field_validator("email")
    @classmethod
    def _check_email(cls, v: str) -> str:
        # email は必須なので None にはならない。validate_email_loose は
        # 非 None 入力に対して正規化値を返すか ValueError を raise する。
        result = validate_email_loose(v)
        assert result is not None  # safety: str 入力に対しては必ず str 返す
        return result


class ContactEmailResponse(ContactEmailInput):
    id: int
    model_config = {"from_attributes": True}


class ContactDiscordInput(BaseModel):
    is_joined: bool = False
    channel_id: str | None = Field(default=None, max_length=50)
    user_id: str | None = Field(default=None, max_length=50)
    invoice_webhook: str | None = None
    shipment_webhook: str | None = None


class ContactDiscordResponse(ContactDiscordInput):
    model_config = {"from_attributes": True}


class ContactChannelInput(BaseModel):
    """連絡ツール 1行（Phase 1-B-1 相当、担当者単位版）"""
    channel: str = Field(min_length=1, max_length=30, description="whatsapp/discord/instagram/facebook_messenger/line_id/telegram/email/phone/referral 等")
    purpose: str | None = Field(default=None, max_length=50, description="用途（'商談用' 等）")
    is_primary: bool = Field(default=False, description="主連絡ツール。1 contact につき最大1つ")


class ContactChannelResponse(ContactChannelInput):
    id: int
    model_config = {"from_attributes": True}


# ========== 本体 ==========


class ContactCreate(BaseModel):
    company_id: int = Field(description="所属会社 id（必須）")
    contact_code: str | None = Field(
        default=None, max_length=20,
        description="CT-00001 形式。未指定ならサーバー側で自動採番",
    )
    lead_id: int | None = Field(default=None, description="出自リード")
    surname: str | None = Field(default=None, max_length=100)
    given_name: str | None = Field(default=None, max_length=100)
    display_name: str | None = Field(default=None, max_length=255)
    job_title: str | None = Field(default=None, max_length=100)
    department: str | None = Field(default=None, max_length=100)
    is_primary_contact: bool = Field(default=False, description="会社内の主窓口。1会社につき最大1つ")
    primary_email: str | None = Field(default=None, max_length=255)
    primary_phone: str | None = Field(default=None, max_length=50)
    status: ContactStatus = ContactStatus.active
    notes: str | None = None
    # 副テーブル
    emails: list[ContactEmailInput] = Field(default_factory=list)
    discord: ContactDiscordInput | None = None
    contact_channels: list[ContactChannelInput] = Field(default_factory=list)

    @field_validator("primary_email")
    @classmethod
    def _check_email(cls, v: str | None) -> str | None:
        return validate_email_loose(v)

    @field_validator("primary_phone")
    @classmethod
    def _check_phone(cls, v: str | None) -> str | None:
        return validate_phone(v)


class ContactUpdate(BaseModel):
    company_id: int | None = None
    lead_id: int | None = None
    surname: str | None = Field(default=None, max_length=100)
    given_name: str | None = Field(default=None, max_length=100)
    display_name: str | None = Field(default=None, max_length=255)
    job_title: str | None = Field(default=None, max_length=100)
    department: str | None = Field(default=None, max_length=100)
    is_primary_contact: bool | None = None
    primary_email: str | None = Field(default=None, max_length=255)
    primary_phone: str | None = Field(default=None, max_length=50)
    status: ContactStatus | None = None
    notes: str | None = None
    # None = 触らない、[]=空に置換
    emails: list[ContactEmailInput] | None = None
    discord: ContactDiscordInput | None = None
    contact_channels: list[ContactChannelInput] | None = None

    @field_validator("primary_email")
    @classmethod
    def _check_email(cls, v: str | None) -> str | None:
        return validate_email_loose(v)

    @field_validator("primary_phone")
    @classmethod
    def _check_phone(cls, v: str | None) -> str | None:
        return validate_phone(v)


class ContactResponse(BaseModel):
    id: int
    tenant_id: int
    company_id: int
    contact_code: str
    lead_id: int | None
    surname: str | None
    given_name: str | None
    display_name: str | None
    job_title: str | None
    department: str | None
    is_primary_contact: bool
    primary_email: str | None
    primary_phone: str | None
    status: str
    notes: str | None
    emails: list[ContactEmailResponse] = Field(default_factory=list)
    discord: ContactDiscordResponse | None = None
    contact_channels: list[ContactChannelResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
