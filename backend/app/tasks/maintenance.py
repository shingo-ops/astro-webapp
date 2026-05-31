"""
メンテナンス定期タスク。

- 監査ログアーカイブ: 90日以上前のログを削除（テナントスキーマ）
- データアクセスイベント削除: 60日以上前を削除（public スキーマ）
- 認証イベント削除: 90日以上前を削除（public スキーマ）

Celery Beat により毎日深夜に実行。
"""

import logging
import os
import time

from celery import shared_task
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "").replace(
    "postgresql+asyncpg://", "postgresql://"
)

# 保持期間（環境変数で上書き可能）
AUDIT_LOG_RETENTION_DAYS = int(os.getenv("AUDIT_LOG_RETENTION_DAYS", "90"))
DATA_ACCESS_RETENTION_DAYS = int(os.getenv("DATA_ACCESS_RETENTION_DAYS", "60"))
AUTH_EVENT_RETENTION_DAYS = int(os.getenv("AUTH_EVENT_RETENTION_DAYS", "90"))

# バッチ削除サイズ（1トランザクションあたりの最大削除件数）
# 5000件 × ~10ms/commit ≒ 50ms ロック → 並行INSERTへの影響を最小化
_BATCH_SIZE = int(os.getenv("RETENTION_BATCH_SIZE", "5000"))

# バッチ間スリープ（ms）: autovacuum・他クエリにCPUを譲る
_BATCH_SLEEP_MS = int(os.getenv("RETENTION_BATCH_SLEEP_MS", "100"))


def _get_sync_engine():
    """同期SQLAlchemyエンジンを返す（テスト時のモック差し替えポイント）。"""
    return create_engine(DATABASE_URL, echo=False)


def _delete_in_batches(table: str, interval: str) -> int:
    """指定テーブルから古いレコードをバッチ分割で安全に削除する。

    - 1バッチ = _BATCH_SIZE 件ずつコミット（ロック保持時間を短縮）
    - バッチ間に _BATCH_SLEEP_MS ms スリープ（autovacuum・他クエリへ処理を譲る）
    - `table` は必ず呼び出し元でハードコード定数から選択すること（SQLi防止）

    根拠（外部事例）:
    - 単発DELETE は100GB規模で最大5時間ロック・900%クエリ劣化（実事例）
    - バッチ1000〜5000件 × スリープで影響を2〜3%に抑制
    - Discord: 保持ポリシー未整備で€800,000 GDPR制裁

    Returns:
        削除した総件数
    """
    engine = _get_sync_engine()
    Session = sessionmaker(engine)
    total_deleted = 0
    batch_num = 0

    while True:
        with Session() as session:
            result = session.execute(
                text(f"""
                    DELETE FROM {table}
                    WHERE id IN (
                        SELECT id FROM {table}
                        WHERE created_at < NOW() - INTERVAL :interval
                        ORDER BY created_at ASC
                        LIMIT :batch_size
                    )
                """),
                {"interval": interval, "batch_size": _BATCH_SIZE},
            )
            session.commit()

        count = result.rowcount if result.rowcount >= 0 else 0
        total_deleted += count
        batch_num += 1

        if count < _BATCH_SIZE:
            # 削除対象がバッチサイズ未満 → 残件なし、終了
            break

        logger.info(
            "%s: バッチ %d 完了 %d件削除（累計 %d件）",
            table, batch_num, count, total_deleted,
        )
        time.sleep(_BATCH_SLEEP_MS / 1000.0)

    return total_deleted


