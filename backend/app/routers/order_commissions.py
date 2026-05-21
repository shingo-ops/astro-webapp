from __future__ import annotations

"""
受注ごとの担当者別報酬 API（order_commissions）。

ADR-021 Phase 5 / Sprint 5: 担当者報酬計算 MVP
  - POST   /orders/{order_id}/commissions/assign — 役割と担当者を UPSERT
  - DELETE /orders/{order_id}/commissions/{role} — 担当解除（行は残し staff_id を null にし金額を 0 にする）
  - GET    /orders/{order_id}/commissions — 5 ロール分（未登録ロールは null）
  - POST   /orders/{order_id}/commissions/recalc — 全 5 ロール再計算 → DB 反映
  - GET    /commissions/monthly?year=&month= — 月次集計（by_staff / by_role / total）

権限:
  - GET 系: require_permission("orders.view")
  - 書込系: require_permission("orders.update")（spec.md の Generator 判断条項より既存パーミッション流用）

設計:
  受注ごとに 5 ロール分のレコードを縦持ちする（UNIQUE order_id, role）。
  recalc は order の status / order_financials.commission_base_amount /
  tenant_commission_settings.commission_rates を読んで現行式を全ロールに適用し、
  各行の calculated_amount を一括更新する。

変更履歴:
  2026-05-11: 初版（ADR-021 Phase 5 / Sprint 5）
"""

import json
import logging
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import (
    get_current_user,
    get_current_tenant,
    require_permission,
)
from app.database import get_db
from app.models import User
from app.schemas.order_commission import (
    MonthlyByRoleItem,
    MonthlyByStaffItem,
    MonthlyCommissionSummaryResponse,
    OrderCommissionAssignmentRequest,
    OrderCommissionResponse,
    OrderCommissionsBundleResponse,
)
from app.schemas.tenant_commission_settings import (
    ALL_ROLES,
    DEFAULT_COMMISSION_RATES,
    CommissionRatesConfig,
)
from app.services.audit import record_audit_log
from app.services.commission_calculator import (
    FinancialSnapshot,
    StaffSnapshot,
    calculate_all,
)
from app.services.time import _jst_month_range_utc

logger = logging.getLogger(__name__)
router = APIRouter()


_COMMISSION_COLS = """
    oc.id, oc.order_id, oc.tenant_id, oc.role, oc.staff_id,
    oc.calculated_amount, oc.calculated_at, oc.notes,
    oc.created_at, oc.updated_at,
    (s.surname_jp || ' ' || s.given_name_jp) AS staff_name
"""


