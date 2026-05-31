from __future__ import annotations

"""
レポート・分析API（Phase 3）。

担当者別コンバージョン分析、案件停滞検出、着地予測、ダッシュボードサマリー。

変更履歴:
  2026-04-17: 初版作成（Phase 3）
  2026-04-27: Phase 1-B-2 Step 5d — customer_id 参照を company_id に置換
  2026-05-25: ダッシュボード強化 — 着地予測・期間別サマリー追加
  2026-05-31: Sprint 2 — 月別受注実績＋着地予想API追加（予実比較グラフ用）
"""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_tenant, get_current_user, require_permission
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
    # NOTE: PostgreSQL の (CURRENT_DATE - timestamp::date) は INTEGER 日数を返す。
    # SQLite 互換の julianday() は使わない（本番は PG のみ、SQLite テストは別件で baseline 故障中）。
    result = await db.execute(
        text("""
            SELECT id, title, company_id, amount, stage, status, updated_at,
                   (CURRENT_DATE - updated_at::date)::INTEGER AS days_stalled
            FROM deals
            WHERE status NOT IN ('won', 'lost')
              AND (CURRENT_DATE - updated_at::date) >= :threshold
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
               (CURRENT_DATE - due_date::date)::INTEGER AS days_overdue
        FROM invoices
        WHERE status IN ('issued', 'overdue')
          AND due_date IS NOT NULL
          AND due_date < CURRENT_DATE
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


# ─────────────────────────────────────────────
# フォローアップリマインド
# ─────────────────────────────────────────────

class FollowUpItem(BaseModel):
    id: int
    customer_name: str
    next_action: str | None
    next_action_date: str | None
    days_overdue: int


class FollowUpReport(BaseModel):
    overdue: list[FollowUpItem]
    due_today: list[FollowUpItem]
    upcoming: list[FollowUpItem]


@router.get(
    "/analytics/followups",
    response_model=FollowUpReport,
    dependencies=[Depends(require_permission("dashboard.view"))],
)
async def followup_reminders(
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """
    フォローアップリマインド。

    - overdue: next_action_date が今日より前
    - due_today: 今日が期限
    - upcoming: 今後7日以内
    """
    today = date.today()
    upcoming_end = today + timedelta(days=7)

    result = await db.execute(
        text("""
            SELECT
                id, customer_name, next_action, next_action_date,
                (CURRENT_DATE - next_action_date)::INTEGER AS days_overdue
            FROM leads
            WHERE next_action_date IS NOT NULL
              AND next_action_date <= :upcoming_end
              AND status NOT IN ('失注', '対象外', '既存顧客')
            ORDER BY next_action_date ASC
        """),
        {"upcoming_end": upcoming_end},
    )
    rows = result.mappings().all()

    overdue, due_today, upcoming = [], [], []
    for row in rows:
        item = FollowUpItem(
            id=row["id"],
            customer_name=row["customer_name"] or "",
            next_action=row["next_action"],
            next_action_date=str(row["next_action_date"]) if row["next_action_date"] else None,
            days_overdue=max(row["days_overdue"] or 0, 0),
        )
        nd = row["next_action_date"]
        if nd < today:
            overdue.append(item)
        elif nd == today:
            due_today.append(item)
        else:
            upcoming.append(item)

    return FollowUpReport(overdue=overdue, due_today=due_today, upcoming=upcoming)


# ─────────────────────────────────────────────
# 着地予測
# ─────────────────────────────────────────────

class ForecastResponse(BaseModel):
    forecast_amount: float
    open_deal_count: int
    won_amount: float
    period_start: str
    period_end: str


@router.get(
    "/analytics/forecast",
    response_model=ForecastResponse,
    dependencies=[Depends(require_permission("dashboard.view"))],
)
async def landing_forecast(
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """
    今月の着地予測。

    計算式: Σ(deal.amount × deal.probability / 100)
    対象: status NOT IN ('won', 'lost') AND expected_close_date の月 = 今月
    """
    today = date.today()
    month_start = today.replace(day=1)
    if today.month == 12:
        month_end = today.replace(year=today.year + 1, month=1, day=1)
    else:
        month_end = today.replace(month=today.month + 1, day=1)

    result = await db.execute(
        text("""
            SELECT
                COALESCE(SUM(amount * probability / 100.0), 0) AS forecast_amount,
                COUNT(*) AS open_deal_count
            FROM deals
            WHERE status NOT IN ('won', 'lost')
              AND expected_close_date >= :start
              AND expected_close_date < :end
        """),
        {"start": month_start, "end": month_end},
    )
    row = result.mappings().first() or {}

    # 今月成約済み売上
    won_result = await db.execute(
        text("""
            SELECT COALESCE(SUM(amount), 0) AS won_amount
            FROM deals
            WHERE status = 'won'
              AND updated_at >= :start AND updated_at < :end
        """),
        {"start": month_start, "end": month_end},
    )
    won_row = won_result.mappings().first() or {}

    return ForecastResponse(
        forecast_amount=float(row.get("forecast_amount", 0) or 0),
        open_deal_count=int(row.get("open_deal_count", 0) or 0),
        won_amount=float(won_row.get("won_amount", 0) or 0),
        period_start=str(month_start),
        period_end=str(month_end),
    )


# ─────────────────────────────────────────────
# 期間別ダッシュボードサマリー
# ─────────────────────────────────────────────

PERIOD_DAYS: dict[str, int] = {
    "1w": 7,
    "1m": 30,
    "3m": 90,
    "6m": 180,
    "12m": 365,
}


class LeadSummary(BaseModel):
    total: int
    converted: int
    excluded: int
    conversion_rate: float


class DealSummary(BaseModel):
    total: int
    active: int
    won: int
    win_rate: float


class OrderSummary(BaseModel):
    total_revenue: float
    order_count: int
    active_count: int


class DashboardSummaryResponse(BaseModel):
    period: str
    start_date: str
    end_date: str
    leads: LeadSummary
    deals: DealSummary
    orders: OrderSummary


@router.get(
    "/analytics/summary",
    response_model=DashboardSummaryResponse,
    dependencies=[Depends(require_permission("dashboard.view"))],
)
async def dashboard_summary(
    period: str = Query(default="1m", description="1w / 1m / 3m / 6m / 12m"),
    tab: str = Query(default="team", description="team または individual"),
    user_id: int | None = Query(default=None, description="individual タブ時のユーザーID"),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """
    期間・タブ別のリード/商談/受注サマリー。

    period: 1w=7日 / 1m=30日 / 3m=90日 / 6m=180日 / 12m=365日
    tab: team=テナント全体 / individual=自分（または指定ユーザー）
    """
    days = PERIOD_DAYS.get(period, 30)
    end_date = date.today()
    start_date = end_date - timedelta(days=days)

    if tab == "individual":
        target_user_id = user_id or current_user.id
        assign_filter_leads = "AND assigned_to = :uid"
        assign_filter_deals = "AND assigned_to = :uid"
        params: dict = {"start": start_date, "end": end_date, "uid": target_user_id}
    else:
        assign_filter_leads = ""
        assign_filter_deals = ""
        params = {"start": start_date, "end": end_date}

    # リード集計
    lead_result = await db.execute(
        text(f"""
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE converted_deal_id IS NOT NULL) AS converted,
                COUNT(*) FILTER (WHERE status = '対象外') AS excluded
            FROM leads
            WHERE created_at::date >= :start AND created_at::date <= :end
            {assign_filter_leads}
        """),
        params,
    )
    lr = lead_result.mappings().first() or {}
    lead_total = int(lr.get("total", 0) or 0)
    lead_converted = int(lr.get("converted", 0) or 0)
    lead_excluded = int(lr.get("excluded", 0) or 0)
    cv_rate = round(lead_converted / lead_total * 100, 1) if lead_total > 0 else 0.0

    # 商談集計
    deal_result = await db.execute(
        text(f"""
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE status NOT IN ('won', 'lost')) AS active,
                COUNT(*) FILTER (WHERE status = 'won') AS won
            FROM deals
            WHERE created_at::date >= :start AND created_at::date <= :end
            {assign_filter_deals}
        """),
        params,
    )
    dr = deal_result.mappings().first() or {}
    deal_total = int(dr.get("total", 0) or 0)
    deal_active = int(dr.get("active", 0) or 0)
    deal_won = int(dr.get("won", 0) or 0)
    win_rate = round(deal_won / deal_total * 100, 1) if deal_total > 0 else 0.0

    # 受注集計（受注はテナント全体のみ）
    order_result = await db.execute(
        text("""
            SELECT
                COALESCE(SUM(total_amount), 0) AS revenue,
                COUNT(*) AS cnt,
                COUNT(*) FILTER (WHERE status IN ('pending', 'processing', 'shipped')) AS active
            FROM orders
            WHERE created_at::date >= :start AND created_at::date <= :end
        """),
        {"start": start_date, "end": end_date},
    )
    orr = order_result.mappings().first() or {}

    return DashboardSummaryResponse(
        period=period,
        start_date=str(start_date),
        end_date=str(end_date),
        leads=LeadSummary(
            total=lead_total,
            converted=lead_converted,
            excluded=lead_excluded,
            conversion_rate=cv_rate,
        ),
        deals=DealSummary(
            total=deal_total,
            active=deal_active,
            won=deal_won,
            win_rate=win_rate,
        ),
        orders=OrderSummary(
            total_revenue=float(orr.get("revenue", 0) or 0),
            order_count=int(orr.get("cnt", 0) or 0),
            active_count=int(orr.get("active", 0) or 0),
        ),
    )


# ─────────────────────────────────────────────
# 月別受注実績＋着地予想（予実比較グラフ用）
# ─────────────────────────────────────────────

class MonthlyRevenueEntry(BaseModel):
    month: str           # "2026-01"
    actual: float        # 確定受注額（orders テーブル）
    forecast: float | None  # 現在月のみ: 着地予想 = won + weighted open deals
    remaining: float     # max(0, forecast - actual)。現在月のみ非ゼロ
    is_current: bool


class MonthlyRevenueResponse(BaseModel):
    entries: list[MonthlyRevenueEntry]


@router.get(
    "/analytics/monthly-revenue",
    response_model=MonthlyRevenueResponse,
    dependencies=[Depends(require_permission("dashboard.view"))],
)
async def monthly_revenue(
    months: int = Query(default=6, ge=3, le=12, description="取得月数（現在月含む）"),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
) -> MonthlyRevenueResponse:
    """
    過去 N ヶ月の月別受注実績と今月の着地予想。予実比較グラフ用。

    - actual: orders.total_amount の月別合計
    - forecast: 今月のみ。成約済み(won) + 進行中商談の加重合計
    - remaining: max(0, forecast - actual)。スタック棒グラフの積み上げ部分に使用
    """
    today = date.today()

    # 取得開始月（N-1 ヶ月前の月初）を計算
    start_year = today.year
    start_month = today.month - (months - 1)
    while start_month <= 0:
        start_month += 12
        start_year -= 1
    range_start = date(start_year, start_month, 1)

    # 翌月の月初（range終端）
    if today.month == 12:
        range_end = date(today.year + 1, 1, 1)
    else:
        range_end = date(today.year, today.month + 1, 1)

    # 月別受注実績（orders テーブル）
    actual_result = await db.execute(
        text("""
            SELECT
                TO_CHAR(DATE_TRUNC('month', created_at), 'YYYY-MM') AS month,
                COALESCE(SUM(total_amount), 0) AS actual
            FROM orders
            WHERE created_at >= :start
              AND created_at < :end
            GROUP BY DATE_TRUNC('month', created_at)
            ORDER BY DATE_TRUNC('month', created_at)
        """),
        {"start": range_start, "end": range_end},
    )
    actual_rows = {row["month"]: float(row["actual"]) for row in actual_result.mappings().all()}

    # 今月の着地予想（deals テーブル）
    current_month_str = today.strftime("%Y-%m")
    month_start = today.replace(day=1)

    # 今月成約済み
    won_result = await db.execute(
        text("""
            SELECT COALESCE(SUM(amount), 0) AS won
            FROM deals
            WHERE status = 'won'
              AND updated_at >= :start AND updated_at < :end
        """),
        {"start": month_start, "end": range_end},
    )
    won_amount = float((won_result.mappings().first() or {}).get("won", 0) or 0)

    # 今月進行中商談の加重合計
    open_result = await db.execute(
        text("""
            SELECT COALESCE(SUM(amount * probability / 100.0), 0) AS weighted
            FROM deals
            WHERE status NOT IN ('won', 'lost')
              AND expected_close_date >= :start
              AND expected_close_date < :end
        """),
        {"start": month_start, "end": range_end},
    )
    weighted_amount = float((open_result.mappings().first() or {}).get("weighted", 0) or 0)
    forecast_total = won_amount + weighted_amount

    # 全月分のエントリを生成（データがない月はゼロ補完）
    entries: list[MonthlyRevenueEntry] = []
    cur_year, cur_month = start_year, start_month
    for _ in range(months):
        month_key = f"{cur_year:04d}-{cur_month:02d}"
        is_current = month_key == current_month_str
        actual = actual_rows.get(month_key, 0.0)
        forecast = forecast_total if is_current else None
        remaining = max(0.0, forecast_total - actual) if is_current else 0.0
        entries.append(MonthlyRevenueEntry(
            month=month_key,
            actual=actual,
            forecast=forecast,
            remaining=remaining,
            is_current=is_current,
        ))
        cur_month += 1
        if cur_month > 12:
            cur_month = 1
            cur_year += 1

    return MonthlyRevenueResponse(entries=entries)