@shared_task(
    name="app.tasks.maintenance.archive_audit_logs",
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
)
def archive_audit_logs():
    """全テナントの90日以上前の監査ログを削除する（テナントスキーマ）。"""
    engine = _get_sync_engine()
    Session = sessionmaker(engine)

    with Session() as session:
        result = session.execute(
            text("SELECT id FROM tenants WHERE is_active = true")
        )
        tenant_ids = [row[0] for row in result]

    total_deleted = 0
    for tenant_id in tenant_ids:
        try:
            with Session() as session:
                schema_name = f"tenant_{tenant_id:03d}"
                session.execute(text(f"SET search_path = {schema_name}, public"))

                result = session.execute(text(f"""
                    DELETE FROM audit_logs
                    WHERE created_at < NOW() - INTERVAL '{AUDIT_LOG_RETENTION_DAYS} days'
                """))
                deleted = result.rowcount if result.rowcount >= 0 else 0
                session.commit()

                if deleted > 0:
                    total_deleted += deleted
                    logger.info(
                        "テナント %d: 監査ログ %d件を削除", tenant_id, deleted
                    )
        except Exception:
            logger.exception("テナント %d の監査ログアーカイブに失敗", tenant_id)

    logger.info("監査ログアーカイブ完了: 合計 %d件 削除", total_deleted)
    return {"deleted": total_deleted, "tenants_processed": len(tenant_ids)}


@shared_task(
    name="app.tasks.maintenance.purge_data_access_events",
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
)
def purge_data_access_events():
    """public.data_access_events の 60日以上前のレコードをバッチ分割で削除する。

    保持期間60日の根拠:
    - GDPR 最低30日 + セキュリティインシデント調査余裕（30日超は珍しくない）
    - SOC2/ISO27001 推奨の最低保持期間を上回る
    """
    interval = f"{DATA_ACCESS_RETENTION_DAYS} days"
    deleted = _delete_in_batches("public.data_access_events", interval)
    logger.info("data_access_events: 合計 %d件 削除（保持期間 %d日）", deleted, DATA_ACCESS_RETENTION_DAYS)
    return {"deleted": deleted}


@shared_task(
    name="app.tasks.maintenance.purge_auth_events",
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
)
def purge_auth_events():
    """public.auth_events の 90日以上前のレコードをバッチ分割で削除する。

    保持期間90日の根拠:
    - SOC2・ISO27001 推奨の認証ログ保持期間
    - auth_events は data_access_events より発生頻度が低い
    """
    interval = f"{AUTH_EVENT_RETENTION_DAYS} days"
    deleted = _delete_in_batches("public.auth_events", interval)
    logger.info("auth_events: 合計 %d件 削除（保持期間 %d日）", deleted, AUTH_EVENT_RETENTION_DAYS)
    return {"deleted": deleted}


@shared_task(
    name="app.tasks.maintenance.purge_expired_inventory_offers",
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
)
def purge_expired_inventory_offers():
    """public.inventory の expires_at を過ぎた仕入元オファーを物理削除する。

    在庫オファーは時間失効モデル (QA 2026-05-30 / ひとしさん):
    - F6 承認時に expires_at = offered_at + 18h を付与（_upsert_inventory_offer）。
    - 本タスクが期限切れ行を削除する。中央在庫 (products.stock_quantity) は触らない。
    - expires_at IS NULL の行（手動の恒久オファー等）は対象外。

    _delete_in_batches は created_at 基準のため、expires_at 基準の本タスクは
    専用ループでバッチ削除する（バッチサイズ・スリープは共通定数を流用）。
    """
    engine = _get_sync_engine()
    Session = sessionmaker(engine)
    total_deleted = 0
    batch_num = 0

    while True:
        with Session() as session:
            result = session.execute(
                text("""
                    DELETE FROM public.inventory
                    WHERE id IN (
                        SELECT id FROM public.inventory
                        WHERE expires_at IS NOT NULL AND expires_at < NOW()
                        ORDER BY expires_at ASC
                        LIMIT :batch_size
                    )
                """),
                {"batch_size": _BATCH_SIZE},
            )
            session.commit()

        count = result.rowcount if result.rowcount >= 0 else 0
        total_deleted += count
        batch_num += 1

        if count < _BATCH_SIZE:
            break

        logger.info(
            "inventory offers: バッチ %d 完了 %d件削除（累計 %d件）",
            batch_num, count, total_deleted,
        )
        time.sleep(_BATCH_SLEEP_MS / 1000.0)

    logger.info("inventory offers: 合計 %d件 失効削除", total_deleted)
    return {"deleted": total_deleted}
