"""TenantProfile Pydantic schemas (Sprint 8 / F8)

PO PDF / メール送信時の差出人情報 (各テナント名義) を管理する。
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

_VALID_LANGUAGES = {"ja", "en", "ko", "zh"}


class TenantProfileResponse(BaseModel):
    id: int
    company_name: str | None = None
    company_name_en: str | None = None
    address: str | None = None
    phone: str | None = None
    email: str | None = None
    website: str | None = None
    seal_image_url: str | None = None
    default_language: str = "ja"
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TenantProfileUpdate(BaseModel):
    company_name: str | None = Field(default=None, max_length=255)
    company_name_en: str | None = Field(default=None, max_length=255)
    address: str | None = Field(default=None, max_length=5000)
    phone: str | None = Field(default=None, max_length=50)
    email: str | None = Field(default=None, max_length=255)
    website: str | None = Field(default=None, max_length=255)
    seal_image_url: str | None = Field(default=None, max_length=5000)
    default_language: str | None = Field(default=None, min_length=2, max_length=2)

    @field_validator("default_language")
    @classmethod
    def _validate_language(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if v not in _VALID_LANGUAGES:
            raise ValueError(
                f"default_language must be one of {sorted(_VALID_LANGUAGES)}"
            )
        return v
