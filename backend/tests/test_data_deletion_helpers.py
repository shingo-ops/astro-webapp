"""
app/tasks/data_deletion.py のヘルパー関数と Celery タスクのユニットテスト。

Celery ブローカー不要: DBセッションをモックしてロジックをテストする。

実行:
    pytest backend/tests/test_data_deletion_helpers.py -v
"""

from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from unittest.mock import MagicMock, call, patch

import pytest


class TestGetSyncEngine:
    """_get_sync_engine の互換性テスト。"""

    def test_returns_engine(self):
        """_get_sync_engine は SQLAlchemy エンジンを返す。"""
        from app.tasks.data_deletion import _get_sync_engine, _engine
        assert _get_sync_engine() is _engine


class TestListTenantSchemas:
    """_list_tenant_schemas のテスト。"""

    def test_returns_formatted_schema_names(self):
        """active テナントの id を tenant_NNN 形式に変換する。"""
        from app.tasks.data_deletion import _list_tenant_schemas

        mock_session = MagicMock()
        mock_session.execute.return_value = iter([(1,), (2,), (10,)])

        schemas = _list_tenant_schemas(mock_session)

        assert schemas == ["tenant_001", "tenant_002", "tenant_010"]

    def test_empty_when_no_active_tenants(self):
        """アクティブテナントがなければ空リスト。"""
        from app.tasks.data_deletion import _list_tenant_schemas

        mock_session = MagicMock()
        mock_session.execute.return_value = iter([])

        schemas = _list_tenant_schemas(mock_session)

        assert schemas == []


class TestDeleteMetaMessagesInTenant:
    """_delete_meta_messages_in_tenant のテスト。"""

    def test_returns_0_when_table_not_exist(self):
        """テーブルが存在しない場合は 0 を返す（スキップ）。"""
        from app.tasks.data_deletion import _delete_meta_messages_in_tenant

        mock_session = MagicMock()
        mock_scalar = MagicMock()
        mock_scalar.scalar.return_value = False
        mock_session.execute.return_value = mock_scalar

        result = _delete_meta_messages_in_tenant(mock_session, "tenant_001", "sender123")

        assert result == 0

    def test_returns_rowcount_when_table_exists(self):
        """テーブルが存在する場合は削除行数を返す。"""
        from app.tasks.data_deletion import _delete_meta_messages_in_tenant

        mock_session = MagicMock()

        # 1回目: テーブル存在確認（True）
        # 2回目: DELETE
        mock_exists_result = MagicMock()
        mock_exists_result.scalar.return_value = True
        mock_delete_result = MagicMock()
        mock_delete_result.rowcount = 3
        mock_session.execute.side_effect = [mock_exists_result, mock_delete_result]

        result = _delete_meta_messages_in_tenant(mock_session, "tenant_001", "sender123")

        assert result == 3


