"""
商談（deals）テーブル用Pydanticスキーマ。

テナントスキーマの deals テーブル定義:
  id, tenant_id, customer_id, title, amount, status, expected_close_date, notes, created_at, updated_at
"""

from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field


class DealStatus(str, Enum):
    """商談ステータスの定義値"""
    open = "open"
    won = "won"
    lost = "lost"
    negotiating = "negotiating"
    on_hold = "on_hold"


class DealCreate(BaseModel):
    """商談登録リクエスト"""
    customer_id: int = Field(ge=1, description="顧客ID")
    title: str = Field(min_length=1, max_length=255, description="商談タイトル")
    amount: Decimal | None = Field(default=None, ge=0, max_digits=15, decimal_places=2, description="金額")
    status: DealStatus = Field(default=DealStatus.open, description="ステータス")
    expected_close_date: date | None = Field(default=None, description="成約予定日")
    notes: str | None = Field(default=None, max_length=5000, description="備考")


class DealUpdate(BaseModel):
    """商談更新リクエスト（部分更新）"""
    customer_id: int | None = Field(default=None, ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=255)
    amount: Decimal | None = Field(default=None, ge=0, max_digits=15, decimal_places=2)
    status: DealStatus | None = None
    expected_close_date: date | None = None
    notes: str | None = Field(default=None, max_length=5000)


class DealResponse(BaseModel):
    """商談情報レスポンス"""
    id: int
    customer_id: int
    title: str
    amount: Decimal | None
    status: str
    expected_close_date: date | None
    notes: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
