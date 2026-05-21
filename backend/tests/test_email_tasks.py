"""
email_tasks Celery タスクのユニットテスト。

Celery ブローカー不要: email_sender をモックしてタスクロジックをテストする。
"""

from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from unittest.mock import MagicMock, patch

import pytest


class TestSendDeletionCompletionEmailTask:
    """send_deletion_completion_email_task のテスト。"""

    def test_task_name_registered(self):
        """タスク名が正しく登録されていること。"""
        from app.tasks.email_tasks import send_deletion_completion_email_task

        assert (
            send_deletion_completion_email_task.name
            == "app.tasks.email_tasks.send_deletion_completion_email_task"
        )

    def test_task_retry_settings(self):
        """max_retries=3 が設定されていること。"""
        from app.tasks.email_tasks import send_deletion_completion_email_task

        assert send_deletion_completion_email_task.max_retries == 3

    def test_send_success_returns_sent(self):
        """メール送信成功時に {"status": "sent"} を返すこと。"""
        from app.tasks.email_tasks import send_deletion_completion_email_task

        with patch(
            "app.services.email_sender.send_deletion_completion_email",
            return_value=None,
        ):
            result = send_deletion_completion_email_task("req-abc-123")

        assert result["status"] == "sent"
        assert result["request_id"] == "req-abc-123"

    def test_send_failure_reraises(self):
        """メール送信失敗時に例外を再 raise すること（autoretry_for による再試行のため）。"""
        from app.tasks.email_tasks import send_deletion_completion_email_task

        with patch(
            "app.services.email_sender.send_deletion_completion_email",
            side_effect=ConnectionError("SMTP unreachable"),
        ):
            with pytest.raises(ConnectionError):
                send_deletion_completion_email_task("req-fail-456")

    def test_in_celery_include_list(self):
        """email_tasks が celery_app の include リストに含まれていること。"""
        from app.celery_app import celery_app

        assert "app.tasks.email_tasks" in celery_app.conf.include
