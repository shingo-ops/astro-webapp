"""
backend/app/tasks/verify_meta_subscriptions.py のユニットテスト（ADR-024）。

`refresh_meta_tokens` と同様の同期 Celery タスク。helper 関数をモックして
orchestration（drift 判定 / decrypt 失敗 / Meta API 失敗の audit 記録）を検証する。

実行:
    pytest backend/tests/test_verify_meta_subscriptions.py -v
"""

from __future__ import annotations

import os

# DATABASE_URL を SQLite に固定（refresh_meta_tokens のテストと同パターン）
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.fernet import Fernet


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fernet_env(monkeypatch):
    from app.services import encryption

    encryption.reset_cache()
    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("METADATA_FERNET_KEY", key)
    monkeypatch.setenv("META_APP_ID", "self-app-id-xyz")
    monkeypatch.setenv("META_APP_SECRET", "secret")
    monkeypatch.delenv("META_GRAPH_API_VERSION", raising=False)
    yield
    encryption.reset_cache()


def _make_row(record_id: int = 1, page_id: str = "page-1",
              encrypted_token: bytes = b"x", ig_id: str | None = None) -> dict:
    return {
        "id": record_id,
        "tenant_id": 999,
        "page_id": page_id,
        "page_name": "Test Page",
        "page_access_token_encrypted": encrypted_token,
        "instagram_business_account_id": ig_id,
    }


# ---------------------------------------------------------------------------
# Configuration / Beat schedule
# ---------------------------------------------------------------------------


class TestConfiguration:
    def test_action_constants(self):
        from app.tasks import verify_meta_subscriptions as m

        assert m.ACTION_DECRYPT_FAILED == "meta_subscription_decrypt_failed"
        assert m.ACTION_DRIFT_DETECTED == "meta_subscription_drift_detected"
        assert m.ACTION_CHECK_ERROR == "meta_subscription_check_error"
        assert m.ACTION_VERIFIED == "meta_subscription_verified"

    def test_beat_schedule_registered(self):
        """ADR-024 AC-5: 定期検証ジョブが Celery Beat に登録されている。"""
        from app.celery_app import celery_app

        schedule = celery_app.conf.beat_schedule
        assert "verify-meta-subscriptions" in schedule
        entry = schedule["verify-meta-subscriptions"]
        assert (
            entry["task"]
            == "app.tasks.verify_meta_subscriptions.verify_all_meta_subscriptions"
        )
        cron = entry["schedule"]
        assert 4 in cron.hour
        assert 30 in cron.minute

    def test_module_in_celery_include(self):
        from app.celery_app import celery_app

        assert "app.tasks.verify_meta_subscriptions" in celery_app.conf.include


# ---------------------------------------------------------------------------
# _verify_one_row
# ---------------------------------------------------------------------------


