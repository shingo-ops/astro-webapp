"""
注文（orders）テーブル用Pydanticスキーマ。

テナントスキーマの orders テーブル定義:
  id, tenant_id, customer_id, deal_id, order_number, total_amount, status, notes, created_at, updated_at
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field


class OrderStatus(str, Enum):
    """注文ステータスの定義値"""
    pending = "pending"
    confirmed = "confirmed"
    shipped = "shipped"
    delivered = "delivered"
    cancelled = "cancelled"


class OrderCreate(BaseModel):
    """注文登録リクエスト"""
    customer_id: int = Field(ge=1, description="顧客ID")
    deal_id: int | None = Field(default=None, ge=1, description="関連商談ID")
    order_number: str = Field(min_length=1, max_length=100, description="注文番号")
    total_amount: Decimal | None = Field(default=None, ge=0, max_digits=15, decimal_places=2, description="合計金額")
    status: OrderStatus = Field(default=OrderStatus.pending, description="ステータス")
    notes: str | None = Field(default=None, max_length=5000, description="備考")


class OrderUpdate(BaseModel):
    """注文更新リクエスト（部分更新）"""
    customer_id: int | None = Field(default=None, ge=1)
    deal_id: int | None = Field(default=None, ge=1)
    order_number: str | None = Field(default=None, min_length=1, max_length=100)
    total_amount: Decimal | None = Field(default=None, ge=0, max_digits=15, decimal_places=2)
    status: OrderStatus | None = None
    notes: str | None = Field(default=None, max_length=5000)


class OrderResponse(BaseModel):
    """注文情報レスポンス"""
    id: int
    customer_id: int
    deal_id: int | None
    order_number: str
    total_amount: Decimal | None
    status: str
    notes: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
