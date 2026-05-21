"""
メンテナンス定期タスク。

- 監査ログアーカイブ: 90日以上前のログを削除
  Celery Beatにより毎日AM4:00に実行。
"""

import logging
import os

from celery import shared_task
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "").replace(
    "postgresql+asyncpg://", "postgresql://"
)

AUDIT_LOG_RETENTION_DAYS = 90


def _get_sync_engine():
    return create_engine(DATABASE_URL, echo=False)


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
    """全テナントの90日以上前の監査ログを削除する。"""
    engine = _get_sync_engine()
    Session = sessionmaker(engine)

    with Session() as session:
        # アクティブなテナント一覧を取得
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
                deleted = result.rowcount
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
