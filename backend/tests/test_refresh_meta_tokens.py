"""
backend/app/tasks/refresh_meta_tokens.py のユニットテスト。

Phase 1-E F1-S2: Page Access Token 60 日リフレッシュ Cron。

テスト戦略:
  - Celery ブローカー / Redis 不要。タスクのロジックを直接呼ぶ。
  - DB は MagicMock（dashboard.py のテストと同じ）。SQL クエリ単位ではなく、
    helper 関数（_select_*, _count_*, _record_audit, _update_token,
    _deactivate_config）をモックして orchestration を検証する。
  - Meta Graph API は `app.services.meta_graph.refresh_page_access_token`
    を `unittest.mock.patch` で差し替え（async 関数 → AsyncMock）。
  - 暗号化は実 Fernet 鍵でラウンドトリップを検証（テスト fixture で鍵を仕込む）。

カバー観点:
  1. SELECT クエリの生成（INTERVAL / page_token_expires_at NULL のケース）
  2. 成功フロー: Meta API 成功 → 暗号化更新 → audit_log 記録
  3. Meta API 失敗（API error）: audit_log 記録、is_active 不変
  4. Meta API 失敗（transport error）: audit_log 記録、is_active 不変
  5. 復号失敗: audit_log 記録、Graph API 呼ばない
  6. 連続 3 日失敗 → is_active=false 切替
  7. テナント分離（複数テナントを処理しても干渉なし）
  8. Celery beat schedule 登録確認

実行:
    pytest backend/tests/test_refresh_meta_tokens.py -v
"""

from __future__ import annotations

import os

# DB は使わないが、import 順で SQLite を保証
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.fernet import Fernet


# -------------------------------------------------------------------------
# Fixtures
# -------------------------------------------------------------------------


@pytest.fixture
def fernet_env(monkeypatch):
    """METADATA_FERNET_KEY と META_APP_ID/SECRET を仕込む。"""
    from app.services import encryption

    encryption.reset_cache()
    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("METADATA_FERNET_KEY", key)
    monkeypatch.setenv("META_APP_ID", "test-app-id")
    monkeypatch.setenv("META_APP_SECRET", "test-secret")
    monkeypatch.delenv("META_GRAPH_API_VERSION", raising=False)
    yield
    encryption.reset_cache()


def _make_row(
    record_id: int = 10,
    tenant_id: int = 999,
    page_id: str = "page-1",
    page_name: str = "Test Page",
    encrypted_token: bytes = b"placeholder",
    page_token_expires_at: datetime | None = None,
    last_token_refreshed_at: datetime | None = None,
    connected_at: datetime | None = None,
) -> dict:
    """tenant_meta_config の SELECT 行を模した dict。"""
    return {
        "id": record_id,
        "tenant_id": tenant_id,
        "page_id": page_id,
        "page_name": page_name,
        "page_access_token_encrypted": encrypted_token,
        "page_token_expires_at": page_token_expires_at,
        "last_token_refreshed_at": last_token_refreshed_at,
        "connected_at": connected_at or datetime.now(timezone.utc),
    }


# -------------------------------------------------------------------------
# 1. Configuration / Beat schedule
# -------------------------------------------------------------------------


class TestConfiguration:
    """設定値・Beat schedule 登録のテスト。"""

    def test_constants_have_expected_values(self):
        from app.tasks import refresh_meta_tokens as m

        assert m.EXPIRES_WITHIN_DAYS == 10
        assert m.LAST_REFRESH_OLDER_THAN_DAYS == 50
        assert m.CONSECUTIVE_FAILURE_THRESHOLD == 3
        assert m.CONSECUTIVE_FAILURE_WINDOW_DAYS == 3
        assert m.ACTION_REFRESHED == "meta_token_refreshed"
        assert m.ACTION_REFRESH_FAILED == "meta_token_refresh_failed"
        assert m.ACTION_DEACTIVATED == "meta_token_auto_deactivated"

    def test_beat_schedule_registered_in_celery_app(self):
        """celery_app.beat_schedule に refresh-meta-page-tokens が登録されている。"""
        from app.celery_app import celery_app

        schedule = celery_app.conf.beat_schedule
        assert "refresh-meta-page-tokens" in schedule
        entry = schedule["refresh-meta-page-tokens"]
        assert entry["task"] == "app.tasks.refresh_meta_tokens.refresh_all_meta_page_tokens"
        # crontab の hour は frozenset で持たれる
        cron = entry["schedule"]
        assert 3 in cron.hour
        assert 0 in cron.minute

    def test_task_module_registered_in_include(self):
        from app.celery_app import celery_app

        assert "app.tasks.refresh_meta_tokens" in celery_app.conf.include


