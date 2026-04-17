"""
CeleryタスクとレポートAPIのユニットテスト。

Celeryブローカー不要: タスクのロジックとAPIエンドポイントをモックでテストする。
"""

import os
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

import json
from unittest.mock import patch, MagicMock, AsyncMock

import pytest


class TestCeleryAppConfig:
    """Celeryアプリケーション設定のテスト"""

    def test_celery_app_import(self):
        """celery_appがインポートできること"""
        from app.celery_app import celery_app
        assert celery_app.main == "jarvis_crm"

    def test_celery_config(self):
        """Celery設定が正しいこと"""
        from app.celery_app import celery_app
        assert celery_app.conf.task_serializer == "json"
        assert celery_app.conf.timezone == "Asia/Tokyo"
        assert celery_app.conf.enable_utc is True

    def test_beat_schedule_exists(self):
        """定期タスクスケジュールが定義されていること"""
        from app.celery_app import celery_app
        schedule = celery_app.conf.beat_schedule
        assert "refresh-dashboard-kpis" in schedule
        assert "archive-old-audit-logs" in schedule

    def test_beat_schedule_dashboard_interval(self):
        """KPI更新が10分間隔であること"""
        from app.celery_app import celery_app
        schedule = celery_app.conf.beat_schedule["refresh-dashboard-kpis"]
        assert schedule["schedule"] == 600.0

    def test_task_modules_registered(self):
        """タスクモジュールが登録されていること"""
        from app.celery_app import celery_app
        assert "app.tasks.dashboard" in celery_app.conf.include
        assert "app.tasks.maintenance" in celery_app.conf.include
        assert "app.tasks.reports" in celery_app.conf.include


class TestDashboardTask:
    """ダッシュボードKPIキャッシュタスクのテスト"""

    def test_compute_kpis_returns_expected_keys(self):
        """_compute_kpisが必要なキー（Phase 1拡張版）を全て含むこと"""
        from app.tasks.dashboard import _compute_kpis

        mock_session = MagicMock()

        lead_row = {"total": 7, "open_count": 4}
        deal_row = {
            "total": 5, "open_count": 3, "won_count": 2,
            "total_amount": 1000000, "won_amount": 500000,
        }
        order_row = {"total": 8, "pending_count": 2, "total_amount": 800000}

        def mk_mapping(data):
            m = MagicMock()
            m.__getitem__ = lambda self, key: data[key]
            return m

        mock_lead = mk_mapping(lead_row)
        mock_deal = mk_mapping(deal_row)
        mock_order = mk_mapping(order_row)

        call_count = [0]

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            result = MagicMock()
            # クエリ順:
            # 1: SET search_path / 2: SET app.tenant_id
            # 3: customers count / 4: leads集計 / 5: deals集計
            # 6: orders集計 / 7: teams count
            # 8: 直近顧客 / 9: 直近商談 / 10: 直近リード
            if call_count[0] == 3:
                result.scalar.return_value = 10
            elif call_count[0] == 4:
                result.mappings.return_value.first.return_value = mock_lead
            elif call_count[0] == 5:
                result.mappings.return_value.first.return_value = mock_deal
            elif call_count[0] == 6:
                result.mappings.return_value.first.return_value = mock_order
            elif call_count[0] == 7:
                result.scalar.return_value = 3
            elif call_count[0] in (8, 9, 10):
                result.mappings.return_value.all.return_value = []
            return result

        mock_session.execute.side_effect = side_effect

        kpis = _compute_kpis(mock_session, 1)

        expected_keys = {
            "schema_version",
            "customer_count",
            "lead_count", "lead_open_count",
            "deal_count", "deal_open_count", "deal_won_count",
            "deal_total_amount", "deal_won_amount",
            "order_count", "order_pending_count", "order_total_amount",
            "team_count",
            "recent_customers", "recent_deals", "recent_leads",
        }
        assert set(kpis.keys()) == expected_keys
        assert kpis["customer_count"] == 10
        assert kpis["lead_count"] == 7
        assert kpis["deal_count"] == 5
        assert kpis["order_count"] == 8
        assert kpis["team_count"] == 3
        assert kpis["schema_version"] == 2


class TestMaintenanceTask:
    """メンテナンスタスクのテスト"""

    def test_retention_days_config(self):
        """保持日数が90日であること"""
        from app.tasks.maintenance import AUDIT_LOG_RETENTION_DAYS
        assert AUDIT_LOG_RETENTION_DAYS == 90


class TestReportsTask:
    """レポートエクスポートタスクのテスト"""

    def test_export_queries_defined(self):
        """全レポートタイプのクエリが定義されていること"""
        from app.tasks.reports import EXPORT_QUERIES
        assert "customers" in EXPORT_QUERIES
        assert "deals" in EXPORT_QUERIES
        assert "orders" in EXPORT_QUERIES

    def test_export_queries_have_headers(self):
        """各レポートにヘッダーが定義されていること"""
        from app.tasks.reports import EXPORT_QUERIES
        for report_type, config in EXPORT_QUERIES.items():
            assert "headers" in config, f"{report_type}にheadersがない"
            assert "query" in config, f"{report_type}にqueryがない"
            assert len(config["headers"]) > 0

    def test_export_result_ttl(self):
        """エクスポート結果の保持期間が1時間であること"""
        from app.tasks.reports import EXPORT_RESULT_TTL
        assert EXPORT_RESULT_TTL == 3600


