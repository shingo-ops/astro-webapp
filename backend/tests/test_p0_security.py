"""
P0セキュリティ修正のテスト（test_p0_security.py）

対象:
  1. META_APP_SECRET未設定時にWebhookが500を返す（署名バイパス防止）
  2. 不正なJSONボディでWebhookが400を返す
  3. Redis障害時にblacklist_tokenがFalseを返す
  4. blacklist_token失敗時にlogoutが503を返す
  5. is_token_blacklisted: Redis障害時はfail-open（False）

実行:
    pytest backend/tests/test_p0_security.py -v
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.cache import blacklist_token, is_token_blacklisted


# ─────────────────────────────────────────────────────────────────────────────
# ヘルパー: HMAC 署名付きリクエストを生成する
# ─────────────────────────────────────────────────────────────────────────────

def _make_signed_headers(body: bytes, secret: str) -> dict:
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return {"X-Hub-Signature-256": sig, "Content-Type": "application/json"}


# ─────────────────────────────────────────────────────────────────────────────
# Webhook セキュリティテスト
# ─────────────────────────────────────────────────────────────────────────────

pytestmark = pytest.mark.asyncio


@pytest.fixture
def webhook_app():
    """最小構成のFastAPIアプリ（webhookルーターのみ）。"""
    from fastapi import FastAPI
    from app.routers import webhook

    app = FastAPI()
    app.include_router(webhook.router, prefix="/api/v1")
    return app


async def test_webhook_missing_meta_app_secret(webhook_app):
    """META_APP_SECRETが空の場合、Webhookエンドポイントは500を返す。

    空シークレットで署名検証をバイパスできる攻撃を防ぐため、
    シークレット未設定時はリクエストを受け付けない。
    """
    # Arrange
    body = json.dumps({"object": "page", "entry": []}).encode()
    headers = _make_signed_headers(body, "")  # 空シークレットで署名

    # Act
    with patch.dict(os.environ, {"META_APP_SECRET": ""}):
        transport = ASGITransport(app=webhook_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/webhook/messenger",
                content=body,
                headers=headers,
            )

    # Assert
    assert resp.status_code == 500
    assert "署名検証" in resp.json()["detail"] or "configured" in resp.json()["detail"]


async def test_webhook_invalid_json(webhook_app):
    """不正なJSONボディを受け取った場合、Webhookエンドポイントは400を返す。

    HMAC署名が正しくてもJSONパースに失敗した場合は400で早期終了し、
    unhandled 500 を防ぐ。
    """
    # Arrange
    secret = "test-secret-value"
    body = b"this is not valid json {{{"
    headers = _make_signed_headers(body, secret)

    # Act
    with patch.dict(os.environ, {"META_APP_SECRET": secret, "META_VERIFY_TOKEN": "tok"}):
        transport = ASGITransport(app=webhook_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/webhook/messenger",
                content=body,
                headers=headers,
            )

    # Assert
    assert resp.status_code == 400
    assert "json" in resp.json()["detail"].lower() or "invalid" in resp.json()["detail"].lower()


# ─────────────────────────────────────────────────────────────────────────────
# blacklist_token: Redis障害時の戻り値テスト
# ─────────────────────────────────────────────────────────────────────────────

async def test_blacklist_token_redis_failure_returns_false():
    """Redis未接続時にblacklist_tokenはFalseを返す。

    呼び出し元（logout）がこの戻り値を見て503を返せるようにするため、
    Noneではなくbool(False)を返すことを保証する。
    """
    # Arrange: Redisを切断状態にする
    with patch("app.cache._redis", None):
        # Act
        result = await blacklist_token("some-token", ttl=3600)

    # Assert
    assert result is False


async def test_blacklist_token_redis_exception_returns_false():
    """Redisへの書き込みが例外を投げた場合もblacklist_tokenはFalseを返す。"""
    # Arrange
    mock_pipe = MagicMock()
    mock_pipe.setex = MagicMock()
    mock_pipe.delete = MagicMock()
    mock_pipe.execute = AsyncMock(side_effect=Exception("Redis connection error"))

    mock_redis = AsyncMock()
    mock_redis.pipeline = MagicMock(return_value=mock_pipe)

    with patch("app.cache._redis", mock_redis):
        # Act
        result = await blacklist_token("some-token", ttl=3600)

    # Assert
    assert result is False


async def test_is_token_blacklisted_redis_down_returns_false():
    """Redis未接続時にis_token_blacklistedはFalse（fail-open）を返す。

    Redis障害で全ユーザーを401にするよりも、ログアウト済みトークンが
    短期間有効である方がサービス可用性上許容できる。
    """
    # Arrange
    with patch("app.cache._redis", None):
        # Act
        result = await is_token_blacklisted("some-token")

    # Assert
    assert result is False


async def test_is_token_blacklisted_redis_exception_returns_false():
    """Redis例外時にis_token_blacklistedはFalse（fail-open）を返す。"""
    # Arrange
    mock_redis = AsyncMock()
    mock_redis.exists = AsyncMock(side_effect=Exception("timeout"))

    with patch("app.cache._redis", mock_redis):
        # Act
        result = await is_token_blacklisted("some-token")

    # Assert
    assert result is False


# ─────────────────────────────────────────────────────────────────────────────
# logout 503テスト
# ─────────────────────────────────────────────────────────────────────────────

async def test_logout_503_when_blacklist_fails():
    """blacklist_tokenがFalseを返した場合、logoutエンドポイントは503を返す。

    トークンの無効化に失敗した場合に200を返すと、クライアントは
    ログアウト成功と誤認する。503で再試行を促す。
    """
    # Arrange
    from app.main import app

    with patch("app.routers.auth.blacklist_token", new_callable=AsyncMock) as mock_bl:
        mock_bl.return_value = False  # 失敗を模擬

        # Act
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/auth/logout",
                headers={"Authorization": "Bearer test-token-xyz"},
            )

    # Assert
    assert resp.status_code == 503
    assert "失敗" in resp.json()["detail"] or "failed" in resp.json()["detail"].lower()


async def test_logout_200_when_blacklist_succeeds():
    """blacklist_tokenが成功した場合、logoutは200を返す（正常系の確認）。"""
    # Arrange
    from app.main import app

    with patch("app.routers.auth.blacklist_token", new_callable=AsyncMock) as mock_bl:
        mock_bl.return_value = True  # 成功を模擬

        # Act
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/auth/logout",
                headers={"Authorization": "Bearer test-token-xyz"},
            )

    # Assert
    assert resp.status_code == 200
    assert resp.json()["message"] == "ログアウトしました"
