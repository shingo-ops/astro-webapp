"""
レポートエクスポートタスク。

顧客・商談・注文データをCSV形式でエクスポートする。
オンデマンドで実行され、結果はRedisに一時保存される。
"""

import csv
import io
import json
import logging
import os

from celery import shared_task
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "").replace(
    "postgresql+asyncpg://", "postgresql://"
)
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

# エクスポート結果の保持期間: 1時間
EXPORT_RESULT_TTL = 3600

EXPORT_QUERIES = {
    "customers": {
        "query": """
            SELECT id, name, email, phone, company, notes, created_at, updated_at
            FROM customers ORDER BY id
        """,
        "headers": ["ID", "名前", "メール", "電話番号", "会社名", "備考", "作成日", "更新日"],
    },
    "deals": {
        "query": """
            SELECT d.id, c.name AS customer_name, d.title, d.amount, d.status,
                   d.expected_close_date, d.notes, d.created_at, d.updated_at
            FROM deals d
            LEFT JOIN customers c ON d.customer_id = c.id
            ORDER BY d.id
        """,
        "headers": ["ID", "顧客名", "案件名", "金額", "ステータス", "成約予定日", "備考", "作成日", "更新日"],
    },
    "orders": {
        "query": """
            SELECT o.id, c.name AS customer_name, o.order_number, o.total_amount,
                   o.status, o.notes, o.created_at, o.updated_at
            FROM orders o
            LEFT JOIN customers c ON o.customer_id = c.id
            ORDER BY o.id
        """,
        "headers": ["ID", "顧客名", "注文番号", "合計金額", "ステータス", "備考", "作成日", "更新日"],
    },
}


def _get_sync_engine():
    return create_engine(DATABASE_URL, echo=False)


def _get_redis():
    import redis
    return redis.from_url(REDIS_URL, decode_responses=True)


@shared_task(name="app.tasks.reports.export_csv")
def export_csv(tenant_id: int, report_type: str):
    """
    指定テナントのデータをCSVエクスポートする。

    Args:
        tenant_id: テナントID
        report_type: "customers", "deals", "orders" のいずれか
    """
    if report_type not in EXPORT_QUERIES:
        return {"error": f"不正なレポートタイプ: {report_type}"}

    engine = _get_sync_engine()
    Session = sessionmaker(engine)
    r = _get_redis()
    export_config = EXPORT_QUERIES[report_type]

    with Session() as session:
        schema_name = f"tenant_{tenant_id:03d}"
        session.execute(text(f"SET search_path = {schema_name}, public"))
        session.execute(text(f"SET app.tenant_id = '{tenant_id}'"))

        result = session.execute(text(export_config["query"]))
        rows = result.fetchall()
        columns = result.keys()

    # CSV生成
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(export_config["headers"])
    for row in rows:
        writer.writerow([str(v) if v is not None else "" for v in row])

    csv_content = output.getvalue()

    # Redisに結果を保存
    task_id = export_csv.request.id
    cache_key = f"export:{task_id}"
    r.setex(cache_key, EXPORT_RESULT_TTL, csv_content)

    logger.info(
        "CSVエクスポート完了: tenant=%d, type=%s, rows=%d",
        tenant_id, report_type, len(rows),
    )
    return {
        "status": "completed",
        "report_type": report_type,
        "row_count": len(rows),
        "cache_key": cache_key,
    }
