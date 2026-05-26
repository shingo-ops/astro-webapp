from __future__ import annotations

"""
受注ごとの発送情報（order_shipping_details）テーブル用 Pydantic スキーマ。

ADR-021 Phase 3 / Sprint 3: 発送情報 MVP
  受注 1 件 = 発送情報 1 件（order_id UNIQUE）。OrderFlow Manager の
  「発送情報」27-85 列 + 「elogi連携」56-76 列を本テーブルへ分解する。
  eLogi CSV 出力を eLogi 既存フォーマット互換で実現する。

カラム概要:
  - 受取人: recipient_name / phone / email / tax_number
  - 住所: address1〜3 / city / state_code / zip_code / country_code
  - 寸法・重量: length_cm / width_cm / height_cm / weight_kg / volume_g / box_count
  - 梱包: packing_memo / packing_type / inspection_status
  - 品目: item_description / item_price_usd / exchange_rate / hs_code / tax_id / fedex_id
  - 配送: carrier (enum) / ship_method / ship_date / tracking_number / est_shipping_fee
  - ステータス: label_issued_at / pickup_requested_at / shipped_at / notified_at
  - メモ: ship_memo

変更履歴:
  2026-05-11: 初版（ADR-021 Phase 3 / Sprint 3）
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

# 配送キャリア enum（DB の CHECK 制約と一致させる）。
# 'elogi' / 'fedex' / 'dhl' / 'yamato' / 'other' のみ許可。
# adapter 層は subclass で簡単に拡張できる構造で、本 Sprint は eLogi のみ実装。
CarrierLiteral = Literal["elogi", "fedex", "dhl", "yamato", "other"]


# 入力可能カラム（router 側のホワイトリストとして使用）
INPUT_FIELDS: tuple[str, ...] = (
    # 受取人
    "recipient_name", "phone", "email", "tax_number",
    # 住所
    "address1", "address2", "address3", "city",
    "state_code", "zip_code", "country_code",
    # 寸法・重量
    "length_cm", "width_cm", "height_cm",
    "weight_kg", "volume_g", "box_count",
    # 梱包
    "packing_memo", "packing_type", "inspection_status",
    # 品目
    "item_description", "item_price_usd", "exchange_rate",
    "hs_code", "tax_id", "fedex_id",
    # 配送
    "carrier", "ship_method", "ship_date",
    "tracking_number", "est_shipping_fee",
    # ステータス
    "label_issued_at", "pickup_requested_at",
    "shipped_at", "notified_at",
    # メモ
    "ship_memo",
)


class OrderShippingDetailBase(BaseModel):
    """発送情報の入力フィールド集合。

    全フィールド optional で、画面の段階入力に対応する（受注 → 採寸 → 集荷依頼 →
    追跡番号確定の流れで都度 PATCH される想定）。
    """
    # 受取人
    recipient_name: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    email: str | None = Field(default=None, max_length=255)
    tax_number: str | None = Field(default=None, max_length=100)

    # 住所
    address1: str | None = Field(default=None, max_length=255)
    address2: str | None = Field(default=None, max_length=255)
    address3: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, max_length=100)
    state_code: str | None = Field(default=None, max_length=20)
    zip_code: str | None = Field(default=None, max_length=50)
    country_code: str | None = Field(default=None, max_length=10)

    # 寸法・重量（負値禁止 / 上限は max_digits で吸収）
    length_cm: Decimal | None = Field(default=None, ge=0, max_digits=8, decimal_places=2)
    width_cm: Decimal | None = Field(default=None, ge=0, max_digits=8, decimal_places=2)
    height_cm: Decimal | None = Field(default=None, ge=0, max_digits=8, decimal_places=2)
    weight_kg: Decimal | None = Field(default=None, ge=0, max_digits=8, decimal_places=3)
    volume_g: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    box_count: int | None = Field(default=None, ge=0)

    # 梱包
    packing_memo: str | None = Field(default=None, max_length=5000)
    packing_type: str | None = Field(default=None, max_length=50)
    inspection_status: str | None = Field(default=None, max_length=50)

    # 品目
    item_description: str | None = Field(default=None, max_length=500)
    item_price_usd: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    exchange_rate: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=6)
    hs_code: str | None = Field(default=None, max_length=50)
    tax_id: str | None = Field(default=None, max_length=100)
    fedex_id: str | None = Field(default=None, max_length=100)

    # 配送
    carrier: CarrierLiteral | None = None
    ship_method: str | None = Field(default=None, max_length=50)
    ship_date: date | None = None
    tracking_number: str | None = Field(default=None, max_length=200)
    est_shipping_fee: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)

    # ステータス
    label_issued_at: datetime | None = None
    pickup_requested_at: datetime | None = None
    shipped_at: datetime | None = None
    notified_at: datetime | None = None

    # メモ
    ship_memo: str | None = Field(default=None, max_length=5000)


class OrderShippingDetailCreate(OrderShippingDetailBase):
    """新規作成リクエスト。order_id は URL パスから渡される。"""
    pass


class OrderShippingDetailUpdate(OrderShippingDetailBase):
    """部分更新リクエスト。全フィールド optional は Base と同じ。
    router 側で `model_dump(exclude_unset=True)` を使い、明示指定された列のみ
    UPDATE する（None で「クリアしたい」場合は明示的に null を渡す必要あり）。
    """
    pass


class OrderShippingDetailResponse(OrderShippingDetailBase):
    """レスポンス。DB 列のメタ情報を含む。"""
    id: int
    order_id: int
    tenant_id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ElogiCsvLine(BaseModel):
    """eLogi CSV 1 行分のフィールド集合（19 列）。

    Config.gs col 56-76 と同じ並び順:
      timestamp / ship_staff / order_type / order_no / order_date /
      sku / image_url / product_title / qty / usd_price /
      buyer_id / recipient / phone / email / country / state /
      city / zip / address1
    """
    timestamp: str = ""
    ship_staff: str = ""
    order_type: str = ""
    order_no: str = ""
    order_date: str = ""
    sku: str = ""
    image_url: str = ""
    product_title: str = ""
    qty: str = ""
    usd_price: str = ""
    buyer_id: str = ""
    recipient: str = ""
    phone: str = ""
    email: str = ""
    country: str = ""
    state: str = ""
    city: str = ""
    zip: str = ""
    address1: str = ""
