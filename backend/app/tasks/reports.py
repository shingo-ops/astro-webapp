"""
レポートエクスポートタスク。

顧客・商談・注文・リードデータをCSV形式でエクスポートする。
オンデマンドで実行され、結果はRedisに一時保存される。

変更履歴:
  2026-04-16: Phase 1拡張（リードCSV出力＋顧客/商談の拡張カラム対応）
  2026-04-27: Phase 1-B-2 Step 5d — deals/orders/quotes/invoices の JOIN を
    customers → companies / customer_addresses → company_addresses に置換
  2026-04-27 (round 1 review fix): Reviewer Major 2 — `company_addresses` は
    `branch_name` で 1:N（partial UNIQUE は `is_default = TRUE` のみ）。
    multi-branch 顧客（例: Card Galaxy LTD = Essex + Preston）で 1 invoice/deal
    が 2 行に膨らむのを防ぐため、JOIN 条件に `AND ba.is_default = TRUE` を追加。
"""

import csv
import io
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
            SELECT
                c.id,
                c.customer_code,
                COALESCE(c.billing_display_name, ba.name, c.company_name) AS customer_name,
                ba.email AS billing_email,
                ba.telephone AS billing_telephone,
                c.company_name,
                c.primary_contact_channel AS registration_source,
                c.status,
                ba.tax_id AS business_id,
                TRIM(CONCAT_WS(' ', ba.address_line_1, ba.address_line_2, ba.address_line_3, ba.city, ba.state, ba.zip, ba.country_code)) AS billing_address,
                TRIM(CONCAT_WS(' ', da.address_line_1, da.address_line_2, da.address_line_3, da.city, da.state, da.zip)) AS delivery_address,
                da.country_code AS delivery_country,
                c.shipping_note AS notes,
                c.created_at,
                c.updated_at
            FROM customers c
            LEFT JOIN customer_addresses ba ON ba.customer_id = c.id AND ba.address_type = 'billing'
            LEFT JOIN customer_addresses da ON da.customer_id = c.id AND da.address_type = 'delivery'
            ORDER BY c.id
        """,
        "headers": [
            "ID", "顧客コード", "顧客名", "請求先メール", "請求先電話", "会社名",
            "主連絡チャネル", "ステータス", "事業者ID",
            "請求先住所", "配送先住所", "配送先国",
            "発送時メモ", "作成日", "更新日",
        ],
    },
    "leads": {
        "query": """
            SELECT id, lead_code, customer_name, company_name, email, phone,
                   source, type, status, temperature, estimated_scale,
                   customer_type, response_speed, monthly_forecast, prospect_rank,
                   notes, created_at, updated_at
            FROM leads ORDER BY id
        """,
        "headers": [
            "ID", "リードコード", "顧客名", "会社名", "メール", "電話番号",
            "流入元", "タイプ", "ステータス", "温度感", "想定規模",
            "顧客タイプ", "返信速度", "月間見込金額", "見込度",
            "備考", "作成日", "更新日",
        ],
    },
    "deals": {
        "query": """
            SELECT d.id, d.deal_code,
                   COALESCE(co.billing_display_name, ba.name, co.name) AS customer_name,
                   d.title, d.amount,
                   d.currency, d.status, d.stage, d.probability,
                   d.expected_close_date, d.notes, d.created_at, d.updated_at
            FROM deals d
            LEFT JOIN companies co ON d.company_id = co.id
            LEFT JOIN company_addresses ba ON ba.company_id = co.id
                 AND ba.address_type = 'billing' AND ba.is_default = TRUE
            ORDER BY d.id
        """,
        "headers": [
            "ID", "案件コード", "顧客名", "案件名", "金額",
            "通貨", "ステータス", "ステージ", "成約確率(%)",
            "成約予定日", "備考", "作成日", "更新日",
        ],
    },
    "orders": {
        "query": """
            SELECT o.id,
                   COALESCE(co.billing_display_name, ba.name, co.name) AS customer_name,
                   o.order_number, o.total_amount,
                   o.currency, o.status, o.shipping_carrier, o.tracking_number,
                   o.notes, o.created_at, o.updated_at
            FROM orders o
            LEFT JOIN companies co ON o.company_id = co.id
            LEFT JOIN company_addresses ba ON ba.company_id = co.id
                 AND ba.address_type = 'billing' AND ba.is_default = TRUE
            ORDER BY o.id
        """,
        "headers": [
            "ID", "顧客名", "注文番号", "合計金額", "通貨", "ステータス",
            "配送キャリア", "追跡番号", "備考", "作成日", "更新日",
        ],
    },
    "products": {
        "query": """
            SELECT id, product_code, name_ja, name_en, category, mark,
                   status, condition, unit_price, quantity, weight,
                   notes, created_at, updated_at
            FROM products ORDER BY id
        """,
        "headers": [
            "ID", "商品コード", "商品名(日)", "商品名(英)", "カテゴリ", "マーク",
            "ステータス", "状態", "単価", "在庫数", "重量(kg)",
            "備考", "作成日", "更新日",
        ],
    },
    "quotes": {
        "query": """
            SELECT q.id, q.quote_code,
                   COALESCE(co.billing_display_name, ba.name, co.name) AS customer_name,
                   q.currency, q.subtotal, q.shipping_fee, q.total_amount,
                   q.status, q.validity_date, q.notes, q.created_at
            FROM quotes q
            LEFT JOIN companies co ON q.company_id = co.id
            LEFT JOIN company_addresses ba ON ba.company_id = co.id
                 AND ba.address_type = 'billing' AND ba.is_default = TRUE
            ORDER BY q.id
        """,
        "headers": [
            "ID", "見積番号", "顧客名", "通貨", "小計", "送料", "合計",
            "ステータス", "有効期限", "備考", "作成日",
        ],
    },
    "invoices": {
        "query": """
            SELECT i.id, i.invoice_number,
                   COALESCE(co.billing_display_name, ba.name, co.name) AS customer_name,
                   i.currency, i.subtotal, i.shipping_fee, i.total_amount,
                   i.amount_jpy, i.payment_method, i.status,
                   i.issued_at, i.due_date, i.paid_at, i.notes, i.created_at
            FROM invoices i
            LEFT JOIN companies co ON i.company_id = co.id
            LEFT JOIN company_addresses ba ON ba.company_id = co.id
                 AND ba.address_type = 'billing' AND ba.is_default = TRUE
            ORDER BY i.id
        """,
        "headers": [
            "ID", "請求番号", "顧客名", "通貨", "小計", "送料", "合計",
            "JPY換算額", "支払方法", "ステータス",
            "発行日", "支払期限", "入金日", "備考", "作成日",
        ],
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
        _ = result.keys()  # 将来の CSV ヘッダー出力用（現在は rows のみ使用）

    # CSV生成
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(export_config["headers"])
    for row in rows:
        writer.writerow([str(v) if v is not None else "" for v in row])

    csv_content = output.getvalue()

    # Redisに結果を保存（テナントIDをキーに含めてIDOR防止）
    task_id = export_csv.request.id
    cache_key = f"export:{tenant_id}:{task_id}"
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
