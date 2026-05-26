from __future__ import annotations

"""
仕入先（suppliers）用Pydanticスキーマ。

変更履歴:
  2026-04-17: 初版作成（Phase 3）
"""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.schemas.base import validate_email_loose, validate_phone


class SupplierCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    contact_name: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    address: str | None = Field(default=None, max_length=5000)
    notes: str | None = Field(default=None, max_length=5000)

    @field_validator("email")
    @classmethod
    def check_email(cls, v: str | None) -> str | None:
        return validate_email_loose(v)

    @field_validator("phone")
    @classmethod
    def check_phone(cls, v: str | None) -> str | None:
        return validate_phone(v)


class SupplierUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    contact_name: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    address: str | None = Field(default=None, max_length=5000)
    is_active: bool | None = None
    notes: str | None = Field(default=None, max_length=5000)

    @field_validator("email")
    @classmethod
    def check_email(cls, v: str | None) -> str | None:
        return validate_email_loose(v)

    @field_validator("phone")
    @classmethod
    def check_phone(cls, v: str | None) -> str | None:
        return validate_phone(v)


class SupplierResponse(BaseModel):
    id: int
    supplier_code: str | None
    name: str
    contact_name: str | None
    email: str | None
    phone: str | None
    address: str | None
    notes: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
