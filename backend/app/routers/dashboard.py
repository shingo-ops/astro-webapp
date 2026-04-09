"""
ダッシュボードAPI。

テナント内の各種KPIをまとめて返す。
Celery定期タスクでキャッシュされたKPIを優先的に返し、
キャッシュミス時のみDBから直接取得する。
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, get_current_tenant
from app.cache import get_redis
from app.database import get_db
from app.models import User

logger = logging.getLogger(__name__)
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
    cached: bool = False


@router.get("/dashboard", response_model=DashboardResponse)
async def get_dashboard(
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """ダッシュボードKPIを取得する（キャッシュ優先）"""

    # Redisキャッシュから取得を試みる
    r = get_redis()
    if r:
        try:
            cached_data = await r.get(f"dashboard_kpi:{tenant_id}")
            if cached_data:
                kpis = json.loads(cached_data)
                kpis["cached"] = True
                return DashboardResponse(**kpis)
        except Exception:
            logger.warning("ダッシュボードキャッシュ読み取り失敗、DBにフォールバック")

    # キャッシュミス: DBから直接取得
    # 顧客数
    result = await db.execute(text("SELECT COUNT(*) AS cnt FROM customers"))
    customer_count = result.scalar() or 0

    # 商談集計
    result = await db.execute(text("""
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE status = 'open') AS open_count,
            COUNT(*) FILTER (WHERE status = 'won') AS won_count,
            COALESCE(SUM(amount), 0) AS total_amount,
            COALESCE(SUM(amount) FILTER (WHERE status = 'won'), 0) AS won_amount
        FROM deals
    """))
    deal_row = result.mappings().first()

    # 注文集計
    result = await db.execute(text("""
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE status = 'pending') AS pending_count,
            COALESCE(SUM(total_amount), 0) AS total_amount
        FROM orders
    """))
    order_row = result.mappings().first()

    # 直近の顧客（5件）
    result = await db.execute(text("""
        SELECT id, name, company, created_at
        FROM customers ORDER BY created_at DESC LIMIT 5
    """))
    recent_customers = [dict(row) for row in result.mappings().all()]

    # 直近の商談（5件）
    result = await db.execute(text("""
        SELECT id, title, amount, status, created_at
        FROM deals ORDER BY created_at DESC LIMIT 5
    """))
    recent_deals = [dict(row) for row in result.mappings().all()]

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
        cached=False,
    )
