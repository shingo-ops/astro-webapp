"""営業向け在庫検索 API のレスポンス schema (Sprint 7 / spec F7)。

spec.md v1.1 F7 / AC7.4 / AC7.9:
  - 検索結果には matched_via, score, supplier 情報を含める (UI でバッジ表示)
  - inventory.visibility.full=false の user では stock_quantity を None で返す
    (フロント側で `***` 表示、AC7.9)

spec.md v1.3 F11 AC11.4 (Sprint 11):
  - 各検索結果に `inventory_offers` (仕入元 × condition × 数量/単価 の現在オファー)
    を埋め込む。営業フローで「仕入先 X が今 Y 個 Z 円」を表示。
  - inventory.visibility.full=false の user では offers も全件マスクする
    (quantity / unit_price=None、AC11.4 + AC7.9 整合)。
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class InventoryOfferSummary(BaseModel):
    """検索結果に同梱する 1 件の仕入元現在オファー (spec v1.3 F11 AC11.4)。

    public.inventory (supplier_id × product_id × condition UNIQUE) の 1 行と対応。
    visibility.full を持たない user では quantity / unit_price=None でマスク。
    """

    supplier_id: int
    supplier_name: str | None = None
    condition: str
    quantity: int | None = Field(
        default=None,
        description="現在オファー数量。visibility=False の user では None でマスク。",
    )
    unit_price: int | None = Field(
        default=None,
        description="現在提示単価 (円)。visibility=False の user では None でマスク。",
    )
    status: str = Field(
        default="in_stock",
        description="in_stock / out_of_stock / reserved / archived",
    )


class InventorySearchCandidate(BaseModel):
    product_id: int
    name: str
    name_en: str | None = None
    product_code: str | None = None
    expansion_code: str | None = None
    card_number: str | None = None
    jan_code: str | None = None
    unit_price: float | None = None
    # AC7.9: visibility=false の user では None (フロントで `***` マスク表示)
    stock_quantity: int | None = Field(
        default=None,
        description="在庫数。inventory.visibility.full 権限を持たないユーザーには None を返す。",
    )
    supplier_default_id: int | None = None
    supplier_name: str | None = None
    image_url: str | None = None
    matched_via: str = Field(
        description=(
            "ヒット経路: "
            "products_name / products_name_en / products_card_number_exact / "
            "products_card_number / products_jan_code_exact / products_jan_code / "
            "products_expansion_code / pokemon_dex / trainer_dex / "
            "tcg_series / supplier_alias"
        )
    )
    score: float = Field(
        description="ranking score (昇順、小さいほど上位、在庫 0 は +1000 で末尾配置)。"
    )
    # spec v1.3 F11 AC11.4: 仕入元現在オファー一覧 (public.inventory から)
    inventory_offers: list[InventoryOfferSummary] = Field(
        default_factory=list,
        description=(
            "仕入元 × condition の現在オファー一覧。status='in_stock' のみ含む。"
            "visibility.full=false なら quantity / unit_price=None マスク。"
        ),
    )


class InventorySearchResponse(BaseModel):
    query: str
    op: str = Field(description="and / or")
    total: int
    masked: bool = Field(
        description=(
            "True の場合 inventory.visibility.full 権限不足のため "
            "全行の stock_quantity が None でマスクされている (AC7.9)。"
        )
    )
    candidates: list[InventorySearchCandidate]