def _row_to_response(row: dict) -> OrderCommissionResponse:
    return OrderCommissionResponse(
        id=row["id"],
        order_id=row["order_id"],
        tenant_id=row["tenant_id"],
        role=row["role"],
        staff_id=row.get("staff_id"),
        staff_name=row.get("staff_name"),
        calculated_amount=Decimal(str(row.get("calculated_amount") or 0)),
        calculated_at=row.get("calculated_at"),
        notes=row.get("notes"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def _ensure_order_exists(db: AsyncSession, order_id: int) -> dict:
    """受注を取得して dict 化（id / status を含む）。なければ 404。"""
    res = await db.execute(
        text("SELECT id, status FROM orders WHERE id = :id"),
        {"id": order_id},
    )
    row = res.mappings().first()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="注文が見つかりません",
        )
    return dict(row)


async def _fetch_financial(db: AsyncSession, order_id: int) -> FinancialSnapshot | None:
    res = await db.execute(
        text(
            "SELECT commission_base_amount FROM order_financials "
            "WHERE order_id = :order_id"
        ),
        {"order_id": order_id},
    )
    row = res.mappings().first()
    return FinancialSnapshot.from_row(dict(row) if row else None)


async def _fetch_rates(db: AsyncSession, tenant_id: int) -> CommissionRatesConfig:
    """テナント設定が無ければデフォルトを使う（recalc / 取得時の安全網）。"""
    res = await db.execute(
        text(
            "SELECT commission_rates FROM tenant_commission_settings "
            "WHERE tenant_id = :tenant_id"
        ),
        {"tenant_id": tenant_id},
    )
    row = res.mappings().first()
    if not row:
        return DEFAULT_COMMISSION_RATES
    raw = row["commission_rates"]
    if isinstance(raw, str):
        try:
            rates_dict = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("commission_rates JSON parse failed for tenant_id=%s; using defaults", tenant_id)
            return DEFAULT_COMMISSION_RATES
    else:
        rates_dict = raw or {}
    if not rates_dict:
        return DEFAULT_COMMISSION_RATES
    return CommissionRatesConfig.model_validate(rates_dict)


async def _fetch_staff_for_role(
    db: AsyncSession, order_id: int, role: str
) -> StaffSnapshot | None:
    """order_commissions 行に紐づく staff の最小情報を返す。"""
    res = await db.execute(
        text(
            """
            SELECT s.id, s.is_employee
            FROM order_commissions oc
            JOIN staff s ON s.id = oc.staff_id
            WHERE oc.order_id = :order_id AND oc.role = :role
            """
        ),
        {"order_id": order_id, "role": role},
    )
    row = res.mappings().first()
    return StaffSnapshot.from_row(dict(row) if row else None)


async def _fetch_all_staff_for_order(
    db: AsyncSession, order_id: int
) -> dict[str, StaffSnapshot | None]:
    """5 ロール分の staff を一括取得。未割当ロールは None。"""
    res = await db.execute(
        text(
            """
            SELECT oc.role, s.id, s.is_employee
            FROM order_commissions oc
            LEFT JOIN staff s ON s.id = oc.staff_id
            WHERE oc.order_id = :order_id
            """
        ),
        {"order_id": order_id},
    )
    rows = res.mappings().all()
    out: dict[str, StaffSnapshot | None] = {r: None for r in ALL_ROLES}
    for row in rows:
        if row.get("id") is None:
            # 行はあるが staff_id が NULL（担当解除中）
            out[row["role"]] = None
        else:
            out[row["role"]] = StaffSnapshot(
                id=int(row["id"]), is_employee=bool(row.get("is_employee", False))
            )
    return out


async def _get_one_commission_row(
    db: AsyncSession, order_id: int, role: str
) -> dict | None:
    res = await db.execute(
        text(
            f"""
            SELECT {_COMMISSION_COLS}
            FROM order_commissions oc
            LEFT JOIN staff s ON s.id = oc.staff_id
            WHERE oc.order_id = :order_id AND oc.role = :role
            """
        ),
        {"order_id": order_id, "role": role},
    )
    row = res.mappings().first()
    return dict(row) if row else None


async def _list_commissions(db: AsyncSession, order_id: int) -> list[dict]:
    res = await db.execute(
        text(
            f"""
            SELECT {_COMMISSION_COLS}
            FROM order_commissions oc
            LEFT JOIN staff s ON s.id = oc.staff_id
            WHERE oc.order_id = :order_id
            ORDER BY oc.role
            """
        ),
        {"order_id": order_id},
    )
    return [dict(r) for r in res.mappings().all()]


async def _validate_staff(db: AsyncSession, staff_id: int) -> None:
    """staff の存在を確認（テナント境界は search_path で担保）。"""
    res = await db.execute(
        text("SELECT id FROM staff WHERE id = :id"),
        {"id": staff_id},
    )
    if not res.first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="指定の staff_id がこのテナントに存在しません",
        )