# -------------------------------------------------------------------------
# 2. _refresh_one_row: 成功 / 失敗ロジック
# -------------------------------------------------------------------------


class TestRefreshOneRowSuccess:
    """単一行の成功フローを検証。"""

    def test_happy_path_encrypts_and_updates(self, fernet_env):
        """Meta API 成功 → encrypt して _update_token 呼び出し → audit に refreshed 記録。"""
        from app.services import encryption
        from app.tasks import refresh_meta_tokens as m

        # 既存暗号化トークン
        original_plain = "long-token-original"
        original_enc_str = encryption.encrypt(original_plain)
        original_enc_bytes = original_enc_str.encode("ascii")

        row = _make_row(
            encrypted_token=original_enc_bytes,
            page_token_expires_at=datetime.now(timezone.utc) + timedelta(days=5),
        )

        session = MagicMock()
        captured_update: dict = {}
        captured_audit: list = []

        def _update(s, schema, *, record_id, encrypted_token_bytes, new_expires_at):
            captured_update["record_id"] = record_id
            captured_update["encrypted_token_bytes"] = encrypted_token_bytes
            captured_update["new_expires_at"] = new_expires_at

        def _audit(s, schema, *, tenant_id, record_id, action, new_data=None):
            captured_audit.append({
                "tenant_id": tenant_id, "record_id": record_id,
                "action": action, "new_data": new_data,
            })

        async def _refresh_async(token):
            assert token == original_plain  # 復号成功
            return {
                "access_token": "long-token-refreshed",
                "expires_in": 5183944,
                "token_type": "bearer",
            }

        with patch.object(m, "_update_token", _update), \
             patch.object(m, "_record_audit", _audit), \
             patch.object(m, "_count_recent_failures", return_value=0), \
             patch("app.services.meta_graph.refresh_page_access_token",
                   new=AsyncMock(side_effect=_refresh_async)):
            result = m._refresh_one_row(session, "tenant_999", row)

        assert result["status"] == "refreshed"
        assert result["page_id"] == "page-1"

        # update が呼ばれた
        assert captured_update["record_id"] == 10
        # 新トークンが Fernet 復号できる（= 正しく暗号化されている）
        new_enc_str = captured_update["encrypted_token_bytes"].decode("ascii")
        decrypted = encryption.decrypt(new_enc_str)
        assert decrypted == "long-token-refreshed"
        # expires_at が future（5183944 秒 ≒ 60 日後）
        assert captured_update["new_expires_at"] is not None
        diff = captured_update["new_expires_at"] - datetime.now(timezone.utc)
        assert diff > timedelta(days=59)

        # audit が refreshed で記録されている
        assert any(a["action"] == m.ACTION_REFRESHED for a in captured_audit)
        # commit が呼ばれた
        session.commit.assert_called()

    def test_handles_memoryview_encrypted_token(self, fernet_env):
        """psycopg2 の bytea が memoryview で来ても正しく復号できる。"""
        from app.services import encryption
        from app.tasks import refresh_meta_tokens as m

        original_enc_str = encryption.encrypt("plain-x")
        mv = memoryview(original_enc_str.encode("ascii"))

        row = _make_row(encrypted_token=mv)

        async def _refresh_async(token):
            assert token == "plain-x"
            return {"access_token": "new-token", "expires_in": 100, "token_type": "bearer"}

        session = MagicMock()
        with patch.object(m, "_update_token"), \
             patch.object(m, "_record_audit"), \
             patch.object(m, "_count_recent_failures", return_value=0), \
             patch("app.services.meta_graph.refresh_page_access_token",
                   new=AsyncMock(side_effect=_refresh_async)):
            result = m._refresh_one_row(session, "tenant_999", row)
        assert result["status"] == "refreshed"


