from __future__ import annotations

"""
認証関連Pydanticスキーマ。

元の app.auth.schemas から移動。後方互換性のため、旧パスからもインポート可能。
"""

from pydantic import BaseModel, Field, field_validator

from app.schemas.base import validate_email_loose


class UserRegister(BaseModel):
    """ユーザー登録リクエスト

    email は EmailStr ではなく簡易バリデーション（validate_email_loose）を使う。
    .local 等のRFC予約TLDも識別子として許容するため。実在性チェックは
    上流のFirebase Auth側で担保される。
    """
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=72)
    username: str = Field(min_length=1, max_length=255)
    full_name: str | None = None
    tenant_code: str = Field(min_length=1, max_length=50)
    firebase_uid: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def check_email(cls, v: str) -> str:
        return validate_email_loose(v)


class UserLogin(BaseModel):
    """ログインリクエスト"""
    email: str = Field(min_length=3, max_length=255)
    password: str

    @field_validator("email")
    @classmethod
    def check_email(cls, v: str) -> str:
        return validate_email_loose(v)


class TokenResponse(BaseModel):
    """ログイン成功時のレスポンス"""
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    """JWTトークンの中身（デコード後）"""
    user_id: int
    email: str
    tenant_id: int
    tenant_code: str
    role: str


class UserResponse(BaseModel):
    """ユーザー情報レスポンス"""
    id: int
    email: str
    username: str
    full_name: str | None
    tenant_id: int
    role: str
    is_active: bool

    model_config = {"from_attributes": True}