@router.post(
    "/orders/{order_id}/commissions/assign",
    response_model=OrderCommissionResponse,
    dependencies=[Depends(require_permission("orders.update"))],
)
async def assign_commission(
    order_id: int,
    data: OrderCommissionAssignmentRequest,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """受注の特定ロールに担当者を割り当てる（UPSERT）。

    既存行があれば staff_id を上書きし、無ければ作成する。
    本エンドポイントは「割当」のみで calculated_amount は触らない。
    再計算は POST /orders/{id}/commissions/recalc で行う。
    """
    await _ensure_order_exists(db, order_id)
    if data.staff_id is not None:
        await _validate_staff(db, data.staff_id)

    existing = await _get_one_commission_row(db, order_id, data.role)
    old_data = dict(existing) if existing else None

    if existing:
        await db.execute(
            text(
                """
                UPDATE order_commissions
                SET staff_id = :staff_id, updated_at = NOW()
                WHERE order_id = :order_id AND role = :role
                """
            ),
            {
                "staff_id": data.staff_id,
                "order_id": order_id,
                "role": data.role,
            },
        )
    else:
        await db.execute(
            text(
                """
                INSERT INTO order_commissions
                    (order_id, tenant_id, role, staff_id, calculated_amount)
                VALUES
                    (:order_id, :tenant_id, :role, :staff_id, 0)
                """
            ),
            {
                "order_id": order_id,
                "tenant_id": tenant_id,
                "role": data.role,
                "staff_id": data.staff_id,
            },
        )

    await record_audit_log(
        db=db,
        tenant_id=tenant_id,
        user_id=current_user.id,
        action="update" if existing else "create",
        table_name="order_commissions",
        record_id=existing["id"] if existing else None,
        old_data=old_data,
        new_data={"role": data.role, "staff_id": data.staff_id},
    )
    await db.commit()

    saved = await _get_one_commission_row(db, order_id, data.role)
    if not saved:
        # 通常は到達しない（直前に UPSERT したため）
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="割当の保存に失敗しました",
        )
    return _row_to_response(saved)


@router.delete(
    "/orders/{order_id}/commissions/{role}",
    response_model=OrderCommissionResponse,
    dependencies=[Depends(require_permission("orders.update"))],
)
async def unassign_commission(
    order_id: int,
    role: str,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """担当解除：staff_id を NULL に戻し、calculated_amount を 0 にして行を残す。

    spec.md の「行は残す」要件に従う（履歴保持のため）。
    """
    if role not in ALL_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"role は {sorted(ALL_ROLES)} のいずれかを指定してください",
        )

    existing = await _get_one_commission_row(db, order_id, role)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="該当ロールの報酬レコードが見つかりません",
        )

    await db.execute(
        text(
            """
            UPDATE order_commissions
            SET staff_id = NULL, calculated_amount = 0, calculated_at = NULL, updated_at = NOW()
            WHERE order_id = :order_id AND role = :role
            """
        ),
        {"order_id": order_id, "role": role},
    )

    await record_audit_log(
        db=db,
        tenant_id=tenant_id,
        user_id=current_user.id,
        action="update",
        table_name="order_commissions",
        record_id=existing["id"],
        old_data=dict(existing),
        new_data={"role": role, "staff_id": None, "calculated_amount": 0},
    )
    await db.commit()

    saved = await _get_one_commission_row(db, order_id, role)
    return _row_to_response(saved)  # type: ignore[arg-type]