class TestRefreshOneRowFailure:
    """失敗フローのロジック検証。"""

    def test_meta_api_error_audits_and_does_not_deactivate_below_threshold(self, fernet_env):
        from app.services import encryption
        from app.services.meta_graph import MetaGraphAPIError
        from app.tasks import refresh_meta_tokens as m

        original_enc = encryption.encrypt("plain").encode("ascii")
        row = _make_row(encrypted_token=original_enc)

        captured_audit: list = []

        def _audit(s, schema, *, tenant_id, record_id, action, new_data=None):
            captured_audit.append({"action": action, "new_data": new_data})

        # 1 回失敗（連続失敗カウント = 1 → 閾値 3 未満）
        with patch.object(m, "_record_audit", _audit), \
             patch.object(m, "_count_recent_failures", return_value=1), \
             patch.object(m, "_deactivate_config") as mock_deactivate, \
             patch.object(m, "_update_token") as mock_update, \
             patch("app.services.meta_graph.refresh_page_access_token",
                   new=AsyncMock(side_effect=MetaGraphAPIError(
                       "Invalid token",
                       status_code=400, error_type="OAuthException",
                       error_code=190,
                   ))):
            session = MagicMock()
            result = m._refresh_one_row(session, "tenant_999", row)

        assert result["status"] == "failed"
        assert result["reason"] == "meta_api_error"
        # is_active は変更しない
        mock_deactivate.assert_not_called()
        mock_update.assert_not_called()
        # 失敗の audit は記録された
        assert any(a["action"] == m.ACTION_REFRESH_FAILED for a in captured_audit)
        # meta_error が dict で記録されている
        failed_entry = next(a for a in captured_audit if a["action"] == m.ACTION_REFRESH_FAILED)
        assert failed_entry["new_data"]["reason"] == "meta_api_error"
        assert failed_entry["new_data"]["meta_error"]["error_code"] == 190

    def test_transport_error_audits_and_skips(self, fernet_env):
        from app.services import encryption
        from app.services.meta_graph import MetaGraphTransportError
        from app.tasks import refresh_meta_tokens as m

        original_enc = encryption.encrypt("plain").encode("ascii")
        row = _make_row(encrypted_token=original_enc)

        captured_audit: list = []

        def _audit(s, schema, *, tenant_id, record_id, action, new_data=None):
            captured_audit.append({"action": action, "new_data": new_data})

        with patch.object(m, "_record_audit", _audit), \
             patch.object(m, "_count_recent_failures", return_value=1), \
             patch.object(m, "_deactivate_config") as mock_deactivate, \
             patch("app.services.meta_graph.refresh_page_access_token",
                   new=AsyncMock(side_effect=MetaGraphTransportError("network down"))):
            session = MagicMock()
            result = m._refresh_one_row(session, "tenant_999", row)

        assert result["status"] == "failed"
        assert result["reason"] == "meta_transport_error"
        mock_deactivate.assert_not_called()

    def test_decrypt_failure_audits_without_calling_meta(self, fernet_env):
        """暗号化トークンが現在の鍵で復号できない場合、Meta API は呼ばない。"""
        from app.tasks import refresh_meta_tokens as m

        # わざと別鍵で暗号化したものを渡す
        other_key = Fernet.generate_key()
        other_enc = Fernet(other_key).encrypt(b"plain").decode("ascii")

        row = _make_row(encrypted_token=other_enc.encode("ascii"))

        captured_audit: list = []

        def _audit(s, schema, *, tenant_id, record_id, action, new_data=None):
            captured_audit.append({"action": action, "new_data": new_data})

        meta_mock = AsyncMock()
        with patch.object(m, "_record_audit", _audit), \
             patch.object(m, "_update_token") as mock_update, \
             patch("app.services.meta_graph.refresh_page_access_token", new=meta_mock):
            session = MagicMock()
            result = m._refresh_one_row(session, "tenant_999", row)

        assert result["status"] == "failed"
        assert result["reason"] == "decrypt_failed"
        meta_mock.assert_not_called()
        mock_update.assert_not_called()
        assert any(a["new_data"]["reason"] == "decrypt_failed" for a in captured_audit)

    def test_three_consecutive_failures_deactivates(self, fernet_env):
        """連続 3 回失敗 → is_active=false に倒し、deactivated audit を記録。"""
        from app.services import encryption
        from app.services.meta_graph import MetaGraphAPIError
        from app.tasks import refresh_meta_tokens as m

        original_enc = encryption.encrypt("plain").encode("ascii")
        row = _make_row(record_id=42, encrypted_token=original_enc)

        captured_audit: list = []

        def _audit(s, schema, *, tenant_id, record_id, action, new_data=None):
            captured_audit.append({"action": action, "record_id": record_id,
                                    "new_data": new_data})

        # _count_recent_failures が CONSECUTIVE_FAILURE_THRESHOLD を返す
        with patch.object(m, "_record_audit", _audit), \
             patch.object(m, "_count_recent_failures",
                          return_value=m.CONSECUTIVE_FAILURE_THRESHOLD), \
             patch.object(m, "_deactivate_config") as mock_deactivate, \
             patch("app.services.meta_graph.refresh_page_access_token",
                   new=AsyncMock(side_effect=MetaGraphAPIError(
                       "Token expired", status_code=400,
                       error_type="OAuthException", error_code=190,
                   ))):
            session = MagicMock()
            result = m._refresh_one_row(session, "tenant_999", row)

        assert result["status"] == "deactivated"
        assert result["consecutive_failure_count"] == m.CONSECUTIVE_FAILURE_THRESHOLD
        mock_deactivate.assert_called_once_with(session, "tenant_999", 42)
        # deactivated audit が記録された
        assert any(a["action"] == m.ACTION_DEACTIVATED for a in captured_audit)

    def test_unexpected_token_type_audits_failed(self, fernet_env):
        """encrypted カラムが想定外型（int 等）なら復号せず failed audit。"""
        from app.tasks import refresh_meta_tokens as m

        row = _make_row(encrypted_token=12345)  # 想定外

        captured_audit: list = []

        def _audit(s, schema, *, tenant_id, record_id, action, new_data=None):
            captured_audit.append({"action": action, "new_data": new_data})

        with patch.object(m, "_record_audit", _audit), \
             patch("app.services.meta_graph.refresh_page_access_token",
                   new=AsyncMock()) as meta_mock:
            session = MagicMock()
            result = m._refresh_one_row(session, "tenant_999", row)

        assert result["status"] == "failed"
        assert result["reason"] == "encrypted_token_unexpected_type"
        meta_mock.assert_not_called()


