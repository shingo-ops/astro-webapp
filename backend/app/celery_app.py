"""
Celery アプリケーション定義。

ブローカー: Redis DB1
結果バックエンド: Redis DB2
タイムゾーン: Asia/Tokyo
"""

import os

from celery import Celery
from celery.schedules import crontab

CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/1")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/2")

celery_app = Celery(
    "jarvis_crm",
    broker=CELERY_BROKER_URL,
    backend=CELERY_RESULT_BACKEND,
    include=[
        "app.tasks.dashboard",
        "app.tasks.data_deletion",
        "app.tasks.email_tasks",
        "app.tasks.maintenance",
        "app.tasks.avatar",
        "app.tasks.refresh_meta_tokens",
        "app.tasks.reports",
        "app.tasks.verify_meta_subscriptions",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Tokyo",
    enable_utc=True,
    # タスク結果の有効期限: 24時間
    result_expires=86400,
    # ワーカーがタスクをプリフェッチしすぎないようにする
    worker_prefetch_multiplier=1,
    # タスクの再試行設定
    task_acks_late=True,
    task_reject_on_worker_lost=True,
)

# 定期タスクのスケジュール
celery_app.conf.beat_schedule = {
    # 顧客アバター画像URLを毎日AM2:00 JSTに全テナント分一括更新
    # Meta Platform Terms: 24h超のキャッシュ禁止 → Redis TTL=23h と組み合わせて準拠
    "refresh-all-avatars": {
        "task": "app.tasks.avatar.refresh_all_avatars",
        "schedule": crontab(hour=2, minute=0),
    },
    # ダッシュボードKPIを10分ごとに全テナント分計算
    "refresh-dashboard-kpis": {
        "task": "app.tasks.dashboard.refresh_all_tenant_kpis",
        "schedule": 600.0,  # 10分
    },
    # 監査ログアーカイブを毎日AM4:00に実行
    "archive-old-audit-logs": {
        "task": "app.tasks.maintenance.archive_audit_logs",
        "schedule": crontab(hour=4, minute=0),
    },
    # Meta Page Access Token を毎日AM3:00 JSTにリフレッシュ（Phase 1-E F1-S2）
    "refresh-meta-page-tokens": {
        "task": "app.tasks.refresh_meta_tokens.refresh_all_meta_page_tokens",
        "schedule": crontab(hour=3, minute=0),
    },
    # Meta 接続レコードの整合性（暗号鍵 + Meta 側 subscribed_apps）を毎日AM4:30 JSTに検証（ADR-024）
    "verify-meta-subscriptions": {
        "task": "app.tasks.verify_meta_subscriptions.verify_all_meta_subscriptions",
        "schedule": crontab(hour=4, minute=30),
    },
    # data_access_events の保持ポリシー（60日超を毎日 AM5:00 に削除）
    # バッチ分割削除でロック競合・WAL肥大を防止
    # 根拠: GDPR 30日+ セキュリティインシデント調査余裕 = 60日
    "purge-data-access-events": {
        "task": "app.tasks.maintenance.purge_data_access_events",
        "schedule": crontab(hour=5, minute=0),
    },
    # auth_events の保持ポリシー（90日超を毎日 AM5:30 に削除）
    # 30分ずらすことで data_access_events タスクとの重複実行を防止
    # 根拠: SOC2・ISO27001 推奨の認証ログ保持期間
    "purge-auth-events": {
        "task": "app.tasks.maintenance.purge_auth_events",
        "schedule": crontab(hour=5, minute=30),
    },
}
