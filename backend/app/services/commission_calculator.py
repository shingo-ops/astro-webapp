from __future__ import annotations

"""
ADR-021 Phase 5 / Sprint 5: 担当者報酬計算ロジック。

OrderFlow Manager の現行 5 ロール × 売上ベースの報酬計算式を Sales Anchor 上で
忠実に再現する。1 受注 × 1 ロール × 1 担当者を入力として、現行式に従って
calculated_amount (Decimal) を 1 つだけ返す純関数として実装する。

現行式の対応表（spec.md より）:
  | ロール   | キャンセル時 | 未割当時 | is_employee 時 | 通常時                               |
  |----------|-------------|----------|----------------|--------------------------------------|
  | 営業     | 0           | 0        | 0              | commission_base_amount × rate (10%)  |
  | 受注     | 0           | 0        | 0              | commission_base_amount × rate (10%)  |
  | 発送     | 0           | 0        | 0              | fixed (200 円)                       |
  | 仕入     | 判定なし    | 0        | 0              | fixed (100 円)                       |
  | トラブル | 判定なし    | 0        | 0              | fixed (500 円)                       |

「キャンセル時 0」が適用されるのは sales / order / ship のみ。
仕入とトラブルはキャンセル後にも工数が発生する業務的事実があるため、
キャンセル判定なしで支払う（OrderFlow と同じ運用）。

精度は Decimal で保持し、最終的に小数 2 桁に quantize する。

変更履歴:
  2026-05-11: 初版（ADR-021 Phase 5 / Sprint 5）
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.schemas.tenant_commission_settings import (
    ALL_ROLES,
    CommissionRate,
    CommissionRatesConfig,
)


# キャンセル判定が適用されるロール（ADR-021 Phase 5 / spec.md の現行式表より）。
# 仕入 / トラブルはキャンセル判定なしのため、ここには含めない。
ROLES_WITH_CANCEL_CHECK: frozenset[str] = frozenset({"sales", "order", "ship"})

# 受注ステータスでキャンセルとみなす値。
# 既存 schemas.order.OrderStatus.cancelled に揃える。
CANCELLED_STATUS: str = "cancelled"


@dataclass(frozen=True)
class StaffSnapshot:
    """計算に必要な staff の最小情報。

    DB から読んだ row の dict を直接渡せるように `from_row` ヘルパを用意する。
    is_employee=True の場合、報酬計算は全ロール 0 円になる。
    """
    id: int
    is_employee: bool

    @classmethod
    def from_row(cls, row: dict[str, Any] | None) -> "StaffSnapshot | None":
        if row is None:
            return None
        return cls(
            id=int(row["id"]),
            is_employee=bool(row.get("is_employee", False)),
        )


@dataclass(frozen=True)
class FinancialSnapshot:
    """計算に必要な order_financials の最小情報。

    rate 型のロールは commission_base_amount × rate.value を支払う。
    """
    commission_base_amount: Decimal

    @classmethod
    def from_row(cls, row: dict[str, Any] | None) -> "FinancialSnapshot | None":
        if row is None:
            return None
        v = row.get("commission_base_amount")
        if v is None:
            return cls(commission_base_amount=Decimal(0))
        if isinstance(v, Decimal):
            return cls(commission_base_amount=v)
        return cls(commission_base_amount=Decimal(str(v)))


def _quantize(amount: Decimal) -> Decimal:
    """円単位の金額として小数 2 桁に丸める（HALF_UP）。

    OrderFlow は税抜運用 + 円整数のため、本来は 0 桁で丸めても整合するが
    将来の通貨拡張に備えて 2 桁を保持する。
    """
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def calculate(
    order_status: str | None,
    financial: FinancialSnapshot | None,
    rates: CommissionRatesConfig,
    role: str,
    staff: StaffSnapshot | None,
) -> Decimal:
    """1 ロール分の報酬額を計算して返す。

    ロジックは spec.md の表通り。
      1) staff が None → 未割当 → 0
      2) staff.is_employee → 社員/役員 → 0
      3) sales/order/ship かつ order_status == 'cancelled' → 0
      4) rate 型 → commission_base_amount × value（financial 未登録は 0）
      5) fixed 型 → value そのまま

    role が 5 ロール外なら ValueError。
    """
    if role not in ALL_ROLES:
        raise ValueError(f"Unknown commission role: {role!r}")

    # 未割当 → 0
    if staff is None:
        return _quantize(Decimal(0))

    # is_employee → 0
    if staff.is_employee:
        return _quantize(Decimal(0))

    # キャンセル時 0 は営業/受注/発送のみ
    if role in ROLES_WITH_CANCEL_CHECK and order_status == CANCELLED_STATUS:
        return _quantize(Decimal(0))

    rate: CommissionRate = getattr(rates, role)
    if rate.type == "rate":
        if financial is None:
            return _quantize(Decimal(0))
        return _quantize(financial.commission_base_amount * rate.value)
    # fixed
    return _quantize(rate.value)


def calculate_all(
    order_status: str | None,
    financial: FinancialSnapshot | None,
    rates: CommissionRatesConfig,
    staff_by_role: dict[str, StaffSnapshot | None],
) -> dict[str, Decimal]:
    """全 5 ロール分の報酬額を一括計算する。

    staff_by_role の欠落ロールは「未割当」として 0 を返す。
    """
    out: dict[str, Decimal] = {}
    for role in ALL_ROLES:
        out[role] = calculate(
            order_status=order_status,
            financial=financial,
            rates=rates,
            role=role,
            staff=staff_by_role.get(role),
        )
    return out
