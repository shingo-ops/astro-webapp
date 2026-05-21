"""
メール送信 Celery タスク（email_tasks.py）

data_deletion タスクが直接 SMTP 呼び出しを行うと、
SMTP タイムアウト（最大 15 秒）が data_deletion タスクの完了を遅らせる問題がある。
このモジュールはメール送信を非同期 Celery タスクとして分離する。

設計判断:
  - data_deletion.process_data_deletion が完了した後に .delay() で起動
  - SMTP 失敗は data_deletion の成功ステータスに影響しない（冪等性維持）
  - max_retries=3: SMTP 一時障害に備えてリトライ（冪等: 同じメールを再送するだけ）
"""
from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(
    name="app.tasks.email_tasks.send_deletion_completion_email_task",
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
)
def send_deletion_completion_email_task(request_id: str) -> dict:
    """削除完了通知メールを非同期で送信する。

    data_deletion.process_data_deletion が完了後に .delay() で呼び出す。
    SMTP 失敗時は autoretry_for による自動リトライ（最大3回）を行う。
    メール送信はべき等なため自動リトライが安全。

    Args:
        request_id: data_deletion_logs.request_id

    Returns:
        {"status": "sent" | "skipped"} の dict
    """
    from app.services.email_sender import send_deletion_completion_email
    try:
        send_deletion_completion_email(request_id)
        logger.info("[email_tasks] deletion completion email sent: %s", request_id)
        return {"status": "sent", "request_id": request_id}
    except Exception as e:
        logger.warning("[email_tasks] mail send failed for %s: %s", request_id, e)
        raise
