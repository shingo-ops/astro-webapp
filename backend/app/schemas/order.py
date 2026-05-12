from __future__ import annotations

"""
注文（orders）テーブル用Pydanticスキーマ。

変更履歴:
  2026-04-17: Phase 2拡張（配送情報、ステータス拡張、invoice_id追加）
  2026-04-27: Phase 1-B-2 Step 5d — 旧 customer_id を撤去し、
    company_id / contact_id を必須化（新 B2B モデル唯一の正）
  2026-05-11: ADR-021 Phase 1 / Sprint 1 — 受注一覧 MVP に伴い
    OrderListResponse / OrderGroupCountsResponse を追加
    （JOIN 結果の company_name / contact_display_name と
     ステータスごとの集計件数を表現するための薄い拡張）
  2026-05-13: ADR-021 J1 fix — OrderStatus enum から `confirmed` を撤去し
    ADR-021 第 1 節の正本 6 値（pending / processing / shipped / delivered /
    returned / cancelled）に揃える。既存 `confirmed` 行は migration 051
    で `pending` に統合される。

    Note: `order_purchase_details.purchase_status='confirmed'`（仕入確定フラグ）
    は **別ドメイン** で本変更の対象外。
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field


class OrderStatus(str, Enum):
    """ADR-021 第 1 節「ステータスフィルタ」の正本 6 値。

    日本語ラベル対応（フロント側で持つ）:
      pending → 未処理
      processing → 仕入中
      shipped → 配送中
      delivered → 完了
      returned → トラブル
      cancelled → キャンセル
    """
    pending = "pending"
    processing = "processing"
    shipped = "shipped"
    delivered = "delivered"
    returned = "returned"
    cancelled = "cancelled"


class OrderCreate(BaseModel):
    """注文登録リクエスト（Step 5d 以降は company_id + contact_id 必須）"""
    company_id: int = Field(ge=1, description="会社ID")
    contact_id: int = Field(ge=1, description="担当者ID")
    deal_id: int | None = Field(default=None, ge=1)
    invoice_id: int | None = Field(default=None, ge=1)
    order_number: str = Field(min_length=1, max_length=100)
    total_amount: Decimal | None = Field(default=None, ge=0, max_digits=15, decimal_places=2)
    currency: str = Field(default="JPY", max_length=10)
    status: OrderStatus = Field(default=OrderStatus.pending)
    shipping_carrier: str | None = Field(default=None, max_length=50)
    shipping_fee: Decimal | None = Field(default=None, ge=0, max_digits=15, decimal_places=2)
    shipping_country: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=5000)


class OrderUpdate(BaseModel):
    # 注意: company_id / contact_id / deal_id / invoice_id は
    # 作成後の変更を禁止（FK 整合性保護ポリシー）。router の _UPDATABLE_COLUMNS にも含まない。
    # schema にも出さないことで API コントラクトと router 挙動を一致させる。
    deal_id: int | None = Field(default=None, ge=1)
    invoice_id: int | None = Field(default=None, ge=1)
    order_number: str | None = Field(default=None, min_length=1, max_length=100)
    total_amount: Decimal | None = Field(default=None, ge=0, max_digits=15, decimal_places=2)
    currency: str | None = Field(default=None, max_length=10)
    status: OrderStatus | None = None
    shipping_carrier: str | None = Field(default=None, max_length=50)
    shipping_fee: Decimal | None = Field(default=None, ge=0, max_digits=15, decimal_places=2)
    tracking_number: str | None = Field(default=None, max_length=200)
    shipping_country: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=5000)


class OrderResponse(BaseModel):
    """注文情報レスポンス。

    Note: PR γ (Step 5d 最終クリーンアップ) で `contact_id: int` 必須に昇格。
    migration 035 で legacy 行 (contact_id IS NULL) は precondition で 0 件保証。
    """
    id: int
    company_id: int
    contact_id: int
    deal_id: int | None
    invoice_id: int | None
    order_number: str
    total_amount: Decimal | None
    currency: str | None
    status: str
    shipping_carrier: str | None
    shipping_fee: Decimal | None
    tracking_number: str | None
    shipped_at: datetime | None
    delivered_at: datetime | None
    shipping_country: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class OrderListResponse(OrderResponse):
    """注文一覧用レスポンス。

    ADR-021 Sprint 1: GET /orders から returns. JOIN で取得した
    company.name / contact.display_name を一覧表示用に同梱する。
    JOIN 失敗（FK 切れ / 削除済 etc.）の保険として null 許容。
    """
    company_name: str | None = None
    contact_display_name: str | None = None


class OrderGroupCountsResponse(BaseModel):
    """ステータスごとの受注件数 + 合計。

    ADR-021 Sprint 1: GET /orders/group-counts から returns.
    `counts` は OrderStatus enum 全値をキーとして含み、件数 0 のステータスも
    0 で返す（フロントエンドのバッジ実装が undefined を気にしなくて済む）。
    `?search=` 指定時はその検索条件下での集計を返す（一覧と件数バッジの連動）。
    """
    counts: dict[str, int]
    total: int
