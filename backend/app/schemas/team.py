from __future__ import annotations

"""
チーム（teams, team_members）用Pydanticスキーマ。

変更履歴:
  2026-04-16: 初版作成（Phase 1）
"""

from datetime import datetime

from pydantic import BaseModel, Field


class TeamCreate(BaseModel):
    """チーム作成リクエスト"""
    name: str = Field(min_length=1, max_length=100)
    leader_id: int | None = Field(default=None, ge=1, description="リーダーユーザーID")
    description: str | None = Field(default=None, max_length=500)


class TeamUpdate(BaseModel):
    """チーム更新リクエスト（部分更新）"""
    name: str | None = Field(default=None, min_length=1, max_length=100)
    leader_id: int | None = Field(default=None, ge=1)
    description: str | None = Field(default=None, max_length=500)
    is_active: bool | None = None


class TeamResponse(BaseModel):
    """チーム情報レスポンス"""
    id: int
    name: str
    leader_id: int | None
    description: str | None
    is_active: bool
    member_count: int | None = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TeamMemberAdd(BaseModel):
    """チームメンバー追加リクエスト"""
    user_id: int = Field(ge=1)


class TeamMemberResponse(BaseModel):
    """チームメンバー情報レスポンス"""
    user_id: int
    username: str | None
    email: str | None
    joined_at: datetime