class TestProcessDataDeletion:
    """process_data_deletion Celery タスクのテスト。"""

    def test_returns_not_found_when_request_id_missing(self):
        """request_id が見つからない場合は not_found を返す。"""
        from app.tasks.data_deletion import process_data_deletion

        mock_session = MagicMock()
        mock_session_cm = MagicMock()
        mock_session_cm.__enter__.return_value = mock_session
        mock_session_cm.__exit__.return_value = None

        # first() は None を返す（レコードなし）
        mock_result = MagicMock()
        mock_result.first.return_value = None
        mock_session.execute.return_value = mock_result

        with patch("app.tasks.data_deletion._SessionLocal", return_value=mock_session_cm):
            result = process_data_deletion("nonexistent-req-id")

        assert result["status"] == "not_found"
        assert result["request_id"] == "nonexistent-req-id"

    def test_completed_for_non_end_user_type(self):
        """user_type が 'user' (手動対応)は completed で返る。"""
        from app.tasks.data_deletion import process_data_deletion

        mock_session = MagicMock()
        mock_session_cm = MagicMock()
        mock_session_cm.__enter__.return_value = mock_session
        mock_session_cm.__exit__.return_value = None

        # SELECT row: (identifier_value, channel, user_type)
        mock_select_result = MagicMock()
        mock_select_result.first.return_value = ("user@example.com", "email", "user")
        mock_update_result = MagicMock()
        mock_session.execute.side_effect = [
            mock_select_result,   # SELECT
            mock_update_result,   # UPDATE status='processing'
            mock_update_result,   # UPDATE status='completed'
        ]

        with patch("app.tasks.data_deletion._SessionLocal", return_value=mock_session_cm), \
             patch("app.tasks.email_tasks.send_deletion_completion_email_task") as mock_email:
            mock_email.delay = MagicMock()
            result = process_data_deletion("req-user-type")

        assert result["status"] == "completed"
        assert result["deleted_counts"] == {}


    def test_end_user_deletion_completes(self):
        """end_user タイプで全テナントの meta_messages を削除する。"""
        from app.tasks.data_deletion import process_data_deletion

        mock_session = MagicMock()
        mock_session_cm = MagicMock()
        mock_session_cm.__enter__.return_value = mock_session
        mock_session_cm.__exit__.return_value = None

        # Session 1: SELECT (identifier_value, channel, user_type)
        mock_select_result = MagicMock()
        mock_select_result.first.return_value = ("sender123", "messenger", "end_user")
        # Session 2: UPDATE status='processing'
        mock_update1 = MagicMock()
        # Session 2 (end_user deletion): _list_tenant_schemas → [(1,)]
        mock_schemas_result = MagicMock()
        mock_schemas_result.__iter__ = MagicMock(return_value=iter([(1,)]))
        # _delete_meta_messages_in_tenant: exists True, delete 2 rows
        mock_exists = MagicMock()
        mock_exists.scalar.return_value = True
        mock_delete = MagicMock()
        mock_delete.rowcount = 2
        # Session 3: UPDATE status='completed'
        mock_update2 = MagicMock()

        # Sequence of execute() calls across sessions
        call_counter = [0]
        def execute_side_effect(*args, **kwargs):
            call_counter[0] += 1
            n = call_counter[0]
            if n == 1:
                return mock_select_result  # session 1: SELECT row
            elif n == 2:
                return mock_update1         # session 1: UPDATE processing
            elif n == 3:
                return mock_schemas_result  # session 2: SELECT tenants
            elif n == 4:
                return mock_exists          # session 2: table exists check
            elif n == 5:
                return mock_delete          # session 2: DELETE
            else:
                return mock_update2         # session 3: UPDATE completed

        mock_session.execute.side_effect = execute_side_effect

        with patch("app.tasks.data_deletion._SessionLocal", return_value=mock_session_cm), \
             patch("app.tasks.email_tasks.send_deletion_completion_email_task") as mock_email:
            mock_email.delay = MagicMock()
            result = process_data_deletion("req-end-user")

        assert result["status"] == "completed"
        assert result["deleted_counts"].get("tenant_001") == 2

    def test_end_user_deletion_exception_triggers_rollback(self):
        """end_user 削除中に例外が発生した場合は rollback し、status='failed' で返る。"""
        from app.tasks.data_deletion import process_data_deletion

        mock_session = MagicMock()
        mock_session_cm = MagicMock()
        mock_session_cm.__enter__.return_value = mock_session
        mock_session_cm.__exit__.return_value = None

        call_counter = [0]

        def execute_side_effect(*args, **kwargs):
            call_counter[0] += 1
            n = call_counter[0]
            if n == 1:
                mock_select = MagicMock()
                mock_select.first.return_value = ("sender456", "messenger", "end_user")
                return mock_select
            elif n == 2:
                return MagicMock()  # UPDATE processing
            elif n == 3:
                # _list_tenant_schemas raises RuntimeError
                raise RuntimeError("DB connection lost")
            else:
                return MagicMock()  # UPDATE completed/failed

        mock_session.execute.side_effect = execute_side_effect

        with patch("app.tasks.data_deletion._SessionLocal", return_value=mock_session_cm), \
             patch("app.tasks.email_tasks.send_deletion_completion_email_task") as mock_email:
            mock_email.delay = MagicMock()
            result = process_data_deletion("req-end-user-fail")

        assert result["status"] == "failed"
        mock_session.rollback.assert_called_once()

    def test_email_queue_failure_does_not_raise(self):
        """メール送信タスクのキュー失敗は警告ログのみで例外を伝播しない。"""
        from app.tasks.data_deletion import process_data_deletion

        mock_session = MagicMock()
        mock_session_cm = MagicMock()
        mock_session_cm.__enter__.return_value = mock_session
        mock_session_cm.__exit__.return_value = None

        mock_select = MagicMock()
        mock_select.first.return_value = ("user@example.com", "email", "user")
        mock_session.execute.return_value = mock_select

        with patch("app.tasks.data_deletion._SessionLocal", return_value=mock_session_cm), \
             patch("app.tasks.email_tasks.send_deletion_completion_email_task") as mock_email:
            mock_email.delay.side_effect = RuntimeError("Redis queue unavailable")
            result = process_data_deletion("req-email-fail")

        # email failure は致命ではなく、タスク自体は completed を返す
        assert result["status"] == "completed"


