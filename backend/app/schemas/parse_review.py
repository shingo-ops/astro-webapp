"""Pydantic schemas for `/super-admin/parse-review/*` endpoints.

spec.md v1.1 F6 (Sprint 6):
  - 中央 admin が `public.discord_inbound_messages.parse_result_json` を行単位で
    review → 承認時に `public.inventory_movements` へ append-only INSERT +
    `public.products.stock_quantity` を delta_qty 反映
  - 楽観ロック (`version`) で同時承認の後勝ち禁止 (AC6.5)
  - reject 操作で `exclude_reason` 必須 (AC6.4)
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.inventory_offers import InventoryCondition, InventoryUnit


class ReviewItemInput(BaseModel):
    """承認対象の 1 行（採用 / 編集後 / 新規追加すべて同じ形）。

    `product_id` が `None` の行は inventory_movements への反映を skip して
    `parse_result_json.skipped[]` へフォールバック保存（product 名寄せ未完）。

    Sprint 11 / F11 AC11.3:
      condition / quantity_offered / unit_price は public.inventory への
      UPSERT 用の任意フィールド。condition が指定 + 呼出側で supplier_id
      が確定している場合のみ inventory_movements に加えて public.inventory
      も更新される。condition が None なら inventory UPSERT は skip し
      従来挙動 (inventory_movements + products.stock_quantity のみ反映)。
    """

    product_id: int | None = Field(
        default=None,
        description="public.products.id。None なら inventory_movements へ反映しない",
    )
    delta_qty: int = Field(
        ...,
        description=(
            "在庫差分。正=入荷、負=出庫。0 = 中央在庫を動かさず "
            "public.inventory のオファーのみ記録 (QA 2026-05-30 / Option Z)。"
        ),
    )
    alias_text: str | None = Field(
        default=None,
        max_length=255,
        description="仕入元固有の言い回し（保存のみ、反映対象外）",
    )
    notes: str | None = Field(default=None, max_length=500)
    # parse_result_json.items[] の元 index（採用された行の追跡用、任意）
    original_index: int | None = Field(default=None, ge=0)

    # Sprint 11 / F11 AC11.3 拡張 (任意・後方互換)
    # 正規 16 値は InventoryCondition 参照 (migration 089)。None なら inventory UPSERT skip。
    condition: InventoryCondition | None = Field(
        default=None,
        description=(
            "商品の状態。migration 089 正規値 16 種。"
            "public.inventory UNIQUE(supplier_id × product_id × condition) の"
            "discriminator。None なら inventory UPSERT は skip。"
        ),
    )
    quantity_offered: int | None = Field(
        default=None,
        ge=0,
        description=(
            "仕入元が今オファーしている在庫数量。public.inventory.quantity に"
            "UPSERT される。None なら apply 側で after_qty で代替 (後方互換)。"
        ),
    )
    unit_price: int | None = Field(
        default=None,
        ge=0,
        description=(
            "仕入元の提示単価 (円・税抜)。public.inventory.unit_price に"
            "UPSERT される。None なら 0 で記録 (apply 側既定)。"
        ),
    )
    unit: InventoryUnit | None = Field(
        default=None,
        description=(
            "数量の単位。正規値: piece / pack / box / case / set。"
            "migration 084 で public.inventory.unit (VARCHAR(20)) へ UPSERT 保存される。None なら NULL。"
        ),
    )


class ApproveRequest(BaseModel):
    """approve リクエスト本体。

    version は AC6.5 楽観ロック用。クライアントが GET 時に受け取った
    `version` をそのまま戻すと、別 admin が先に approve/reject していれば
    server 側で `version` が増えており 409 を返す。
    """

    version: int = Field(..., ge=0, description="クライアント保持の version (AC6.5)")
    items: list[ReviewItemInput] = Field(
        default_factory=list,
        description="採用する行（順序保持）。空でも reject ではなく approve は許容",
    )
    skipped_indices: list[int] = Field(
        default_factory=list,
        description="parse_result_json.items[] のうち採用しなかった行 index (AC6.3)",
    )
    operator_comment: str | None = Field(
        default=None, max_length=2000, description="reviewer メモ (AC6.2)"
    )


class RejectRequest(BaseModel):
    """reject リクエスト本体。

    AC6.4: exclude_reason は必須（空文字 / 空白のみ → 400）。
    """

    version: int = Field(..., ge=0)
    exclude_reason: str = Field(..., min_length=1, max_length=1000)


class InventoryMovementSummary(BaseModel):
    """approve 結果の 1 行サマリ。"""

    movement_id: int
    product_id: int
    delta_qty: int
    before_qty: int
    after_qty: int


class ApproveResponse(BaseModel):
    """approve 結果。movements に作成された行と新しい version。

    Sprint 9 / F9 v1.2 拡張:
      - skipped_stock_update: Phase A 時に products.stock_quantity の更新を
        スキップしたかどうか。フロントエンドが warning toast 表示判定に使用。
      - phase: 当該承認操作実行時のテナント Phase ('A' / 'B' / 'C')。
      - offers_recorded: QA 2026-05-30 (Option Z)。中央在庫を動かさず
        public.inventory に記録した仕入元オファーの件数。
    """

    inbound_id: int
    parse_status: str
    version: int
    movements: list[InventoryMovementSummary]
    skipped_count: int
    # QA 2026-05-30 (Option Z): 在庫を動かさず public.inventory に記録したオファー件数
    offers_recorded: int = 0
    # Sprint 9 / F9 v1.2: Phase A 並走時の挙動を UI に伝える
    skipped_stock_update: bool = False
    phase: str = "B"


class RejectResponse(BaseModel):
    """reject 結果。"""

    inbound_id: int
    parse_status: str
    version: int
    exclude_reason: str


class ParseReviewDetail(BaseModel):
    """GET /super-admin/parse-review/{id} レスポンス。

    DiscordInboundDetail と似ているが、楽観ロック用の `version` と
    review 専用 fields のみに集約。
    """

    id: int
    discord_message_id: str
    discord_channel_id: str
    supplier_id: int | None = None
    supplier_name: str | None = None
    raw_content: str
    parse_status: str
    parse_engine: str | None = None
    parse_result_json: Any = None
    received_at: datetime
    exclude_reason: str | None = None
    operator_comment: str | None = None
    operator_id: int | None = None
    approved_at: datetime | None = None
    llm_cost_usd: Decimal | None = None
    created_at: datetime
    updated_at: datetime
    version: int


__all__ = [
    "ReviewItemInput",
    "ApproveRequest",
    "RejectRequest",
    "InventoryMovementSummary",
    "ApproveResponse",
    "RejectResponse",
    "ParseReviewDetail",
]
