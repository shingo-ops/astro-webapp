"""Pydantic schemas for `/super-admin/inbound/discord/*` endpoints.

spec.md v1.1 F5 (Sprint 5) AC5.5:
  - 中央 admin 用 inbound 一覧 / 詳細 API レスポンス schema
  - parse_status / parse_engine は文字列のまま返す（フロントで i18n マッピング）
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field


class DiscordInboundListItem(BaseModel):
    """一覧 view 用の薄い schema（raw_content は 200 chars に truncate）。"""

    id: int
    discord_message_id: str
    discord_channel_id: str
    supplier_id: int | None = None
    supplier_name: str | None = None
    raw_content_preview: str = Field(
        ..., description="raw_content を 200 chars で truncate した preview"
    )
    parse_status: str
    parse_engine: str | None = None
    received_at: datetime
    llm_cost_usd: Decimal | None = None


class DiscordInboundDetail(BaseModel):
    """詳細 view 用の full schema (parse_result_json も含む)。"""

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


class InboundProductCandidate(BaseModel):
    """受信通知の解析結果から抽出した、商品マスタ未登録の商品名候補。"""

    name: str
    occurrences: int = Field(..., description="受信通知の解析結果中での出現回数")
    sample: str | None = Field(default=None, description="抽出元の受信本文サンプル（raw_line）")
    # PR5c: 取込時に商品マスタへ転記する付随情報。
    unit: str | None = Field(default=None, description="代表的な取引単位（carton→case 正規化済・小文字）")
    condition: str | None = Field(default=None, description="代表的な状態（小文字）")
    language: str = Field(default="ja", description="既定言語（全件 ja。取込時に en へ修正可）")


class InboundProductCandidatesResponse(BaseModel):
    candidates: list[InboundProductCandidate]
    total: int


class InboundProductImportApply(BaseModel):
    """選択された商品名候補を商品マスタ（public.products）へ一括登録する。"""

    names: list[str] = Field(default_factory=list, description="登録する商品名のリスト")
    category: str | None = Field(default=None, max_length=50, description="一括で付与する分類（任意）")
    # PR5c: 商品名→言語コード（ja/en）の上書きマップ。オペレータが候補UIで修正した値。
    # 未指定の名前は商品名から自動判定する。
    languages: dict[str, str] = Field(default_factory=dict, description="商品名ごとの言語コード上書き（ja/en）")


class InboundProductImportApplyResponse(BaseModel):
    inserted: int = Field(..., description="新規登録された件数（既存同名はスキップ）")
    skipped: int = Field(default=0, description="既存同名のためスキップした件数")


__all__ = [
    "DiscordInboundListItem",
    "DiscordInboundDetail",
    "InboundProductCandidate",
    "InboundProductCandidatesResponse",
    "InboundProductImportApply",
    "InboundProductImportApplyResponse",
]