class TestMaintenanceGetSyncEngine:
    """maintenance._get_sync_engine のテスト。"""

    def test_returns_engine(self):
        from app.tasks.maintenance import _get_sync_engine
        with patch("app.tasks.maintenance.DATABASE_URL", "sqlite:///:memory:"):
            engine = _get_sync_engine()
        assert engine is not None


class TestReportsGetSyncEngine:
    """reports._get_sync_engine と export_csv のテスト。"""

    def test_returns_engine(self):
        from app.tasks.reports import _get_sync_engine
        with patch("app.tasks.reports.DATABASE_URL", "sqlite:///:memory:"):
            engine = _get_sync_engine()
        assert engine is not None

    def test_export_csv_invalid_report_type(self):
        """不正なレポートタイプは error を返す。"""
        from app.tasks.reports import export_csv

        result = export_csv(tenant_id=1, report_type="invalid_type")
        assert "error" in result
        assert "invalid_type" in result["error"]

    def test_export_queries_keys(self):
        """EXPORT_QUERIES に必要なキーが存在する。"""
        from app.tasks.reports import EXPORT_QUERIES
        assert "customers" in EXPORT_QUERIES
        assert "deals" in EXPORT_QUERIES
        assert "orders" in EXPORT_QUERIES


class TestArchiveAuditLogsTask:
    """maintenance.archive_audit_logs のテスト。"""

    def test_archive_returns_deleted_count(self):
        """ログ削除件数を返す。"""
        from app.tasks.maintenance import archive_audit_logs

        mock_session = MagicMock()
        mock_session_cm = MagicMock()
        mock_session_cm.__enter__.return_value = mock_session
        mock_session_cm.__exit__.return_value = None

        # テナント一覧
        mock_tenants_result = MagicMock()
        mock_tenants_result.__iter__ = MagicMock(return_value=iter([(1,), (2,)]))
        # DELETE 結果
        mock_delete_result = MagicMock()
        mock_delete_result.rowcount = 5

        mock_session.execute.side_effect = [
            mock_tenants_result,    # SELECT tenants
            MagicMock(),            # SET search_path tenant_001
            mock_delete_result,     # DELETE tenant_001
            MagicMock(),            # SET search_path tenant_002
            mock_delete_result,     # DELETE tenant_002
        ]

        with patch("app.tasks.maintenance._get_sync_engine", return_value=MagicMock()), \
             patch("app.tasks.maintenance.sessionmaker", return_value=lambda: mock_session_cm):
            result = archive_audit_logs()

        # 2 テナント × 5 件 = 10 件
        assert result["tenants_processed"] == 2
        assert result["deleted"] == 10

    def test_archive_continues_when_one_tenant_fails(self):
        """1テナントの失敗でも他テナントのアーカイブを継続する。"""
        from app.tasks.maintenance import archive_audit_logs

        call_count = [0]

        def make_cm():
            mock_session = MagicMock()
            mock_session_cm = MagicMock()
            mock_session_cm.__enter__.return_value = mock_session
            mock_session_cm.__exit__.return_value = None
            call_count[0] += 1
            if call_count[0] == 1:
                # テナント一覧取得用セッション
                mock_session.execute.return_value = iter([(1,), (2,)])
            elif call_count[0] == 2:
                # テナント 1 は失敗
                mock_session.execute.side_effect = RuntimeError("DB error")
            else:
                # テナント 2 は成功
                mock_result = MagicMock()
                mock_result.rowcount = 3
                mock_session.execute.side_effect = None
                mock_session.execute.return_value = mock_result
            return mock_session_cm

        with patch("app.tasks.maintenance._get_sync_engine", return_value=MagicMock()), \
             patch("app.tasks.maintenance.sessionmaker", return_value=make_cm):
            result = archive_audit_logs()

        # 失敗しても 2 テナントを試みる
        assert result["tenants_processed"] == 2


