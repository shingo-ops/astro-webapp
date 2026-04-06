"""
顧客（customers）テーブル用Pydanticスキーマ。

テナントスキーマの customers テーブル定義:
  id, tenant_id, name, email, phone, company, notes, created_at, updated_at
"""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.schemas.base import validate_phone, validate_email_loose


class CustomerCreate(BaseModel):
    """顧客登録リクエスト"""
    name: str = Field(min_length=1, max_length=255, description="顧客名")
    email: str | None = Field(default=None, max_length=255, description="メールアドレス")
    phone: str | None = Field(default=None, max_length=50, description="電話番号")
    company: str | None = Field(default=None, max_length=255, description="会社名")
    notes: str | None = Field(default=None, max_length=5000, description="備考")

    @field_validator("email")
    @classmethod
    def check_email(cls, v: str | None) -> str | None:
        return validate_email_loose(v)

    @field_validator("phone")
    @classmethod
    def check_phone(cls, v: str | None) -> str | None:
        return validate_phone(v)


class CustomerUpdate(BaseModel):
    """顧客更新リクエスト（部分更新: 指定したフィールドのみ更新）"""
    name: str | None = Field(default=None, min_length=1, max_length=255)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    company: str | None = Field(default=None, max_length=255)
    notes: str | None = Field(default=None, max_length=5000)

    @field_validator("email")
    @classmethod
    def check_email(cls, v: str | None) -> str | None:
        return validate_email_loose(v)

    @field_validator("phone")
    @classmethod
    def check_phone(cls, v: str | None) -> str | None:
        return validate_phone(v)


class CustomerResponse(BaseModel):
    """顧客情報レスポンス"""
    id: int
    name: str
    email: str | None
    phone: str | None
    company: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