class TestVerifyOneRow:
    def test_verified_when_self_app_in_subscribed_apps(self, fernet_env):
        """ADR-024 AC-2: subscribed_apps に自 App が含まれていれば verified を audit する。"""
        from app.services import encryption
        from app.tasks import verify_meta_subscriptions as m

        token = "plain-token"
        row = _make_row(encrypted_token=encryption.encrypt(token).encode("ascii"))

        captured: list = []

        def _audit(s, schema, *, tenant_id, record_id, action, new_data=None):
            captured.append({"action": action, "new_data": new_data})

        async def _apps(_pid, _tok):
            return [
                {"id": "self-app-id-xyz", "name": "Sales Anchor",
                 "subscribed_fields": ["messages"]},
                {"id": "other", "name": "Other"},
            ]

        with patch.object(m, "_record_audit", _audit), \
             patch("app.services.meta_graph.get_page_subscribed_apps",
                   new=AsyncMock(side_effect=_apps)):
            session = MagicMock()
            result = m._verify_one_row(
                session, "tenant_999", row, self_app_id="self-app-id-xyz"
            )

        assert result["status"] == "verified"
        actions = [a["action"] for a in captured]
        assert m.ACTION_VERIFIED in actions
        assert m.ACTION_DRIFT_DETECTED not in actions
        # commit が呼ばれた
        session.commit.assert_called()

    def test_drift_detected_when_self_app_not_in_subscribed_apps(self, fernet_env):
        """ADR-024 AC-5: 自 App が Meta 側 subscribed_apps に無ければ drift として audit する。"""
        from app.services import encryption
        from app.tasks import verify_meta_subscriptions as m

        token = "plain-token"
        row = _make_row(encrypted_token=encryption.encrypt(token).encode("ascii"))

        captured: list = []

        def _audit(s, schema, *, tenant_id, record_id, action, new_data=None):
            captured.append({"action": action, "new_data": new_data})

        async def _apps(_pid, _tok):
            return [{"id": "someone-else", "name": "Other App"}]

        with patch.object(m, "_record_audit", _audit), \
             patch("app.services.meta_graph.get_page_subscribed_apps",
                   new=AsyncMock(side_effect=_apps)):
            result = m._verify_one_row(
                MagicMock(), "tenant_999", row, self_app_id="self-app-id-xyz"
            )

        assert result["status"] == "drift"
        drift = next(a for a in captured if a["action"] == m.ACTION_DRIFT_DETECTED)
        assert drift["new_data"]["expected_app_id"] == "self-app-id-xyz"
        assert drift["new_data"]["subscribed_app_ids"] == ["someone-else"]

    def test_decrypt_failed_recorded_when_wrong_key(self, fernet_env):
        """別鍵で暗号化されたトークン → 復号失敗 → audit に記録 + Meta API は呼ばない。"""
        from app.tasks import verify_meta_subscriptions as m

        # 別鍵で暗号化
        other = Fernet(Fernet.generate_key())
        bogus = other.encrypt(b"plain").decode("ascii").encode("ascii")
        row = _make_row(encrypted_token=bogus)

        captured: list = []

        def _audit(s, schema, *, tenant_id, record_id, action, new_data=None):
            captured.append({"action": action, "new_data": new_data})

        meta_mock = AsyncMock()
        with patch.object(m, "_record_audit", _audit), \
             patch("app.services.meta_graph.get_page_subscribed_apps", new=meta_mock):
            result = m._verify_one_row(
                MagicMock(), "tenant_999", row, self_app_id="self-app-id-xyz"
            )

        assert result["status"] == "decrypt_failed"
        meta_mock.assert_not_called()
        assert any(a["action"] == m.ACTION_DECRYPT_FAILED for a in captured)

    def test_check_error_recorded_on_meta_api_error(self, fernet_env):
        """Meta API が OAuthException を返したら check_error を audit する。"""
        from app.services import encryption
        from app.services.meta_graph import MetaGraphAPIError
        from app.tasks import verify_meta_subscriptions as m

        token = encryption.encrypt("plain").encode("ascii")
        row = _make_row(encrypted_token=token)

        captured: list = []

        def _audit(s, schema, *, tenant_id, record_id, action, new_data=None):
            captured.append({"action": action, "new_data": new_data})

        with patch.object(m, "_record_audit", _audit), \
             patch("app.services.meta_graph.get_page_subscribed_apps",
                   new=AsyncMock(side_effect=MetaGraphAPIError(
                       "Invalid token", status_code=400,
                       error_type="OAuthException", error_code=190,
                   ))):
            result = m._verify_one_row(
                MagicMock(), "tenant_999", row, self_app_id="self-app-id-xyz"
            )

        assert result["status"] == "check_error"
        assert result["reason"] == "meta_api_error"
        err = next(a for a in captured if a["action"] == m.ACTION_CHECK_ERROR)
        assert err["new_data"]["meta_error"]["error_code"] == 190

    def test_check_error_recorded_on_transport_error(self, fernet_env):
        from app.services import encryption
        from app.services.meta_graph import MetaGraphTransportError
        from app.tasks import verify_meta_subscriptions as m

        token = encryption.encrypt("plain").encode("ascii")
        row = _make_row(encrypted_token=token)

        captured: list = []

        def _audit(s, schema, *, tenant_id, record_id, action, new_data=None):
            captured.append({"action": action, "new_data": new_data})

        with patch.object(m, "_record_audit", _audit), \
             patch("app.services.meta_graph.get_page_subscribed_apps",
                   new=AsyncMock(side_effect=MetaGraphTransportError("network down"))):
            result = m._verify_one_row(
                MagicMock(), "tenant_999", row, self_app_id="self-app-id-xyz"
            )

        assert result["status"] == "check_error"
        assert result["reason"] == "meta_transport_error"
        assert any(a["action"] == m.ACTION_CHECK_ERROR for a in captured)

    def test_handles_memoryview_encrypted_token(self, fernet_env):
        """psycopg2 の bytea が memoryview で来ても復号できる。"""
        from app.services import encryption
        from app.tasks import verify_meta_subscriptions as m

        enc_str = encryption.encrypt("plain")
        mv = memoryview(enc_str.encode("ascii"))
        row = _make_row(encrypted_token=mv)

        async def _apps(_pid, _tok):
            return [{"id": "self-app-id-xyz", "name": "Sales Anchor"}]

        with patch.object(m, "_record_audit"), \
             patch("app.services.meta_graph.get_page_subscribed_apps",
                   new=AsyncMock(side_effect=_apps)):
            result = m._verify_one_row(
                MagicMock(), "tenant_999", row, self_app_id="self-app-id-xyz"
            )
        assert result["status"] == "verified"


# ---------------------------------------------------------------------------
# _process_tenant
# ---------------------------------------------------------------------------


