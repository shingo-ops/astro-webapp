"""
Redisキャッシュモジュール（cache.py）のユニットテスト。

Redisサーバー不要: モックで全機能をテストする。
"""

import os
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from app.cache import (
    _token_hash,
    cache_jwt_result,
    get_cached_jwt,
    cache_tenant,
    get_cached_tenant,
    blacklist_token,
    is_token_blacklisted,
    init_redis,
    close_redis,
    JWT_CACHE_TTL,
    TENANT_CACHE_TTL,
)


class TestTokenHash:
    def test_consistent_hash(self):
        """同じトークンに対して同じハッシュが返ること"""
        token = "test-token-123"
        assert _token_hash(token) == _token_hash(token)

    def test_different_tokens_different_hash(self):
        """異なるトークンに対して異なるハッシュが返ること"""
        assert _token_hash("token-a") != _token_hash("token-b")


class TestJWTCache:
    @pytest.fixture
    def mock_redis(self):
        r = AsyncMock()
        with patch("app.cache._redis", r):
            yield r

    async def test_cache_jwt_result(self, mock_redis):
        """JWT検証結果がRedisにキャッシュされること"""
        token = "test-token"
        user_data = {"email": "test@example.com"}
        await cache_jwt_result(token, user_data)
        mock_redis.setex.assert_called_once()
        args = mock_redis.setex.call_args
        assert args[0][1] == JWT_CACHE_TTL

    async def test_get_cached_jwt_hit(self, mock_redis):
        """キャッシュヒット時にユーザーデータが返ること"""
        import json
        mock_redis.get.return_value = json.dumps({"email": "test@example.com"})
        result = await get_cached_jwt("test-token")
        assert result == {"email": "test@example.com"}

    async def test_get_cached_jwt_miss(self, mock_redis):
        """キャッシュミス時にNoneが返ること"""
        mock_redis.get.return_value = None
        result = await get_cached_jwt("test-token")
        assert result is None

    async def test_cache_jwt_no_redis(self):
        """Redis未接続時にエラーにならないこと"""
        with patch("app.cache._redis", None):
            await cache_jwt_result("token", {"email": "test@example.com"})
            result = await get_cached_jwt("token")
            assert result is None


class TestTenantCache:
    @pytest.fixture
    def mock_redis(self):
        r = AsyncMock()
        with patch("app.cache._redis", r):
            yield r

    async def test_cache_tenant(self, mock_redis):
        """テナント情報がキャッシュされること"""
        await cache_tenant(1, True)
        mock_redis.setex.assert_called_once()
        args = mock_redis.setex.call_args
        assert args[0][1] == TENANT_CACHE_TTL

    async def test_get_cached_tenant_hit(self, mock_redis):
        """キャッシュヒット時にテナント情報が返ること"""
        import json
        mock_redis.get.return_value = json.dumps({"is_active": True})
        result = await get_cached_tenant(1)
        assert result == {"is_active": True}

    async def test_get_cached_tenant_miss(self, mock_redis):
        """キャッシュミス時にNoneが返ること"""
        mock_redis.get.return_value = None
        result = await get_cached_tenant(1)
        assert result is None


class TestBlacklist:
    @pytest.fixture
    def mock_redis(self):
        r = AsyncMock()
        # pipeline()は同期メソッドとしてMagicMockを返す
        mock_pipe = MagicMock()
        mock_pipe.execute = AsyncMock(return_value=[True, 0])
        r.pipeline = MagicMock(return_value=mock_pipe)
        r._mock_pipe = mock_pipe  # テストからアクセス用
        with patch("app.cache._redis", r):
            yield r

    async def test_blacklist_token(self, mock_redis):
        """トークンがブラックリストに追加されること（pipeline使用）"""
        await blacklist_token("test-token", ttl=3600)
        pipe = mock_redis._mock_pipe
        pipe.setex.assert_called_once()
        pipe.delete.assert_called_once()
        pipe.execute.assert_called_once()

    async def test_is_token_blacklisted_true(self, mock_redis):
        """ブラックリストに含まれるトークンでTrueが返ること"""
        mock_redis.exists.return_value = 1
        assert await is_token_blacklisted("test-token") is True

    async def test_is_token_blacklisted_false(self, mock_redis):
        """ブラックリストに含まれないトークンでFalseが返ること"""
        mock_redis.exists.return_value = 0
        assert await is_token_blacklisted("test-token") is False

    async def test_blacklist_no_redis(self):
        """Redis未接続時はfail-closed（Trueを返す）"""
        with patch("app.cache._redis", None):
            await blacklist_token("token")
            # fail-closed: Redis障害時は安全側に倒してブラックリスト扱い
            assert await is_token_blacklisted("token") is True


class TestLogoutEndpoint:
    async def test_logout(self):
        """ログアウトAPIがトークンをブラックリストに追加すること"""
        from app.main import app
        from httpx import AsyncClient, ASGITransport

        with patch("app.routers.auth.blacklist_token", new_callable=AsyncMock) as mock_bl:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/api/v1/auth/logout",
                    headers={"Authorization": "Bearer test-token-xyz"},
                )
            assert resp.status_code == 200
            assert resp.json()["message"] == "ログアウトしました"
            mock_bl.assert_called_once_with("test-token-xyz", ttl=3600)