class TestReportsAPI:
    """レポートAPIエンドポイントのテスト"""

    async def test_export_request_valid_type(self):
        """有効なレポートタイプでエクスポートリクエストが受け付けられること"""
        from app.main import app
        from app.auth.dependencies import get_current_user, get_current_tenant
        from app.database import get_db
        from httpx import AsyncClient, ASGITransport
        from app.models import User

        mock_user = User()
        mock_user.id = 999
        mock_user.tenant_id = 999
        mock_user.username = "testuser"
        mock_user.email = "test@example.com"
        mock_user.role = "admin"
        mock_user.is_active = True

        app.dependency_overrides[get_db] = lambda: iter([MagicMock()])
        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_current_tenant] = lambda: 999

        mock_task_result = MagicMock()
        mock_task_result.id = "test-task-id-123"

        with patch("app.tasks.reports.export_csv.delay", return_value=mock_task_result):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/api/v1/reports/export",
                    json={"report_type": "customers"},
                )

        app.dependency_overrides.clear()

        assert resp.status_code == 202
        data = resp.json()
        assert data["task_id"] == "test-task-id-123"
        assert "customers" in data["message"]

    async def test_export_request_invalid_type(self):
        """無効なレポートタイプで422が返ること"""
        from app.main import app
        from app.auth.dependencies import get_current_user, get_current_tenant
        from app.database import get_db
        from httpx import AsyncClient, ASGITransport
        from app.models import User

        mock_user = User()
        mock_user.id = 999
        mock_user.tenant_id = 999
        mock_user.username = "testuser"
        mock_user.email = "test@example.com"
        mock_user.role = "admin"
        mock_user.is_active = True

        app.dependency_overrides[get_db] = lambda: iter([MagicMock()])
        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_current_tenant] = lambda: 999

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/reports/export",
                json={"report_type": "invalid_type"},
            )

        app.dependency_overrides.clear()
        assert resp.status_code == 422

    async def test_download_not_found(self):
        """存在しないタスクIDで404が返ること"""
        from app.main import app
        from app.auth.dependencies import get_current_user, get_current_tenant
        from app.database import get_db
        from httpx import AsyncClient, ASGITransport
        from app.models import User

        mock_user = User()
        mock_user.id = 999
        mock_user.tenant_id = 999
        mock_user.username = "testuser"
        mock_user.email = "test@example.com"
        mock_user.role = "admin"
        mock_user.is_active = True

        app.dependency_overrides[get_db] = lambda: iter([MagicMock()])
        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_current_tenant] = lambda: 999

        mock_redis = AsyncMock()
        mock_redis.get.return_value = None

        with patch("app.routers.reports.get_redis", return_value=mock_redis):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/v1/reports/nonexistent-id/download")

        app.dependency_overrides.clear()
        assert resp.status_code == 404


class TestDashboardCacheIntegration:
    """ダッシュボードのキャッシュ統合テスト"""

    async def test_dashboard_cache_hit(self):
        """キャッシュヒット時にキャッシュデータが返ること"""
        from app.main import app
        from app.auth.dependencies import get_current_user, get_current_tenant
        from app.database import get_db
        from httpx import AsyncClient, ASGITransport
        from app.models import User

        mock_user = User()
        mock_user.id = 999
        mock_user.tenant_id = 999
        mock_user.username = "testuser"
        mock_user.email = "test@example.com"
        mock_user.role = "admin"
        mock_user.is_active = True

        app.dependency_overrides[get_db] = lambda: iter([MagicMock()])
        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_current_tenant] = lambda: 999

        # schema_version=3 を含む最新スキーマのキャッシュ（Phase 3拡張後）
        cached_kpi = json.dumps({
            "schema_version": 3,
            "customer_count": 42,
            "lead_count": 7,
            "lead_open_count": 4,
            "deal_count": 10,
            "deal_open_count": 5,
            "deal_won_count": 5,
            "deal_total_amount": 1000000.0,
            "deal_won_amount": 500000.0,
            "order_count": 20,
            "order_pending_count": 3,
            "order_total_amount": 800000.0,
            "team_count": 3,
            "recent_customers": [],
            "recent_deals": [],
            "recent_leads": [],
        })

        mock_redis = AsyncMock()
        mock_redis.get.return_value = cached_kpi

        with patch("app.routers.dashboard.get_redis", return_value=mock_redis):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/v1/dashboard")

        app.dependency_overrides.clear()
        assert resp.status_code == 200
        data = resp.json()
        assert data["cached"] is True
        assert data["customer_count"] == 42