class TestProcessTenant:
    def test_sets_search_path_and_tenant_id(self, fernet_env):
        from app.tasks import verify_meta_subscriptions as m

        session = MagicMock()
        with patch.object(m, "_select_active_configs", return_value=[]):
            summary = m._process_tenant(session, tenant_id=4, self_app_id="x")

        first = session.execute.call_args_list[0].args[0].text
        assert "SET search_path = tenant_004" in first
        second = session.execute.call_args_list[1].args[0].text
        assert "SET app.tenant_id = '4'" in second
        assert summary["scanned"] == 0

    def test_aggregates_per_tenant_summary(self, fernet_env):
        from app.tasks import verify_meta_subscriptions as m

        rows = [
            _make_row(record_id=1, page_id="a"),
            _make_row(record_id=2, page_id="b"),
            _make_row(record_id=3, page_id="c"),
            _make_row(record_id=4, page_id="d"),
        ]
        side_effects = [
            {"status": "verified", "page_id": "a"},
            {"status": "drift", "page_id": "b"},
            {"status": "decrypt_failed", "page_id": "c"},
            {"status": "check_error", "page_id": "d", "reason": "x"},
        ]
        with patch.object(m, "_select_active_configs", return_value=rows), \
             patch.object(m, "_verify_one_row", side_effect=side_effects):
            summary = m._process_tenant(MagicMock(), tenant_id=999, self_app_id="x")

        assert summary["scanned"] == 4
        assert summary["verified"] == 1
        assert summary["drift"] == 1
        assert summary["decrypt_failed"] == 1
        assert summary["check_error"] == 1

    def test_unexpected_exception_does_not_stop_batch(self, fernet_env):
        from app.tasks import verify_meta_subscriptions as m

        rows = [_make_row(record_id=1), _make_row(record_id=2)]
        results = [{"status": "verified", "page_id": "p2"}]

        def _verify_side(session, schema, row, *, self_app_id):
            if row["id"] == 1:
                raise RuntimeError("boom")
            return results.pop(0)

        with patch.object(m, "_select_active_configs", return_value=rows), \
             patch.object(m, "_verify_one_row", side_effect=_verify_side):
            summary = m._process_tenant(MagicMock(), tenant_id=999, self_app_id="x")

        assert summary["scanned"] == 2
        assert summary["verified"] == 1
        assert summary["check_error"] == 1


# ---------------------------------------------------------------------------
# verify_all_meta_subscriptions
# ---------------------------------------------------------------------------


class TestOrchestration:
    def test_iterates_active_tenants_and_aggregates(self, fernet_env):
        from app.tasks import verify_meta_subscriptions as m

        mock_session = MagicMock()
        mock_cm = MagicMock()
        mock_cm.__enter__.return_value = mock_session
        mock_cm.__exit__.return_value = None
        mock_session.execute.return_value = iter([(1,), (2,)])

        with patch.object(m, "_get_sync_engine", return_value=MagicMock()), \
             patch("app.tasks.verify_meta_subscriptions.sessionmaker",
                   return_value=lambda: mock_cm), \
             patch.object(m, "_process_tenant",
                          side_effect=[
                              {"tenant_id": 1, "scanned": 1, "verified": 1,
                               "drift": 0, "decrypt_failed": 0, "check_error": 0,
                               "rows": []},
                              {"tenant_id": 2, "scanned": 2, "verified": 0,
                               "drift": 1, "decrypt_failed": 1, "check_error": 0,
                               "rows": []},
                          ]):
            result = m.verify_all_meta_subscriptions()

        assert result["tenants_processed"] == 2
        assert result["rows_scanned"] == 3
        assert result["verified"] == 1
        assert result["drift"] == 1
        assert result["decrypt_failed"] == 1
        assert result["check_error"] == 0

    def test_continues_when_one_tenant_fails(self, fernet_env):
        from app.tasks import verify_meta_subscriptions as m

        mock_session = MagicMock()
        mock_cm = MagicMock()
        mock_cm.__enter__.return_value = mock_session
        mock_cm.__exit__.return_value = None
        mock_session.execute.return_value = iter([(1,), (2,), (3,)])

        with patch.object(m, "_get_sync_engine", return_value=MagicMock()), \
             patch("app.tasks.verify_meta_subscriptions.sessionmaker",
                   return_value=lambda: mock_cm), \
             patch.object(m, "_process_tenant",
                          side_effect=[
                              {"tenant_id": 1, "scanned": 1, "verified": 1,
                               "drift": 0, "decrypt_failed": 0, "check_error": 0,
                               "rows": []},
                              RuntimeError("tenant 2 broken"),
                              {"tenant_id": 3, "scanned": 1, "verified": 1,
                               "drift": 0, "decrypt_failed": 0, "check_error": 0,
                               "rows": []},
                          ]):
            result = m.verify_all_meta_subscriptions()

        assert result["tenants_processed"] == 2
        assert result["verified"] == 2