# -------------------------------------------------------------------------
# 3. _process_tenant: テナント分離
# -------------------------------------------------------------------------


class TestProcessTenantIsolation:
    """テナント別 schema search_path の設定 / テナント間の独立性検証。"""

    def test_sets_search_path_and_tenant_id(self, fernet_env):
        from app.tasks import refresh_meta_tokens as m

        session = MagicMock()
        session.execute.return_value.mappings.return_value.all.return_value = []

        with patch.object(m, "_select_refresh_targets", return_value=[]):
            summary = m._process_tenant(session, tenant_id=4)

        # 最初の 2 回の execute() は SET search_path と SET app.tenant_id
        first_call = session.execute.call_args_list[0].args[0].text
        assert "SET search_path = tenant_004" in first_call
        second_call = session.execute.call_args_list[1].args[0].text
        assert "SET app.tenant_id = '4'" in second_call

        assert summary["tenant_id"] == 4
        assert summary["scanned"] == 0

    def test_aggregates_results_per_tenant(self, fernet_env):
        from app.tasks import refresh_meta_tokens as m

        rows = [
            _make_row(record_id=1, page_id="p1"),
            _make_row(record_id=2, page_id="p2"),
            _make_row(record_id=3, page_id="p3"),
        ]
        # 1 件成功、1 件失敗、1 件 deactivated
        side_effects = [
            {"status": "refreshed", "page_id": "p1"},
            {"status": "failed", "page_id": "p2", "reason": "x"},
            {"status": "deactivated", "page_id": "p3", "consecutive_failure_count": 3},
        ]

        with patch.object(m, "_select_refresh_targets", return_value=rows), \
             patch.object(m, "_refresh_one_row", side_effect=side_effects):
            summary = m._process_tenant(MagicMock(), tenant_id=999)

        assert summary["scanned"] == 3
        assert summary["refreshed"] == 1
        assert summary["failed"] == 1
        assert summary["deactivated"] == 1

    def test_unexpected_exception_in_one_row_does_not_stop_batch(self, fernet_env):
        """1 行で想定外 Exception が出ても残り行を処理する。"""
        from app.tasks import refresh_meta_tokens as m

        rows = [_make_row(record_id=1), _make_row(record_id=2)]

        # 最初は throw、次は成功
        results = [{"status": "refreshed", "page_id": "p2"}]

        def _refresh_side(session, schema, row):
            if row["id"] == 1:
                raise RuntimeError("boom")
            return results.pop(0)

        with patch.object(m, "_select_refresh_targets", return_value=rows), \
             patch.object(m, "_refresh_one_row", side_effect=_refresh_side):
            summary = m._process_tenant(MagicMock(), tenant_id=999)

        assert summary["scanned"] == 2
        # 1 件失敗（unexpected）+ 1 件成功
        assert summary["refreshed"] == 1
        assert summary["failed"] == 1


# -------------------------------------------------------------------------
# 4. refresh_all_meta_page_tokens: 全体オーケストレーション
# -------------------------------------------------------------------------


