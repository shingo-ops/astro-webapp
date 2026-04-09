from __future__ import annotations

"""
テナント関連Pydanticスキーマ。

元の app.routers.admin 内のインラインモデルから分離。
"""

from pydantic import BaseModel, Field


class TenantCreate(BaseModel):
    """テナント登録リクエスト"""
    tenant_name: str = Field(min_length=1, max_length=255)
    tenant_code: str = Field(min_length=1, max_length=50, pattern=r"^[a-z0-9\-]+$")


class TenantResponse(BaseModel):
    """テナント情報レスポンス"""
    id: int
    tenant_name: str
    tenant_code: str
    is_active: bool
    schema_name: str

    model_config = {"from_attributes": True}
