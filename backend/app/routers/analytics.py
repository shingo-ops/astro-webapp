from __future__ import annotations

"""
レポート・分析API（Phase 3）。

担当者別コンバージョン分析、案件停滞検出。

変更履歴:
  2026-04-17: 初版作成（Phase 3）
  2026-04-27: Phase 1-B-2 Step 5d — customer_id 参照を company_id に置換
"""

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, get_current_tenant, require_permission
from app.database import get_db
from app.models import User

router = APIRouter()


class ConversionEntry(BaseModel):
    user_id: int
    username: str | None
    lead_count: int
    converted_count: int
    conversion_rate: float


class ConversionReport(BaseModel):
    entries: list[ConversionEntry]
    overall_rate: float


class StalledDeal(BaseModel):
    id: int
    title: str
    company_id: int | None
    amount: float | None
    stage: str | None
    status: str
    days_stalled: int
    updated_at: str


class StalledDealsReport(BaseModel):
    threshold_days: int
    total_open: int
    stalled_count: int
    stalled_deals: list[StalledDeal]


class OverdueInvoice(BaseModel):
    id: int
    invoice_number: str | None
    company_id: int
    total_amount: float | None
    currency: str
    due_date: str | None
    days_overdue: int


class OverdueReport(BaseModel):
    count: int
    total_amount: float
    invoices: list[OverdueInvoice]


@router.get(
    "/analytics/conversion",
    response_model=ConversionReport,
    dependencies=[Depends(require_permission("reports.view"))],
)
async def conversion_analysis(
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """担当者別のリード→案件コンバージョン分析"""
    result = await db.execute(text("""
        SELECT
            l.assigned_to AS user_id,
            u.username,
            COUNT(*) AS lead_count,
            COUNT(l.converted_deal_id) AS converted_count
        FROM leads l
        LEFT JOIN public.users u ON u.id = l.assigned_to
        WHERE l.assigned_to IS NOT NULL
        GROUP BY l.assigned_to, u.username
        ORDER BY converted_count DESC
    """))
    rows = result.mappings().all()

    entries = []
    total_leads = 0
    total_converted = 0
    for row in rows:
        lc = row["lead_count"] or 0
        cc = row["converted_count"] or 0
        rate = round((cc / lc * 100), 1) if lc > 0 else 0.0
        entries.append(ConversionEntry(
            user_id=row["user_id"], username=row["username"],
            lead_count=lc, converted_count=cc, conversion_rate=rate,
        ))
        total_leads += lc
        total_converted += cc

    overall = round((total_converted / total_leads * 100), 1) if total_leads > 0 else 0.0
    return ConversionReport(entries=entries, overall_rate=overall)


@router.get(
    "/analytics/stalled-deals",
    response_model=StalledDealsReport,
    dependencies=[Depends(require_permission("reports.view"))],
)
async def stalled_deals_report(
    threshold_days: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """指定日数以上更新のない停滞案件を検出"""
    # 全オープン案件数
    total_result = await db.execute(
        text("SELECT COUNT(*) FROM deals WHERE status NOT IN ('won', 'lost')")
    )
    total_open = total_result.scalar() or 0

    # 停滞案件
    result = await db.execute(
        text("""
            SELECT id, title, company_id, amount, stage, status, updated_at,
                   CAST(julianday('now') - julianday(updated_at) AS INTEGER) AS days_stalled
            FROM deals
            WHERE status NOT IN ('won', 'lost')
              AND (julianday('now') - julianday(updated_at)) >= :threshold
            ORDER BY updated_at ASC
        """),
        {"threshold": threshold_days},
    )
    rows = result.mappings().all()

    stalled = [
        StalledDeal(
            id=row["id"], title=row["title"], company_id=row["company_id"],
            amount=float(row["amount"]) if row["amount"] else None,
            stage=row["stage"], status=row["status"],
            days_stalled=row["days_stalled"] or 0,
            updated_at=str(row["updated_at"]),
        )
        for row in rows
    ]

    return StalledDealsReport(
        threshold_days=threshold_days, total_open=total_open,
        stalled_count=len(stalled), stalled_deals=stalled,
    )


@router.get(
    "/analytics/overdue-invoices",
    response_model=OverdueReport,
    dependencies=[Depends(require_permission("reports.view"))],
)
async def overdue_invoices_report(
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """支払期限超過の未入金請求書一覧"""
    result = await db.execute(text("""
        SELECT id, invoice_number, company_id, total_amount, currency, due_date,
               CAST(julianday('now') - julianday(due_date) AS INTEGER) AS days_overdue
        FROM invoices
        WHERE status IN ('issued', 'overdue')
          AND due_date IS NOT NULL
          AND due_date < date('now')
        ORDER BY due_date ASC
    """))
    rows = result.mappings().all()

    invoices = [
        OverdueInvoice(
            id=row["id"], invoice_number=row["invoice_number"],
            company_id=row["company_id"],
            total_amount=float(row["total_amount"]) if row["total_amount"] else None,
            currency=row["currency"], due_date=str(row["due_date"]),
            days_overdue=row["days_overdue"] or 0,
        )
        for row in rows
    ]
    total = sum(i.total_amount or 0 for i in invoices)

    return OverdueReport(count=len(invoices), total_amount=total, invoices=invoices)
