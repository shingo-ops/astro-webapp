from __future__ import annotations

"""
ダッシュボードAPI。

テナント内の各種KPIをまとめて返す。
Celery定期タスクでキャッシュされたKPIを優先的に返し、
キャッシュミス時のみDBから直接取得する。

変更履歴:
  2026-04-16: Phase 1拡張（リード/チームKPI追加）
"""

import json
import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, get_current_tenant, require_permission
from app.cache import get_redis
from app.database import get_db
from app.models import User

logger = logging.getLogger(__name__)
router = APIRouter()

# キャッシュKPIのスキーマバージョン。
# Phase 1でlead/team KPIを追加したため v2。構造を変えたらインクリメント。
KPI_SCHEMA_VERSION = 2


class DashboardResponse(BaseModel):
    """ダッシュボードKPIレスポンス"""
    schema_version: int = KPI_SCHEMA_VERSION
    customer_count: int
    lead_count: int = 0
    lead_open_count: int = 0
    deal_count: int
    deal_open_count: int
    deal_won_count: int
    deal_total_amount: float
    deal_won_amount: float
    order_count: int
    order_pending_count: int
    order_total_amount: float
    team_count: int = 0
    recent_customers: list[dict]
    recent_deals: list[dict]
    recent_leads: list[dict] = []
    cached: bool = False


@router.get(
    "/dashboard",
    response_model=DashboardResponse,
    dependencies=[Depends(require_permission("dashboard.view"))],
)
async def get_dashboard(
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """ダッシュボードKPIを取得する（キャッシュ優先）"""

    r = get_redis()
    if r:
        try:
            cached_data = await r.get(f"dashboard_kpi:{tenant_id}")
            if cached_data:
                kpis = json.loads(cached_data)
                # スキーマバージョンが一致しないキャッシュは破棄してDB再計算
                if kpis.get("schema_version") != KPI_SCHEMA_VERSION:
                    logger.info("KPIキャッシュのバージョン不一致、DBから再計算")
                    await r.delete(f"dashboard_kpi:{tenant_id}")
                else:
                    kpis["cached"] = True
                    return DashboardResponse(**kpis)
        except Exception:
            logger.warning("ダッシュボードキャッシュ読み取り失敗、DBにフォールバック")

    # 顧客数
    result = await db.execute(text("SELECT COUNT(*) AS cnt FROM customers"))
    customer_count = result.scalar() or 0

    # リード集計
    result = await db.execute(text("""
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE status NOT IN ('案件化', '失注', '保留')) AS open_count
        FROM leads
    """))
    lead_row = result.mappings().first() or {"total": 0, "open_count": 0}

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

    # チーム数
    result = await db.execute(text("SELECT COUNT(*) FROM teams WHERE is_active = TRUE"))
    team_count = result.scalar() or 0

    # 直近5件
    result = await db.execute(text("""
        SELECT id, name, company, created_at
        FROM customers ORDER BY created_at DESC LIMIT 5
    """))
    recent_customers = [dict(row) for row in result.mappings().all()]

    result = await db.execute(text("""
        SELECT id, title, amount, status, created_at
        FROM deals ORDER BY created_at DESC LIMIT 5
    """))
    recent_deals = [dict(row) for row in result.mappings().all()]

    result = await db.execute(text("""
        SELECT id, customer_name, status, prospect_rank, created_at
        FROM leads ORDER BY created_at DESC LIMIT 5
    """))
    recent_leads = [dict(row) for row in result.mappings().all()]

    return DashboardResponse(
        customer_count=customer_count,
        lead_count=lead_row["total"],
        lead_open_count=lead_row["open_count"],
        deal_count=deal_row["total"],
        deal_open_count=deal_row["open_count"],
        deal_won_count=deal_row["won_count"],
        deal_total_amount=float(deal_row["total_amount"]),
        deal_won_amount=float(deal_row["won_amount"]),
        order_count=order_row["total"],
        order_pending_count=order_row["pending_count"],
        order_total_amount=float(order_row["total_amount"]),
        team_count=team_count,
        recent_customers=recent_customers,
        recent_deals=recent_deals,
        recent_leads=recent_leads,
        cached=False,
    )
