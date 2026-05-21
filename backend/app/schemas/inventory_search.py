"""営業向け在庫検索 API のレスポンス schema (Sprint 7 / spec F7)。

spec.md v1.1 F7 / AC7.4 / AC7.9:
  - 検索結果には matched_via, score, supplier 情報を含める (UI でバッジ表示)
  - inventory.visibility.full=false の user では stock_quantity を None で返す
    (フロント側で `***` 表示、AC7.9)
"""
from __future__ import annotations

from pydantic import BaseModel, Field


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
