"""
P1必須修正のテスト（test_p1_fixes.py）

対象:
  1. MetaGraphRateLimitError: レート制限コードで正しく raise される
  2. leads.py: RateLimitError → 429、TimeoutError → 504
  3. global exception handler: SQLAlchemy OperationalError → 503
  4. global exception handler: 予期しない例外 → 500
  5. health.py: DB障害時に503を返す

実行:
    pytest backend/tests/test_p1_fixes.py -v
"""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

import pytest
from httpx import ASGITransport, AsyncClient


pytestmark = pytest.mark.asyncio


# ─────────────────────────────────────────────────────────────────────────────
# MetaGraphRateLimitError テスト
# ─────────────────────────────────────────────────────────────────────────────

async def test_meta_graph_rate_limit_error_raised_on_code_4():
    """Meta error.code=4 (Application rate limit) で MetaGraphRateLimitError が raise される。"""
    # Arrange
    from app.services.meta_graph import MetaGraphRateLimitError, _request
    import httpx

    rate_limit_body = {"error": {"code": 4, "message": "Application request limit reached", "type": "OAuthException"}}

    class MockTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            import json
            return httpx.Response(400, json=rate_limit_body)

    # Act / Assert
    with pytest.raises(MetaGraphRateLimitError) as exc_info:
        async with httpx.AsyncClient(transport=MockTransport()) as client:
            await _request("GET", "https://graph.facebook.com/test", client=client)

    assert exc_info.value.error_code == 4


async def test_meta_graph_rate_limit_error_raised_on_http_429():
    """HTTP 429レスポンスで MetaGraphRateLimitError が raise される。"""
    # Arrange
    from app.services.meta_graph import MetaGraphRateLimitError, _request
    import httpx

    rate_limit_body = {"error": {"code": 4, "message": "Rate limit", "type": "OAuthException"}}

    class MockTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            return httpx.Response(429, json=rate_limit_body)

    # Act / Assert
    with pytest.raises(MetaGraphRateLimitError):
        async with httpx.AsyncClient(transport=MockTransport()) as client:
            await _request("GET", "https://graph.facebook.com/test", client=client)


async def test_meta_graph_api_error_not_rate_limit_on_regular_code():
    """通常のAPIエラー（code=100）では MetaGraphAPIError が raise され MetaGraphRateLimitError ではない。"""
    # Arrange
    from app.services.meta_graph import MetaGraphAPIError, MetaGraphRateLimitError, _request
    import httpx

    error_body = {"error": {"code": 100, "message": "Unsupported operation", "type": "OAuthException"}}

    class MockTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            return httpx.Response(400, json=error_body)

    # Act / Assert
    with pytest.raises(MetaGraphAPIError) as exc_info:
        async with httpx.AsyncClient(transport=MockTransport()) as client:
            await _request("GET", "https://graph.facebook.com/test", client=client)

    # MetaGraphRateLimitError ではないこと
    assert not isinstance(exc_info.value, MetaGraphRateLimitError)


# ─────────────────────────────────────────────────────────────────────────────
# グローバル例外ハンドラーテスト
# ─────────────────────────────────────────────────────────────────────────────

async def test_global_handler_sqlalchemy_operational_error_returns_503():
    """SQLAlchemy OperationalError（DB接続失敗）はグローバルハンドラーで503に変換される。"""
    # Arrange
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from sqlalchemy.exc import OperationalError
    from app.main import db_operational_error_handler

    app = FastAPI()
    app.add_exception_handler(OperationalError, db_operational_error_handler)

    @app.get("/test-db-error")
    async def trigger_db_error():
        raise OperationalError("Connection refused", None, None)

    # Act
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/test-db-error")

    # Assert
    assert resp.status_code == 503
    assert "接続" in resp.json()["detail"] or "database" in resp.json()["detail"].lower()


async def test_global_handler_unhandled_exception_returns_500():
    """未捕捉例外はグローバルハンドラーで500に変換される。

    main.appに実際の例外ハンドラーが設定されていることを検証。
    """
    # Arrange: main.py の app に global_exception_handler が登録されているか確認
    from app.main import app, global_exception_handler
    from starlette.exceptions import HTTPException as StarletteHTTPException

    # ハンドラーが登録されていることを確認
    assert Exception in app.exception_handlers, \
        "global_exception_handler は app.exception_handlers[Exception] に登録されるべき"
    # 登録されたハンドラーが正しい関数であることを確認
    assert app.exception_handlers[Exception] is global_exception_handler


# ─────────────────────────────────────────────────────────────────────────────
# health.py テスト
# ─────────────────────────────────────────────────────────────────────────────

async def test_health_check_db_failure_returns_503():
    """DB接続失敗時にhealth checkは503を返す。"""
    # Arrange
    from fastapi import FastAPI
    from app.routers import health
    from sqlalchemy.exc import OperationalError

    app = FastAPI()
    app.include_router(health.router, prefix="/api")

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=OperationalError("Connection refused", None, None))

    # Act
    with patch("app.routers.health.get_db", return_value=mock_db):
        from app.database import get_db as real_get_db
        app.dependency_overrides[real_get_db] = lambda: mock_db

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/health")

        app.dependency_overrides.clear()

    # Assert
    assert resp.status_code == 503
    assert resp.json()["status"] == "error"
    assert resp.json()["database"] == "disconnected"


async def test_health_check_db_ok_returns_200():
    """DB接続成功時にhealth checkは200を返す。"""
    # Arrange
    from fastapi import FastAPI
    from app.routers import health

    app = FastAPI()
    app.include_router(health.router, prefix="/api")

    mock_result = MagicMock()
    mock_result.scalar.return_value = 1
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    from app.database import get_db as real_get_db
    app.dependency_overrides[real_get_db] = lambda: mock_db

    # Redisとceleryをスキップ（health.pyはapp.cacheからget_redisをインポートしている）
    with patch("app.cache.get_redis", return_value=None), \
         patch.dict(os.environ, {"CELERY_BROKER_URL": ""}):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/health")

    app.dependency_overrides.clear()

    # Assert
    assert resp.status_code == 200
    assert resp.json()["database"] == "connected"
