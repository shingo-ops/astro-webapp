"""
ダッシュボードAPI。

テナント内の各種KPIをまとめて返す。
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, get_current_tenant
from app.database import get_db
from app.models import User

router = APIRouter()


class DashboardResponse(BaseModel):
    """ダッシュボードKPIレスポンス"""
    customer_count: int
    deal_count: int
    deal_open_count: int
    deal_won_count: int
    deal_total_amount: float
    deal_won_amount: float
    order_count: int
    order_pending_count: int
    order_total_amount: float
    recent_customers: list[dict]
    recent_deals: list[dict]


@router.get("/dashboard", response_model=DashboardResponse)
async def get_dashboard(
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """ダッシュボードKPIを取得する"""

    # 顧客数
    r = await db.execute(text("SELECT COUNT(*) AS cnt FROM customers"))
    customer_count = r.scalar() or 0

    # 商談集計
    r = await db.execute(text("""
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE status = 'open') AS open_count,
            COUNT(*) FILTER (WHERE status = 'won') AS won_count,
            COALESCE(SUM(amount), 0) AS total_amount,
            COALESCE(SUM(amount) FILTER (WHERE status = 'won'), 0) AS won_amount
        FROM deals
    """))
    deal_row = r.mappings().first()

    # 注文集計
    r = await db.execute(text("""
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE status = 'pending') AS pending_count,
            COALESCE(SUM(total_amount), 0) AS total_amount
        FROM orders
    """))
    order_row = r.mappings().first()

    # 直近の顧客（5件）
    r = await db.execute(text("""
        SELECT id, name, company, created_at
        FROM customers ORDER BY created_at DESC LIMIT 5
    """))
    recent_customers = [dict(row) for row in r.mappings().all()]

    # 直近の商談（5件）
    r = await db.execute(text("""
        SELECT id, title, amount, status, created_at
        FROM deals ORDER BY created_at DESC LIMIT 5
    """))
    recent_deals = [dict(row) for row in r.mappings().all()]

    return DashboardResponse(
        customer_count=customer_count,
        deal_count=deal_row["total"],
        deal_open_count=deal_row["open_count"],
        deal_won_count=deal_row["won_count"],
        deal_total_amount=float(deal_row["total_amount"]),
        deal_won_amount=float(deal_row["won_amount"]),
        order_count=order_row["total"],
        order_pending_count=order_row["pending_count"],
        order_total_amount=float(order_row["total_amount"]),
        recent_customers=recent_customers,
        recent_deals=recent_deals,
    )