class TestRefreshAllOrchestration:
    """全テナントを順に処理するエントリポイントのテスト。"""

    def test_iterates_active_tenants_only(self, fernet_env):
        """tenants.is_active=true のみを対象に列挙する SQL を発行する。"""
        from app.tasks import refresh_meta_tokens as m

        mock_engine = MagicMock()
        mock_session_cm = MagicMock()
        mock_session = MagicMock()
        mock_session_cm.__enter__.return_value = mock_session
        mock_session_cm.__exit__.return_value = None

        # tenants 一覧
        mock_session.execute.return_value = iter([(1,), (2,)])

        with patch.object(m, "_get_sync_engine", return_value=mock_engine), \
             patch("app.tasks.refresh_meta_tokens.sessionmaker",
                   return_value=lambda: mock_session_cm), \
             patch.object(m, "_process_tenant",
                          side_effect=[
                              {"tenant_id": 1, "scanned": 2, "refreshed": 2,
                               "failed": 0, "deactivated": 0, "rows": []},
                              {"tenant_id": 2, "scanned": 1, "refreshed": 0,
                               "failed": 1, "deactivated": 0, "rows": []},
                          ]):
            result = m.refresh_all_meta_page_tokens()

        assert result["tenants_processed"] == 2
        assert result["rows_scanned"] == 3
        assert result["refreshed"] == 2
        assert result["failed"] == 1
        assert result["deactivated"] == 0
        # tenants の SELECT クエリが 1 回発行されている
        select_sql = mock_session.execute.call_args_list[0].args[0].text
        assert "FROM tenants" in select_sql
        assert "is_active = true" in select_sql

    def test_continues_when_one_tenant_fails(self, fernet_env):
        """1 テナントの処理が例外でも他テナントを止めない。"""
        from app.tasks import refresh_meta_tokens as m

        mock_session = MagicMock()
        mock_session_cm = MagicMock()
        mock_session_cm.__enter__.return_value = mock_session
        mock_session_cm.__exit__.return_value = None
        mock_session.execute.return_value = iter([(1,), (2,), (3,)])

        with patch.object(m, "_get_sync_engine", return_value=MagicMock()), \
             patch("app.tasks.refresh_meta_tokens.sessionmaker",
                   return_value=lambda: mock_session_cm), \
             patch.object(m, "_process_tenant",
                          side_effect=[
                              {"tenant_id": 1, "scanned": 1, "refreshed": 1,
                               "failed": 0, "deactivated": 0, "rows": []},
                              RuntimeError("tenant 2 broken"),
                              {"tenant_id": 3, "scanned": 1, "refreshed": 1,
                               "failed": 0, "deactivated": 0, "rows": []},
                          ]):
            result = m.refresh_all_meta_page_tokens()

        # 2 件分（tenant 1, 3）が処理された
        assert result["tenants_processed"] == 2
        assert result["refreshed"] == 2


# -------------------------------------------------------------------------
# 5. SQL 文字列の構造検証（INTERVAL / NULL 条件）
# -------------------------------------------------------------------------


class TestSelectRefreshTargetsSQL:
    """_select_refresh_targets が発行する SQL の構造を検証。"""

    def test_sql_includes_expected_conditions(self, fernet_env):
        from app.tasks import refresh_meta_tokens as m

        captured_sql: list = []

        def _execute(stmt, *args, **kwargs):
            # text() オブジェクトから .text 属性で文字列取得
            captured_sql.append(getattr(stmt, "text", str(stmt)))
            ret = MagicMock()
            ret.mappings.return_value.all.return_value = []
            return ret

        session = MagicMock()
        session.execute.side_effect = _execute

        m._select_refresh_targets(session, "tenant_999")

        assert len(captured_sql) == 1
        sql = captured_sql[0]
        # is_active=TRUE 条件
        assert "is_active = TRUE" in sql
        # 期限切れ間近 (10 日)
        assert "INTERVAL '10 days'" in sql
        # 最終リフレッシュから 50 日経過
        assert "INTERVAL '50 days'" in sql
        # NULL 安全
        assert "page_token_expires_at IS NULL" in sql
        assert "COALESCE(last_token_refreshed_at, connected_at)" in sql
        # スキーマ修飾
        assert "tenant_999.tenant_meta_config" in sql


# -------------------------------------------------------------------------
# 6. _count_recent_failures: 連続失敗カウントの仕様
# -------------------------------------------------------------------------


