"""
ダッシュボードKPIキャッシュの定期タスク。

全テナントのKPIを計算してRedisにキャッシュする。
Celery Beatにより10分ごとに実行。
"""

import json
import logging
import os
from datetime import datetime

from celery import shared_task
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger(__name__)

# Celeryワーカーは同期なのでasyncpgではなくpsycopg2を使用
DATABASE_URL = os.getenv("DATABASE_URL", "").replace(
    "postgresql+asyncpg://", "postgresql://"
)
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

DASHBOARD_CACHE_TTL = 660  # 11分（10分の更新間隔 + 1分のバッファ）


def _get_sync_engine():
    """同期DBエンジンを取得する。"""
    return create_engine(DATABASE_URL, echo=False)


def _get_redis():
    """同期Redisクライアントを取得する。"""
    import redis
    return redis.from_url(REDIS_URL, decode_responses=True)


def _compute_kpis(session, tenant_id: int) -> dict:
    """テナントのKPIを計算する。"""
    schema_name = f"tenant_{tenant_id:03d}"
    session.execute(text(f"SET search_path = {schema_name}, public"))
    session.execute(text(f"SET app.tenant_id = '{tenant_id}'"))

    # 顧客数
    r = session.execute(text("SELECT COUNT(*) FROM customers"))
    customer_count = r.scalar() or 0

    # 商談集計
    r = session.execute(text("""
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
    r = session.execute(text("""
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE status = 'pending') AS pending_count,
            COALESCE(SUM(total_amount), 0) AS total_amount
        FROM orders
    """))
    order_row = r.mappings().first()

    # 直近の顧客（5件）
    r = session.execute(text("""
        SELECT id, name, company, created_at
        FROM customers ORDER BY created_at DESC LIMIT 5
    """))
    recent_customers = [
        {k: (str(v) if isinstance(v, datetime) else v) for k, v in dict(row).items()}
        for row in r.mappings().all()
    ]

    # 直近の商談（5件）
    r = session.execute(text("""
        SELECT id, title, amount, status, created_at
        FROM deals ORDER BY created_at DESC LIMIT 5
    """))
    recent_deals = [
        {k: (str(v) if isinstance(v, (datetime, type(None))) else float(v) if hasattr(v, '__float__') and k == 'amount' else v)
         for k, v in dict(row).items()}
        for row in r.mappings().all()
    ]

    return {
        "customer_count": customer_count,
        "deal_count": deal_row["total"],
        "deal_open_count": deal_row["open_count"],
        "deal_won_count": deal_row["won_count"],
        "deal_total_amount": float(deal_row["total_amount"]),
        "deal_won_amount": float(deal_row["won_amount"]),
        "order_count": order_row["total"],
        "order_pending_count": order_row["pending_count"],
        "order_total_amount": float(order_row["total_amount"]),
        "recent_customers": recent_customers,
        "recent_deals": recent_deals,
    }


@shared_task(name="app.tasks.dashboard.refresh_all_tenant_kpis")
def refresh_all_tenant_kpis():
    """全テナントのダッシュボードKPIを更新する。"""
    engine = _get_sync_engine()
    Session = sessionmaker(engine)
    r = _get_redis()

    with Session() as session:
        # アクティブなテナント一覧を取得
        result = session.execute(
            text("SELECT id FROM tenants WHERE is_active = true")
        )
        tenant_ids = [row[0] for row in result]

    updated = 0
    for tenant_id in tenant_ids:
        try:
            with Session() as session:
                kpis = _compute_kpis(session, tenant_id)
                cache_key = f"dashboard_kpi:{tenant_id}"
                r.setex(cache_key, DASHBOARD_CACHE_TTL, json.dumps(kpis))
                updated += 1
        except Exception:
            logger.exception("テナント %d のKPI計算に失敗", tenant_id)

    logger.info("KPIキャッシュ更新完了: %d/%d テナント", updated, len(tenant_ids))
    return {"updated": updated, "total": len(tenant_ids)}


@shared_task(name="app.tasks.dashboard.refresh_tenant_kpi")
def refresh_tenant_kpi(tenant_id: int):
    """特定テナントのダッシュボードKPIを更新する。"""
    engine = _get_sync_engine()
    Session = sessionmaker(engine)
    r = _get_redis()

    with Session() as session:
        kpis = _compute_kpis(session, tenant_id)
        cache_key = f"dashboard_kpi:{tenant_id}"
        r.setex(cache_key, DASHBOARD_CACHE_TTL, json.dumps(kpis))

    return kpis
