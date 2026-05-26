from __future__ import annotations

"""
受注ごとの仕入情報（order_purchase_details）テーブル用 Pydantic スキーマ。

ADR-021 Phase 4 / Sprint 4: 仕入情報 MVP
  受注 1 件 = 仕入情報 1 件（order_id UNIQUE）。OrderFlow Manager の
  「仕入れ情報」（Config.gs col 86-99）を本テーブルへ分解する。
  既存 purchase_orders テーブル（migration 007）とは別系統で並行運用する
  （統合は別 ADR）。

カラム概要:
  - 仕入担当: purchase_staff（Phase 5 で staff_id FK 化、本 Sprint は文字列）
  - 取引: purchase_date / transaction_no
  - 仕入元: supplier_name / supplier_url（次 Sprint で suppliers テーブル参照化）
  - 金額・数量: purchase_amount / purchase_quantity / purchase_total /
    purchase_shipping
  - 配送: carrier_name / waybill_no
  - メモ・ステータス: purchase_note / purchase_status

導出フィールド（Python 側で計算）:
  - total_with_shipping = purchase_total + purchase_shipping

変更履歴:
  2026-05-11: 初版（ADR-021 Phase 4 / Sprint 4）
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

# 仕入ステータス Literal（DB の CHECK 制約と一致させる）。
# 拡張時は CHECK と Literal の両方を更新すること。
PurchaseStatusLiteral = Literal["", "confirmed"]


# 入力可能カラム（router 側のホワイトリストとして使用）。
# id / order_id / tenant_id / created_at / updated_at は別経路で扱う。
INPUT_FIELDS: tuple[str, ...] = (
    "purchase_staff",
    "purchase_date",
    "transaction_no",
    "supplier_name",
    "supplier_url",
    "purchase_amount",
    "purchase_quantity",
    "purchase_total",
    "purchase_shipping",
    "carrier_name",
    "waybill_no",
    "purchase_note",
    "purchase_status",
)


def _to_decimal(v: Any) -> Decimal:
    """None / float / int / Decimal を安全に Decimal に丸める。"""
    if v is None:
        return Decimal(0)
    if isinstance(v, Decimal):
        return v
    return Decimal(str(v))


def compute_derived(values: dict[str, Any]) -> dict[str, Any]:
    """入力 dict（DB row もしくは Pydantic dump）から導出フィールドを計算する。

    本 Sprint では `total_with_shipping = purchase_total + purchase_shipping` のみ。
    DB に列を持たせず Python 側で都度算出する（売上情報パネルと同じパターン）。
    """
    total = _to_decimal(values.get("purchase_total"))
    shipping = _to_decimal(values.get("purchase_shipping"))
    return {
        "total_with_shipping": total + shipping,
    }


class OrderPurchaseDetailBase(BaseModel):
    """仕入情報の入力フィールド集合。

    全フィールド optional で、画面の段階入力に対応する（仕入元決定 → 数量確定 →
    確定確認 → 配送追跡の流れで都度 PATCH される想定）。
    """
    # 仕入担当・取引情報
    purchase_staff: str | None = Field(default=None, max_length=255)
    purchase_date: date | None = None
    transaction_no: str | None = Field(default=None, max_length=255)

    # 仕入元
    supplier_name: str | None = Field(default=None, max_length=255)
    supplier_url: str | None = Field(default=None, max_length=2000)

    # 金額・数量（負値禁止）
    purchase_amount: Decimal | None = Field(
        default=None, ge=0, max_digits=14, decimal_places=2
    )
    purchase_quantity: int | None = Field(default=None, ge=0)
    purchase_total: Decimal | None = Field(
        default=None, ge=0, max_digits=14, decimal_places=2
    )
    purchase_shipping: Decimal | None = Field(
        default=None, ge=0, max_digits=14, decimal_places=2
    )

    # 配送
    carrier_name: str | None = Field(default=None, max_length=255)
    waybill_no: str | None = Field(default=None, max_length=255)

    # メモ
    purchase_note: str | None = Field(default=None, max_length=5000)

    # ステータス（"" = 確認中 / "confirmed" = 確定済み）
    purchase_status: PurchaseStatusLiteral | None = None


class OrderPurchaseDetailCreate(OrderPurchaseDetailBase):
    """新規作成リクエスト。order_id は URL パスから渡される。"""
    pass


class OrderPurchaseDetailUpdate(OrderPurchaseDetailBase):
    """部分更新リクエスト。全フィールド optional は Base と同じ。
    router 側で `model_dump(exclude_unset=True)` を使い、明示指定された列のみ
    UPDATE する（None で「クリアしたい」場合は明示的に null を渡す必要あり）。
    """
    pass


class OrderPurchaseDetailStatusUpdate(BaseModel):
    """`PATCH /orders/{id}/purchase/status` 用の最小ボディ。

    status は省略可能で、省略時は 'confirmed' に切り替える業務ショートカット
    （現状の最頻ユースケース = 「確定」ボタン）。
    'confirmed' / '' のいずれかを明示することも許可する（取り消し用途）。
    """
    status: PurchaseStatusLiteral | None = None


class OrderPurchaseDetailResponse(OrderPurchaseDetailBase):
    """レスポンス。DB 列 + 導出フィールドを返す。"""
    id: int
    order_id: int
    tenant_id: int
    created_at: datetime
    updated_at: datetime

    # 導出フィールド
    total_with_shipping: Decimal

    model_config = {"from_attributes": True}

    @model_validator(mode="before")
    @classmethod
    def _fill_derived(cls, values: Any) -> Any:
        """DB row から構築する際に導出フィールドが無い場合は自動計算する。"""
        if not isinstance(values, dict):
            try:
                values = dict(values)
            except (TypeError, ValueError):
                return values
        if "total_with_shipping" not in values or values.get("total_with_shipping") is None:
            values.update(compute_derived(values))
        return values


class PurchaseBySupplierItem(BaseModel):
    """仕入元別取引履歴の 1 行。

    `GET /purchase/by-supplier` のレスポンス items に並ぶ。受注本体の
    order_number / 顧客名は JOIN 取得して同梱する（一覧画面用に最小限の情報を返す）。
    """
    id: int
    order_id: int
    order_number: str | None = None
    purchase_date: date | None = None
    transaction_no: str | None = None
    supplier_name: str | None = None
    supplier_url: str | None = None
    purchase_amount: Decimal | None = None
    purchase_quantity: int | None = None
    purchase_total: Decimal | None = None
    purchase_shipping: Decimal | None = None
    purchase_status: str | None = None
    created_at: datetime
    updated_at: datetime


class PurchaseBySupplierResponse(BaseModel):
    """`GET /purchase/by-supplier` のレスポンス。

    OrderFlow の仕入元別履歴ビューに対応するページング応答。
    検索キーワード（partial match）と total / page / per_page をエコーバックする。
    """
    items: list[PurchaseBySupplierItem]
    total: int
    page: int
    per_page: int
    supplier_name: str | None = None
