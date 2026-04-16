from __future__ import annotations

"""
ロール・権限（roles, role_permissions, user_roles）用Pydanticスキーマ。

Discord式カスタムロール:
  - テナント管理者がロール自体を自由に作成
  - 1ユーザー＝複数ロール、権限は和集合
  - priority（優先順位）で管理権限を階層化
  - is_system=True のロール（オーナー/メンバー）は削除/編集不可

変更履歴:
  2026-04-16: 初版作成（Phase 1）
"""

import re
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def validate_hex_color(v: str | None) -> str | None:
    if v is None:
        return None
    if not HEX_COLOR_RE.match(v):
        raise ValueError("色は #RRGGBB 形式で指定してください")
    return v.lower()


class RoleCreate(BaseModel):
    """ロール作成リクエスト"""
    name: str = Field(min_length=1, max_length=100, description="ロール名")
    color: str | None = Field(default="#6c757d", max_length=7, description="表示色 #RRGGBB")
    priority: int = Field(default=1, ge=0, le=999, description="優先順位 (0-999、システムロール除く)")
    description: str | None = Field(default=None, max_length=500)

    @field_validator("color")
    @classmethod
    def check_color(cls, v: str | None) -> str | None:
        return validate_hex_color(v)


class RoleUpdate(BaseModel):
    """ロール更新リクエスト（部分更新）"""
    name: str | None = Field(default=None, min_length=1, max_length=100)
    color: str | None = Field(default=None, max_length=7)
    priority: int | None = Field(default=None, ge=0, le=999)
    description: str | None = Field(default=None, max_length=500)

    @field_validator("color")
    @classmethod
    def check_color(cls, v: str | None) -> str | None:
        return validate_hex_color(v)


class RoleResponse(BaseModel):
    """ロール情報レスポンス"""
    id: int
    name: str
    color: str | None
    priority: int
    is_system: bool
    description: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PermissionResponse(BaseModel):
    """パーミッション情報レスポンス"""
    id: int
    key: str
    resource: str
    action: str
    description: str
    category: str

    model_config = {"from_attributes": True}


class RolePermissionAssign(BaseModel):
    """ロールへの権限割り当てリクエスト"""
    permission_ids: list[int] = Field(default_factory=list, description="権限IDのリスト")


class UserRoleAssign(BaseModel):
    """ユーザーへのロール割り当てリクエスト"""
    role_ids: list[int] = Field(min_length=1, description="付与するロールIDのリスト")


class UserRoleResponse(BaseModel):
    """ユーザーに付与されているロールレスポンス"""
    role_id: int
    role_name: str
    color: str | None
    priority: int
    assigned_at: datetime
