from __future__ import annotations

"""
Bot 管理スキーマ。Phase 1 再設計版。

テナントスキーマの bots テーブルに対応。API キーは作成時のみ平文で返し、
以降は api_key_hash（bcrypt）のみ保持する。
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, field_validator

from app.schemas.base import validate_email_loose


class BotPurpose(str, Enum):
    invoice = "invoice"
    shipment = "shipment"
    notification = "notification"
    custom = "custom"


class BotStatus(str, Enum):
    active = "active"
    inactive = "inactive"
    maintenance = "maintenance"


class BotCreate(BaseModel):
    bot_code: str | None = Field(default=None, max_length=20, description="BOT-00001 形式。空欄なら自動採番")
    display_name: str = Field(min_length=1, max_length=100)
    purpose: BotPurpose
    status: BotStatus = BotStatus.active
    discord_user_id: str | None = Field(default=None, max_length=50)
    sender_email: str | None = Field(default=None, max_length=255)
    owner_staff_id: int

    @field_validator("sender_email")
    @classmethod
    def _check_email(cls, v: str | None) -> str | None:
        return validate_email_loose(v)


class BotUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    purpose: BotPurpose | None = None
    status: BotStatus | None = None
    discord_user_id: str | None = Field(default=None, max_length=50)
    sender_email: str | None = Field(default=None, max_length=255)
    owner_staff_id: int | None = None

    @field_validator("sender_email")
    @classmethod
    def _check_email(cls, v: str | None) -> str | None:
        return validate_email_loose(v)


class BotResponse(BaseModel):
    id: int
    tenant_id: int
    bot_code: str
    display_name: str
    purpose: str
    status: str
    discord_user_id: str | None
    sender_email: str | None
    owner_staff_id: int
    owner_staff_name: str | None = None
    last_executed_at: datetime | None
    execution_count: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class BotCreatedResponse(BotResponse):
    """作成時のみ平文 API キーを含めて返す"""
    api_key: str = Field(description="作成時のみ返される平文。この応答を逃すと再取得不能")
