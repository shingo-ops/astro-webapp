from __future__ import annotations

"""
ダッシュボードAPI。

テナント内の各種KPIをまとめて返す。
Celery定期タスクでキャッシュされたKPIを優先的に返し、
キャッシュミス時のみDBから直接取得する。

変更履歴:
  2026-04-16: Phase 1拡張（リード/チームKPI追加）
  2026-04-17: Phase 3拡張（見積/請求/在庫/パイプライン/コンバージョン/未入金）
"""

import json
import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_tenant, get_current_user, require_permission
from app.cache import get_redis
from app.database import get_db
from app.models import User

logger = logging.getLogger(__name__)
router = APIRouter()

KPI_SCHEMA_VERSION = 3


class DashboardResponse(BaseModel):
    """ダッシュボードKPIレスポンス"""
    schema_version: int = KPI_SCHEMA_VERSION
    # 基本
    company_count: int
    lead_count: int = 0
    lead_open_count: int = 0
    lead_inbound_count: int = 0
    lead_outbound_count: int = 0
    lead_conversion_rate: float = 0.0
    deal_count: int
    deal_open_count: int
    deal_won_count: int
    deal_total_amount: float
    deal_won_amount: float
    order_count: int
    order_pending_count: int
    order_total_amount: float
    team_count: int = 0
    # Phase 2/3 追加
    quote_count: int = 0
    quote_draft_count: int = 0
    quote_approved_amount: float = 0.0
    invoice_count: int = 0
    invoice_unpaid_count: int = 0
    invoice_unpaid_amount: float = 0.0
    product_count: int = 0
    inventory_value: float = 0.0
    supplier_count: int = 0
    po_pending_count: int = 0
    # パイプライン（ステージ別）
    pipeline_by_stage: list[dict] = []
    # 直近データ
    recent_companies: list[dict]
    recent_deals: list[dict]
    recent_leads: list[dict] = []
    recent_quotes: list[dict] = []
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
                if kpis.get("schema_version") != KPI_SCHEMA_VERSION:
                    logger.info("KPIキャッシュのバージョン不一致、DBから再計算")
                    await r.delete(f"dashboard_kpi:{tenant_id}")
                else:
                    kpis["cached"] = True
                    return DashboardResponse(**kpis)
        except Exception:
            logger.warning("ダッシュボードキャッシュ読み取り失敗、DBにフォールバック")

    # 会社数
    result = await db.execute(text("SELECT COUNT(*) AS cnt FROM companies"))
    company_count = result.scalar() or 0

    # リード集計
    result = await db.execute(text("""
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE status NOT IN ('商談中', '既存顧客', '失注', '追客（短期）', '追客（長期）', '対象外')) AS open_count,
            COUNT(*) FILTER (WHERE type = 'Inbound') AS inbound,
            COUNT(*) FILTER (WHERE type = 'Outbound') AS outbound,
            COUNT(*) FILTER (WHERE converted_deal_id IS NOT NULL) AS converted
        FROM leads
    """))
    lead_row = result.mappings().first() or {}
    lead_total = lead_row.get("total", 0) or 0
    lead_converted = lead_row.get("converted", 0) or 0
    conversion_rate = round((lead_converted / lead_total * 100), 1) if lead_total > 0 else 0.0

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

    # パイプライン（ステージ別）
    result = await db.execute(text("""
        SELECT stage,
               COUNT(*) AS count,
               COALESCE(SUM(amount), 0) AS amount,
               COALESCE(SUM(amount * probability / 100.0), 0) AS weighted_amount
        FROM deals
        WHERE status NOT IN ('won', 'lost')
        GROUP BY stage
        ORDER BY
            CASE stage
                WHEN 'open' THEN 1
                WHEN 'negotiating' THEN 2
                WHEN 'proposal' THEN 3
                WHEN 'on_hold' THEN 4
                ELSE 5
            END
    """))
    pipeline = [dict(row) for row in result.mappings().all()]

    # 注文集計
    result = await db.execute(text("""
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE status = 'pending') AS pending_count,
            COALESCE(SUM(total_amount), 0) AS total_amount
        FROM orders
    """))
    order_row = result.mappings().first()

    # 見積集計
    result = await db.execute(text("""
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE status = 'draft') AS draft_count,
            COALESCE(SUM(total_amount) FILTER (WHERE status = 'approved'), 0) AS approved_amount
        FROM quotes
    """))
    quote_row = result.mappings().first() or {}

    # 請求集計
    result = await db.execute(text("""
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE status IN ('issued', 'overdue')) AS unpaid_count,
            COALESCE(SUM(total_amount) FILTER (WHERE status IN ('issued', 'overdue')), 0) AS unpaid_amount
        FROM invoices
    """))
    invoice_row = result.mappings().first() or {}

    # 在庫集計
    result = await db.execute(text("""
        SELECT COUNT(*) AS cnt,
               COALESCE(SUM(quantity * COALESCE(unit_price, 0)), 0) AS value
        FROM products WHERE status = 'active'
    """))
    product_row = result.mappings().first() or {}

    # 仕入先・PO
    result = await db.execute(text("SELECT COUNT(*) FROM suppliers WHERE is_active = TRUE"))
    supplier_count = result.scalar() or 0
    result = await db.execute(text("SELECT COUNT(*) FROM purchase_orders WHERE status IN ('draft', 'ordered')"))
    po_pending = result.scalar() or 0

    # チーム数
    result = await db.execute(text("SELECT COUNT(*) FROM teams WHERE is_active = TRUE"))
    team_count = result.scalar() or 0

    # 直近5件ずつ
    result = await db.execute(text("""
        SELECT
            id,
            company_code,
            COALESCE(billing_display_name, name) AS name,
            name AS company,
            created_at
        FROM companies
        ORDER BY created_at DESC
        LIMIT 5
    """))
    recent_companies = [dict(row) for row in result.mappings().all()]

    result = await db.execute(text("SELECT id, title, amount, status, created_at FROM deals ORDER BY created_at DESC LIMIT 5"))
    recent_deals = [dict(row) for row in result.mappings().all()]

    result = await db.execute(text("SELECT id, customer_name, status, prospect_rank, created_at FROM leads ORDER BY created_at DESC LIMIT 5"))
    recent_leads = [dict(row) for row in result.mappings().all()]

    result = await db.execute(text("SELECT id, quote_code, total_amount, status, created_at FROM quotes ORDER BY created_at DESC LIMIT 5"))
    recent_quotes = [dict(row) for row in result.mappings().all()]

    return DashboardResponse(
        company_count=company_count,
        lead_count=lead_total,
        lead_open_count=lead_row.get("open_count", 0) or 0,
        lead_inbound_count=lead_row.get("inbound", 0) or 0,
        lead_outbound_count=lead_row.get("outbound", 0) or 0,
        lead_conversion_rate=conversion_rate,
        deal_count=deal_row["total"],
        deal_open_count=deal_row["open_count"],
        deal_won_count=deal_row["won_count"],
        deal_total_amount=float(deal_row["total_amount"]),
        deal_won_amount=float(deal_row["won_amount"]),
        order_count=order_row["total"],
        order_pending_count=order_row["pending_count"],
        order_total_amount=float(order_row["total_amount"]),
        team_count=team_count,
        quote_count=quote_row.get("total", 0) or 0,
        quote_draft_count=quote_row.get("draft_count", 0) or 0,
        quote_approved_amount=float(quote_row.get("approved_amount", 0) or 0),
        invoice_count=invoice_row.get("total", 0) or 0,
        invoice_unpaid_count=invoice_row.get("unpaid_count", 0) or 0,
        invoice_unpaid_amount=float(invoice_row.get("unpaid_amount", 0) or 0),
        product_count=product_row.get("cnt", 0) or 0,
        inventory_value=float(product_row.get("value", 0) or 0),
        supplier_count=supplier_count,
        po_pending_count=po_pending,
        pipeline_by_stage=pipeline,
        recent_companies=recent_companies,
        recent_deals=recent_deals,
        recent_leads=recent_leads,
        recent_quotes=recent_quotes,
        cached=False,
    )
