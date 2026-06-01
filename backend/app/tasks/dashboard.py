"""
ダッシュボードKPIキャッシュの定期タスク。

全テナントのKPIを計算してRedisにキャッシュする。
Celery Beatにより10分ごとに実行。

変更履歴:
  2026-04-16: Phase 1対応（lead/team KPI追加、schema_version=2）
  ADR-089 Sprint 3: customers テーブル廃止に伴い companies テーブルを参照するよう改修。
    schema_version=3 に更新。customer_count→company_count、recent_customers→recent_companies。
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

# KPIキャッシュのスキーマバージョン。ルーター側の KPI_SCHEMA_VERSION と揃える。
KPI_SCHEMA_VERSION = 3


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

    # 会社数
    r = session.execute(text("SELECT COUNT(*) FROM companies"))
    company_count = r.scalar() or 0

    # リード集計
    r = session.execute(text("""
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE status NOT IN ('商談中', '既存顧客', '失注', '追客（短期）', '追客（長期）', '対象外')) AS open_count
        FROM leads
    """))
    lead_row = r.mappings().first() or {"total": 0, "open_count": 0}

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

    # チーム数
    r = session.execute(text("SELECT COUNT(*) FROM teams WHERE is_active = TRUE"))
    team_count = r.scalar() or 0

    # 直近の会社（5件）
    r = session.execute(text("""
        SELECT id, company_code, COALESCE(billing_display_name, name) AS name, name AS company, created_at
        FROM companies ORDER BY created_at DESC LIMIT 5
    """))
    recent_companies = [
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

    # 直近のリード（5件）
    r = session.execute(text("""
        SELECT id, customer_name, status, prospect_rank, created_at
        FROM leads ORDER BY created_at DESC LIMIT 5
    """))
    recent_leads = [
        {k: (str(v) if isinstance(v, datetime) else v) for k, v in dict(row).items()}
        for row in r.mappings().all()
    ]

    return {
        "schema_version": KPI_SCHEMA_VERSION,
        "company_count": company_count,
        "lead_count": lead_row["total"],
        "lead_open_count": lead_row["open_count"],
        "deal_count": deal_row["total"],
        "deal_open_count": deal_row["open_count"],
        "deal_won_count": deal_row["won_count"],
        "deal_total_amount": float(deal_row["total_amount"]),
        "deal_won_amount": float(deal_row["won_amount"]),
        "order_count": order_row["total"],
        "order_pending_count": order_row["pending_count"],
        "order_total_amount": float(order_row["total_amount"]),
        "team_count": team_count,
        "recent_companies": recent_companies,
        "recent_deals": recent_deals,
        "recent_leads": recent_leads,
    }


@shared_task(
    name="app.tasks.dashboard.refresh_all_tenant_kpis",
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
)
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


@shared_task(
    name="app.tasks.dashboard.refresh_tenant_kpi",
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
)
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
