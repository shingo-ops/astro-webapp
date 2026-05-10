from __future__ import annotations

"""
受注ごとの売上情報（order_financials）テーブル用 Pydantic スキーマ。

ADR-021 Phase 2 / Sprint 2: 売上計算 MVP
  受注 1 件 = 売上情報 1 件（order_id UNIQUE）。OrderFlow Manager の
  「売上情報」27 列を本テーブルへ分解し、Phase 5（報酬計算）で必要な
  commission_base_amount フィールドも先取りで保持する。

導出列（DB ではなく Python 側で計算してレスポンスに同梱）:
  - cost_total = 仕入原価 + 仕入送料 + 各種手数料 + 返送料 + 返金額
  - gross_profit = revenue_amount - cost_total
  - gross_profit_rate = gross_profit / revenue_amount（revenue_amount=0 のとき null）
  - operating_profit_with_tax_refund = gross_profit + tax_refund

変更履歴:
  2026-05-11: 初版（ADR-021 Phase 2 / Sprint 2）
"""

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field, model_validator


# 入力可能な数値カラム（Pydantic では default 0 で受け取る）
_INPUT_FIELDS: tuple[str, ...] = (
    "revenue_amount",
    "purchase_cost",
    "purchase_shipping",
    "paypal_fee",
    "wise_fee",
    "exchange_fee",
    "outsource_fee",
    "packing_fee",
    "ad_cost",
    "return_fee",
    "refund_amount",
    "commission_base_amount",
    "tax_refund",
)

# cost_total を構成するカラム（commission_base_amount / tax_refund は対象外）
_COST_FIELDS: tuple[str, ...] = (
    "purchase_cost",
    "purchase_shipping",
    "paypal_fee",
    "wise_fee",
    "exchange_fee",
    "outsource_fee",
    "packing_fee",
    "ad_cost",
    "return_fee",
    "refund_amount",
)


def _to_decimal(v: Any) -> Decimal:
    """None / float / int / Decimal を安全に Decimal に丸める。

    数値カラムは DB 側で DEFAULT 0 だが、SELECT 時 NULL が返る経路（OUTER JOIN や
    旧データ復旧）も想定し、None は 0 として扱う。
    """
    if v is None:
        return Decimal(0)
    if isinstance(v, Decimal):
        return v
    return Decimal(str(v))


def compute_derived(values: dict[str, Any]) -> dict[str, Any]:
    """入力 dict（DB row もしくは Pydantic dump）から導出列 4 種を計算する。

    呼び出し側は dict を渡すこと（asyncpg.Record / Pydantic model_dump 結果いずれも可）。
    revenue_amount=0 の場合 gross_profit_rate は None を返す（ZeroDivisionError 回避）。
    """
    cost_total = sum((_to_decimal(values.get(k)) for k in _COST_FIELDS), Decimal(0))
    revenue = _to_decimal(values.get("revenue_amount"))
    gross_profit = revenue - cost_total
    if revenue == 0:
        gross_profit_rate: Decimal | None = None
    else:
        # 小数 6 桁で丸め（フロントは小数 1 桁の % 表示）。Decimal の挙動を安定させる。
        gross_profit_rate = (gross_profit / revenue).quantize(Decimal("0.000001"))
    tax_refund = _to_decimal(values.get("tax_refund"))
    operating_profit_with_tax_refund = gross_profit + tax_refund
    return {
        "cost_total": cost_total,
        "gross_profit": gross_profit,
        "gross_profit_rate": gross_profit_rate,
        "operating_profit_with_tax_refund": operating_profit_with_tax_refund,
    }