@router.get(
    "/orders/{order_id}/commissions",
    response_model=OrderCommissionsBundleResponse,
    dependencies=[Depends(require_permission("orders.view"))],
)
async def list_order_commissions(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """5 ロール分（未登録ロールは null）を返す。"""
    await _ensure_order_exists(db, order_id)
    rows = await _list_commissions(db, order_id)
    by_role: dict[str, OrderCommissionResponse | None] = {r: None for r in ALL_ROLES}
    for row in rows:
        by_role[row["role"]] = _row_to_response(row)
    return OrderCommissionsBundleResponse(order_id=order_id, commissions=by_role)


@router.post(
    "/orders/{order_id}/commissions/recalc",
    response_model=OrderCommissionsBundleResponse,
    dependencies=[Depends(require_permission("orders.update"))],
)
async def recalculate_order_commissions(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """5 ロール全てを現行式で再計算し、order_commissions を一括更新する。

    再計算前後で行数は変わらない（既存行のみ更新）。
    未登録ロール（行なし）は計算結果が 0 でも DB には反映しない（割当時に作成）。
    """
    order_row = await _ensure_order_exists(db, order_id)
    order_status = order_row.get("status")
    rates = await _fetch_rates(db, tenant_id)
    financial = await _fetch_financial(db, order_id)
    staff_by_role = await _fetch_all_staff_for_order(db, order_id)
    amounts = calculate_all(
        order_status=order_status,
        financial=financial,
        rates=rates,
        staff_by_role=staff_by_role,
    )

    now = datetime.now(timezone.utc)
    for role, amount in amounts.items():
        # 既存の行があるロールのみ更新（行が無ければ「未割当でもなく未登録」なので skip）
        await db.execute(
            text(
                """
                UPDATE order_commissions
                SET calculated_amount = :amount,
                    calculated_at = :calc_at,
                    updated_at = NOW()
                WHERE order_id = :order_id AND role = :role
                """
            ),
            {
                "amount": amount,
                "calc_at": now,
                "order_id": order_id,
                "role": role,
            },
        )

    await record_audit_log(
        db=db,
        tenant_id=tenant_id,
        user_id=current_user.id,
        action="update",
        table_name="order_commissions",
        record_id=order_id,
        new_data={
            "recalc": {role: str(amount) for role, amount in amounts.items()},
        },
    )
    await db.commit()

    rows = await _list_commissions(db, order_id)
    by_role: dict[str, OrderCommissionResponse | None] = {r: None for r in ALL_ROLES}
    for row in rows:
        by_role[row["role"]] = _row_to_response(row)
    return OrderCommissionsBundleResponse(order_id=order_id, commissions=by_role)


@router.get(
    "/commissions/monthly",
    response_model=MonthlyCommissionSummaryResponse,
    dependencies=[Depends(require_permission("orders.view"))],
)
async def get_monthly_commissions(
    year: int = Query(..., ge=2000, le=2999, description="集計対象年"),
    month: int = Query(..., ge=1, le=12, description="集計対象月（1-12）"),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """月次集計（by_staff / by_role / total）。

    集計対象は `calculated_at` が指定月内のレコードのみ。再計算未実施の行は
    `calculated_at` が NULL のため対象外（recalc が走った行のみ）。

    ADR-021 J2 fix (2026-05-13):
      期間境界は JST 暦月（month=5 → JST 2026-05-01 00:00 〜 6-01 00:00）。
      UTC 換算で SQL バインドし、TIMESTAMPTZ 比較で評価する。
    """
    start, end = _jst_month_range_utc(year, month)

    # by_staff（NULL は「未割当」としてまとめる）
    by_staff_sql = text(
        """
        SELECT
            oc.staff_id,
            CASE
                WHEN s.id IS NULL THEN NULL
                ELSE (s.surname_jp || ' ' || s.given_name_jp)
            END AS staff_name,
            COALESCE(SUM(oc.calculated_amount), 0) AS total
        FROM order_commissions oc
        LEFT JOIN staff s ON s.id = oc.staff_id
        WHERE oc.calculated_at IS NOT NULL
          AND oc.calculated_at >= :start
          AND oc.calculated_at < :end
        GROUP BY oc.staff_id, staff_name
        ORDER BY oc.staff_id NULLS LAST
        """
    )
    res_staff = await db.execute(by_staff_sql, {"start": start, "end": end})
    by_staff = [
        MonthlyByStaffItem(
            staff_id=r["staff_id"],
            staff_name=r["staff_name"],
            total=Decimal(str(r["total"] or 0)),
        )
        for r in res_staff.mappings().all()
    ]

    # by_role
    by_role_sql = text(
        """
        SELECT
            role,
            COALESCE(SUM(calculated_amount), 0) AS total
        FROM order_commissions
        WHERE calculated_at IS NOT NULL
          AND calculated_at >= :start
          AND calculated_at < :end
        GROUP BY role
        ORDER BY role
        """
    )
    res_role = await db.execute(by_role_sql, {"start": start, "end": end})
    by_role = [
        MonthlyByRoleItem(role=r["role"], total=Decimal(str(r["total"] or 0)))
        for r in res_role.mappings().all()
    ]

    total = sum((item.total for item in by_role), Decimal(0))
    return MonthlyCommissionSummaryResponse(
        year=year,
        month=month,
        by_staff=by_staff,
        by_role=by_role,
        total=total,
    )
