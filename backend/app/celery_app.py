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
        "app.tasks.maintenance",
        "app.tasks.reports",
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
}