class OrderFinancialBase(BaseModel):
    """売上情報の入力フィールド集合（13 列）。

    全列に default 0 を持たせ、UI から部分入力されたフォームでも 0 で埋まる
    ようにする。負値は API レイヤで弾く（ge=0）。
    """
    revenue_amount: Decimal = Field(default=Decimal(0), ge=0, max_digits=14, decimal_places=2)
    purchase_cost: Decimal = Field(default=Decimal(0), ge=0, max_digits=14, decimal_places=2)
    purchase_shipping: Decimal = Field(default=Decimal(0), ge=0, max_digits=14, decimal_places=2)
    paypal_fee: Decimal = Field(default=Decimal(0), ge=0, max_digits=14, decimal_places=2)
    wise_fee: Decimal = Field(default=Decimal(0), ge=0, max_digits=14, decimal_places=2)
    exchange_fee: Decimal = Field(default=Decimal(0), ge=0, max_digits=14, decimal_places=2)
    outsource_fee: Decimal = Field(default=Decimal(0), ge=0, max_digits=14, decimal_places=2)
    packing_fee: Decimal = Field(default=Decimal(0), ge=0, max_digits=14, decimal_places=2)
    ad_cost: Decimal = Field(default=Decimal(0), ge=0, max_digits=14, decimal_places=2)
    return_fee: Decimal = Field(default=Decimal(0), ge=0, max_digits=14, decimal_places=2)
    refund_amount: Decimal = Field(default=Decimal(0), ge=0, max_digits=14, decimal_places=2)
    commission_base_amount: Decimal = Field(default=Decimal(0), ge=0, max_digits=14, decimal_places=2)
    tax_refund: Decimal = Field(default=Decimal(0), ge=0, max_digits=14, decimal_places=2)
    notes: str | None = Field(default=None, max_length=5000)


class OrderFinancialCreate(OrderFinancialBase):
    """新規作成リクエスト。order_id は URL パスから渡されるため body には含めない。"""
    pass


class OrderFinancialUpdate(BaseModel):
    """部分更新リクエスト。全フィールド optional で受け、router 側で
    指定された列のみ UPDATE する。"""
    revenue_amount: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    purchase_cost: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    purchase_shipping: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    paypal_fee: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    wise_fee: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    exchange_fee: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    outsource_fee: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    packing_fee: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    ad_cost: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    return_fee: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    refund_amount: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    commission_base_amount: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    tax_refund: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    notes: str | None = Field(default=None, max_length=5000)


class OrderFinancialResponse(OrderFinancialBase):
    """レスポンス。DB 列 + 導出列 4 種を一緒に返す。"""
    id: int
    order_id: int
    tenant_id: int
    created_at: datetime
    updated_at: datetime

    # 導出列（Python 側で計算）
    cost_total: Decimal
    gross_profit: Decimal
    gross_profit_rate: Decimal | None
    operating_profit_with_tax_refund: Decimal

    model_config = {"from_attributes": True}

    @model_validator(mode="before")
    @classmethod
    def _fill_derived(cls, values: Any) -> Any:
        """DB row から構築する際に導出列が無い場合は自動計算する。

        既に呼び出し側で計算済みの値が含まれていればそれを優先（テストや
        外部キャッシュのオーバーライド用）。
        """
        if not isinstance(values, dict):
            # asyncpg / sqlalchemy mappings からの変換時は dict 化を試みる
            try:
                values = dict(values)
            except (TypeError, ValueError):
                return values
        derived_keys = (
            "cost_total",
            "gross_profit",
            "gross_profit_rate",
            "operating_profit_with_tax_refund",
        )
        if any(k not in values or values.get(k) is None and k != "gross_profit_rate"
               for k in derived_keys):
            # gross_profit_rate は revenue=0 のとき正常に None になり得るので
            # 「None だから未計算」とは限らない。ただし他 3 列は必ず Decimal が入る前提なので
            # それらが欠けていれば再計算する。
            need_compute = any(k not in values for k in derived_keys)
            if not need_compute:
                # cost_total / gross_profit / operating_profit_with_tax_refund のいずれかが
                # None なら計算する
                need_compute = any(
                    k != "gross_profit_rate" and values.get(k) is None
                    for k in derived_keys
                )
            if need_compute:
                values.update(compute_derived(values))
        return values


class MonthlySummaryResponse(BaseModel):
    """月次集計レスポンス（テナント単位）。

    ADR-021 第 4 節 AC-004 の月次レポート最小実装。staff_id 別の集計は
    Phase 5 で実装する（本 Sprint では受け取って無視 = 全件集計）。
    """
    year: int
    month: int
    count: int
    revenue_total: Decimal
    cost_total: Decimal
    gross_profit_total: Decimal
    gross_profit_rate: Decimal | None  # 合計売上=0 のとき None
    staff_id: int | None = None  # 指定された場合エコーバック（フィルタ自体は stub）