class TestDeleteInBatches:
    """maintenance._delete_in_batches のバッチ分割削除ロジックのテスト。"""

    def _make_session_cm(self, rowcount: int):
        """指定 rowcount を返すモックセッションコンテキストマネージャを生成する。"""
        mock_result = MagicMock()
        mock_result.rowcount = rowcount
        mock_session = MagicMock()
        mock_session.execute.return_value = mock_result
        mock_session_cm = MagicMock()
        mock_session_cm.__enter__.return_value = mock_session
        mock_session_cm.__exit__.return_value = None
        return mock_session_cm

    def test_returns_zero_when_nothing_to_delete(self):
        """削除対象がない場合は 0 を返す。"""
        from app.tasks.maintenance import _delete_in_batches

        session_cm = self._make_session_cm(rowcount=0)

        with patch("app.tasks.maintenance._get_sync_engine", return_value=MagicMock()), \
             patch("app.tasks.maintenance.sessionmaker", return_value=lambda _: session_cm):
            result = _delete_in_batches("public.data_access_events", "60 days")

        assert result == 0

    def test_returns_count_when_less_than_batch_size(self):
        """1バッチ未満の削除件数を正しく返す。"""
        from app.tasks.maintenance import _delete_in_batches

        session_cm = self._make_session_cm(rowcount=42)

        with patch("app.tasks.maintenance._get_sync_engine", return_value=MagicMock()), \
             patch("app.tasks.maintenance.sessionmaker", return_value=lambda _: session_cm):
            result = _delete_in_batches("public.data_access_events", "60 days")

        assert result == 42

    def test_loops_when_full_batch_then_stops(self):
        """バッチサイズと同数なら続行し、次が0件で終了する。"""
        from app.tasks.maintenance import _delete_in_batches, _BATCH_SIZE

        # 1回目: バッチサイズ丁度（継続）、2回目: 0件（終了）
        rowcounts = iter([_BATCH_SIZE, 0])

        def make_cm():
            mock_result = MagicMock()
            mock_result.rowcount = next(rowcounts)
            mock_session = MagicMock()
            mock_session.execute.return_value = mock_result
            mock_session_cm = MagicMock()
            mock_session_cm.__enter__.return_value = mock_session
            mock_session_cm.__exit__.return_value = None
            return mock_session_cm

        with patch("app.tasks.maintenance._get_sync_engine", return_value=MagicMock()), \
             patch("app.tasks.maintenance.sessionmaker", return_value=lambda _: make_cm()), \
             patch("app.tasks.maintenance.time") as mock_time:
            result = _delete_in_batches("public.data_access_events", "60 days")

        # 合計 = _BATCH_SIZE + 0
        assert result == _BATCH_SIZE
        # バッチ間スリープが1回呼ばれる
        mock_time.sleep.assert_called_once()


class TestPurgeDataAccessEvents:
    """maintenance.purge_data_access_events のテスト。"""

    def test_returns_deleted_count(self):
        """削除件数を {"deleted": N} 形式で返す。"""
        from app.tasks.maintenance import purge_data_access_events

        with patch("app.tasks.maintenance._delete_in_batches", return_value=123) as mock_batch:
            result = purge_data_access_events()

        assert result == {"deleted": 123}
        # public.data_access_events が対象テーブルであることを確認
        args = mock_batch.call_args[0]
        assert args[0] == "public.data_access_events"

    def test_uses_retention_env_var(self):
        """DATA_ACCESS_RETENTION_DAYS 環境変数が interval に反映される。"""
        from app.tasks.maintenance import purge_data_access_events

        with patch("app.tasks.maintenance._delete_in_batches", return_value=0) as mock_batch, \
             patch("app.tasks.maintenance.DATA_ACCESS_RETENTION_DAYS", 45):
            purge_data_access_events()

        args = mock_batch.call_args[0]
        assert "45" in args[1]


class TestPurgeAuthEvents:
    """maintenance.purge_auth_events のテスト。"""

    def test_returns_deleted_count(self):
        """削除件数を {"deleted": N} 形式で返す。"""
        from app.tasks.maintenance import purge_auth_events

        with patch("app.tasks.maintenance._delete_in_batches", return_value=77) as mock_batch:
            result = purge_auth_events()

        assert result == {"deleted": 77}
        # public.auth_events が対象テーブルであることを確認
        args = mock_batch.call_args[0]
        assert args[0] == "public.auth_events"
