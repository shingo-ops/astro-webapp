"""
認証関連Pydanticスキーマ。

元の app.auth.schemas から移動。後方互換性のため、旧パスからもインポート可能。
"""

from pydantic import BaseModel, EmailStr, Field


class UserRegister(BaseModel):
    """ユーザー登録リクエスト"""
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    username: str = Field(min_length=1, max_length=255)
    full_name: str | None = None
    tenant_code: str = Field(min_length=1, max_length=50)
    firebase_uid: str = Field(min_length=1, max_length=128)


class UserLogin(BaseModel):
    """ログインリクエスト"""
    email: EmailStr
    password: str


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