class TestCountRecentFailures:
    """audit_logs を遡る連続失敗カウントの SQL / ロジック検証。"""

    def test_sql_filters_by_record_and_actions(self, fernet_env):
        from app.tasks import refresh_meta_tokens as m

        session = MagicMock()
        session.execute.return_value = iter([])

        m._count_recent_failures(session, "tenant_999", record_id=42)

        call = session.execute.call_args
        sql = call.args[0].text
        params = call.args[1]
        assert "tenant_999.audit_logs" in sql
        assert "table_name = 'tenant_meta_config'" in sql
        assert "INTERVAL '3 days'" in sql
        assert params["record_id"] == 42
        assert params["failed_action"] == m.ACTION_REFRESH_FAILED
        assert params["success_action"] == m.ACTION_REFRESHED

    def test_counts_consecutive_until_success(self, fernet_env):
        """直近順に走査し、success が出たらそれ以降はカウントしない。"""
        from app.tasks import refresh_meta_tokens as m

        # 直近順: failed, failed, refreshed, failed
        # → 直近 2 件 failed のみカウント（refreshed でリセット）
        session = MagicMock()
        session.execute.return_value = iter([
            (m.ACTION_REFRESH_FAILED,),
            (m.ACTION_REFRESH_FAILED,),
            (m.ACTION_REFRESHED,),
            (m.ACTION_REFRESH_FAILED,),
        ])
        n = m._count_recent_failures(session, "tenant_999", record_id=1)
        assert n == 2

    def test_counts_only_failed_with_no_success(self, fernet_env):
        from app.tasks import refresh_meta_tokens as m

        session = MagicMock()
        session.execute.return_value = iter([
            (m.ACTION_REFRESH_FAILED,),
            (m.ACTION_REFRESH_FAILED,),
            (m.ACTION_REFRESH_FAILED,),
        ])
        assert m._count_recent_failures(session, "tenant_999", 1) == 3

    def test_zero_when_no_records(self, fernet_env):
        from app.tasks import refresh_meta_tokens as m

        session = MagicMock()
        session.execute.return_value = iter([])
        assert m._count_recent_failures(session, "tenant_999", 1) == 0


# -------------------------------------------------------------------------
# 7. meta_graph.refresh_page_access_token のヘルパ単体テスト
# -------------------------------------------------------------------------


class TestRefreshPageAccessTokenHelper:
    """app/services/meta_graph.refresh_page_access_token の動作。"""

    @pytest.mark.asyncio
    async def test_calls_oauth_endpoint_with_fb_exchange_token(self, fernet_env):
        import httpx
        from app.services import meta_graph

        captured: dict = {}

        def handler(req: httpx.Request) -> httpx.Response:
            captured["path"] = req.url.path
            captured["params"] = dict(req.url.params)
            return httpx.Response(
                200,
                json={"access_token": "refreshed-long-token", "expires_in": 5183944,
                      "token_type": "bearer"},
            )

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            result = await meta_graph.refresh_page_access_token(
                "current-token-xyz", client=client
            )

        assert result["access_token"] == "refreshed-long-token"
        assert result["expires_in"] == 5183944
        assert result["token_type"] == "bearer"
        assert "/oauth/access_token" in captured["path"]
        assert captured["params"]["grant_type"] == "fb_exchange_token"
        assert captured["params"]["fb_exchange_token"] == "current-token-xyz"
        assert captured["params"]["client_id"] == "test-app-id"

    @pytest.mark.asyncio
    async def test_raises_on_empty_token(self, fernet_env):
        from app.services import meta_graph

        with pytest.raises(ValueError):
            await meta_graph.refresh_page_access_token("")

    @pytest.mark.asyncio
    async def test_raises_when_no_access_token_in_response(self, fernet_env):
        import httpx
        from app.services import meta_graph
        from app.services.meta_graph import MetaGraphTransportError

        def handler(req):
            return httpx.Response(200, json={"foo": "bar"})

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(MetaGraphTransportError):
                await meta_graph.refresh_page_access_token("t", client=client)

    @pytest.mark.asyncio
    async def test_meta_api_error_propagates(self, fernet_env):
        import httpx
        from app.services import meta_graph
        from app.services.meta_graph import MetaGraphAPIError

        def handler(req):
            return httpx.Response(
                400, json={"error": {"type": "OAuthException", "code": 190,
                                       "message": "Invalid OAuth access token."}}
            )

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(MetaGraphAPIError) as exc_info:
                await meta_graph.refresh_page_access_token("t", client=client)
        assert exc_info.value.error_code == 190
