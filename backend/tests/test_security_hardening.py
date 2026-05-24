"""
セキュリティ強化機能の自動テスト（P0-1 / P2-2 / P2-3 / P4）

カバー範囲:
  P0-1  — IPブルートフォース保護（check_auth_rate_limit / record_auth_failure）
  P0-1  — メール登録試行制限（check_register_rate_limit / record_register_failure）
  P2-2  — RateLimitMiddleware（認証済み100回/分・未認証60回/分・Redis fail-open）
  P2-3  — 大量エクスポート検知（_check_and_record_bulk_export・閾値超過でTrue）
  P4    — SessionGuardMiddleware（物理不可能移動のみ401・通常IP変化は通過）

実行:
    pytest backend/tests/test_security_hardening.py -v
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
import time
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

# reportlab は未インストール環境でも app.main が import できるようにスタブ化
for _mod in [
    "reportlab",
    "reportlab.lib",
    "reportlab.lib.pagesizes",
    "reportlab.lib.styles",
    "reportlab.lib.units",
    "reportlab.lib.colors",
    "reportlab.platypus",
    "reportlab.platypus.paragraph",
    "reportlab.platypus.tables",
    "reportlab.platypus.doctemplate",
    "reportlab.pdfbase",
    "reportlab.pdfbase.pdfmetrics",
    "reportlab.pdfbase.ttfonts",
    "reportlab.pdfgen",
    "reportlab.pdfgen.canvas",
]:
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


# ─────────────────────────────────────────────────────────────────────────────
# ヘルパー
# ─────────────────────────────────────────────────────────────────────────────

def _make_jwt(email: str = "test@example.com") -> str:
    """署名なしのダミーJWT（ミドルウェアのメールデコード用）。"""
    header = base64.urlsafe_b64encode(b'{"alg":"RS256","typ":"JWT"}').rstrip(b"=").decode()
    payload_bytes = json.dumps({"email": email, "sub": "uid123"}).encode()
    payload = base64.urlsafe_b64encode(payload_bytes).rstrip(b"=").decode()
    return f"{header}.{payload}.fake-signature"


def _ip_hash(ip: str) -> str:
    return hashlib.sha256(ip.encode()).hexdigest()[:16]


# ─────────────────────────────────────────────────────────────────────────────
# P0-1: IPブルートフォース保護 — cache.py 関数単体テスト
# ─────────────────────────────────────────────────────────────────────────────

class TestAuthRateLimit:
    """check_auth_rate_limit / record_auth_failure の単体テスト"""

    async def test_check_auth_rate_limit_below_threshold_returns_false(self):
        """失敗回数が閾値未満の場合は False（通過許可）を返す。"""
        from app.cache import check_auth_rate_limit, AUTH_FAIL_MAX

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=str(AUTH_FAIL_MAX - 1))

        with patch("app.cache._redis", mock_redis):
            result = await check_auth_rate_limit("1.2.3.4")

        assert result is False

    async def test_check_auth_rate_limit_at_threshold_returns_true(self):
        """失敗回数が閾値に達した場合は True（ブロック）を返す。"""
        from app.cache import check_auth_rate_limit, AUTH_FAIL_MAX

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=str(AUTH_FAIL_MAX))

        with patch("app.cache._redis", mock_redis):
            result = await check_auth_rate_limit("1.2.3.4")

        assert result is True

    async def test_check_auth_rate_limit_redis_down_fail_open(self):
        """Redis未接続時は fail-open（False = 通過許可）を返す。"""
        from app.cache import check_auth_rate_limit

        with patch("app.cache._redis", None):
            result = await check_auth_rate_limit("1.2.3.4")

        assert result is False

    async def test_check_auth_rate_limit_redis_exception_fail_open(self):
        """Redis例外時も fail-open を維持する。"""
        from app.cache import check_auth_rate_limit

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(side_effect=Exception("timeout"))

        with patch("app.cache._redis", mock_redis):
            result = await check_auth_rate_limit("1.2.3.4")

        assert result is False

    async def test_record_auth_failure_increments_counter(self):
        """record_auth_failure がRedisカウンターをインクリメントする。"""
        from app.cache import record_auth_failure, AUTH_FAIL_LOCKOUT_TTL

        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=1)
        mock_redis.expire = AsyncMock()

        with patch("app.cache._redis", mock_redis):
            await record_auth_failure("1.2.3.4")

        ip_hash = _ip_hash("1.2.3.4")
        expected_key = f"auth_fail_ip:{ip_hash}"
        mock_redis.incr.assert_called_once_with(expected_key)
        mock_redis.expire.assert_called_once_with(expected_key, AUTH_FAIL_LOCKOUT_TTL)

    async def test_record_auth_failure_no_expire_on_subsequent_calls(self):
        """2回目以降の失敗記録では expire を呼ばない（TTLリセット防止）。"""
        from app.cache import record_auth_failure

        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=5)  # 2回目以降: count > 1
        mock_redis.expire = AsyncMock()

        with patch("app.cache._redis", mock_redis):
            await record_auth_failure("1.2.3.4")

        mock_redis.expire.assert_not_called()

    async def test_record_auth_failure_redis_down_no_exception(self):
        """Redis未接続時にrecord_auth_failureが例外を出さない（fail-safe）。"""
        from app.cache import record_auth_failure

        with patch("app.cache._redis", None):
            await record_auth_failure("1.2.3.4")


# ─────────────────────────────────────────────────────────────────────────────
# P0-1: get_current_user の429返却テスト
# ─────────────────────────────────────────────────────────────────────────────

class TestAuthDependency429:
    """IPブルートフォース保護がAPI層で機能することを検証"""

    async def test_get_current_user_returns_429_when_ip_locked(self):
        """IPがブロック状態のとき、保護エンドポイントが429を返す。"""
        from app.main import app

        with patch("app.auth.dependencies.check_auth_rate_limit", new_callable=AsyncMock) as mock_check, \
             patch("app.auth.dependencies.is_token_blacklisted", new_callable=AsyncMock) as mock_bl:
            mock_check.return_value = True   # IPロック中
            mock_bl.return_value = False

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(
                    "/api/v1/customers",
                    headers={"Authorization": "Bearer valid-token-format"},
                )

        assert resp.status_code == 429
        assert "認証試行" in resp.json()["detail"]

    async def test_get_current_user_records_failure_on_invalid_token(self):
        """無効なFirebaseトークンで record_auth_failure が呼ばれる。"""
        from app.main import app

        with patch("app.auth.dependencies.check_auth_rate_limit", new_callable=AsyncMock) as mock_check, \
             patch("app.auth.dependencies.is_token_blacklisted", new_callable=AsyncMock) as mock_bl, \
             patch("app.auth.dependencies.get_cached_jwt", new_callable=AsyncMock) as mock_cache, \
             patch("app.auth.dependencies.record_auth_failure", new_callable=AsyncMock) as mock_record, \
             patch("firebase_admin.auth.verify_id_token", side_effect=Exception("invalid token")):
            mock_check.return_value = False
            mock_bl.return_value = False
            mock_cache.return_value = None

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(
                    "/api/v1/customers",
                    headers={"Authorization": "Bearer invalid-firebase-token"},
                )

        assert resp.status_code == 401
        mock_record.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# P2-2: RateLimitMiddleware
# ─────────────────────────────────────────────────────────────────────────────

class TestRateLimitMiddleware:
    """RateLimitMiddleware の動作検証"""

    def _make_app(self):
        """RateLimitMiddlewareだけを装着した最小FastAPIアプリ。"""
        from fastapi import FastAPI
        from app.middleware.rate_limit import RateLimitMiddleware

        app = FastAPI()
        app.add_middleware(RateLimitMiddleware)

        @app.get("/api/test")
        async def test_endpoint():
            return {"ok": True}

        @app.get("/health")
        async def health():
            return {"status": "ok"}

        return app

    async def test_rate_limit_not_exceeded_returns_200(self):
        """カウンターが閾値未満の場合は200を返す。"""
        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=1)
        mock_redis.expire = AsyncMock()

        app = self._make_app()

        # get_redis はミドルウェア内で app.cache から動的importされる
        with patch("app.cache._redis", mock_redis):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/test")

        assert resp.status_code == 200

    async def test_rate_limit_exceeded_authed_returns_429(self):
        """認証済みユーザーが100回/分を超えたら429を返す。"""
        from app.middleware.rate_limit import AUTHED_RATE_LIMIT

        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=AUTHED_RATE_LIMIT + 1)
        mock_redis.expire = AsyncMock()

        app = self._make_app()
        token = _make_jwt("user@example.com")

        with patch("app.cache._redis", mock_redis):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(
                    "/api/test",
                    headers={"Authorization": f"Bearer {token}"},
                )

        assert resp.status_code == 429
        assert "Retry-After" in resp.headers

    async def test_rate_limit_exceeded_unauthed_returns_429(self):
        """未認証IPが60回/分を超えたら429を返す。"""
        from app.middleware.rate_limit import UNAUTHED_RATE_LIMIT

        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=UNAUTHED_RATE_LIMIT + 1)
        mock_redis.expire = AsyncMock()

        app = self._make_app()

        with patch("app.cache._redis", mock_redis):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/test")

        assert resp.status_code == 429

    async def test_rate_limit_redis_down_fail_open(self):
        """Redis未接続時は制限をかけない（fail-open）。"""
        app = self._make_app()

        with patch("app.cache._redis", None):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/test")

        assert resp.status_code == 200

    async def test_rate_limit_skips_health_path(self):
        """ヘルスチェックパスはレート制限を受けない。"""
        from app.middleware.rate_limit import AUTHED_RATE_LIMIT

        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=AUTHED_RATE_LIMIT + 100)
        mock_redis.expire = AsyncMock()

        app = self._make_app()

        with patch("app.cache._redis", mock_redis):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/health")

        assert resp.status_code == 200

    async def test_rate_limit_retry_after_header_present(self):
        """429レスポンスに Retry-After ヘッダーが付いていること。"""
        from app.middleware.rate_limit import AUTHED_RATE_LIMIT, AUTHED_WINDOW_SEC

        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=AUTHED_RATE_LIMIT + 1)
        mock_redis.expire = AsyncMock()

        app = self._make_app()
        token = _make_jwt()

        with patch("app.cache._redis", mock_redis):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(
                    "/api/test",
                    headers={"Authorization": f"Bearer {token}"},
                )

        assert resp.status_code == 429
        assert resp.headers.get("Retry-After") == str(AUTHED_WINDOW_SEC)


# ─────────────────────────────────────────────────────────────────────────────
# P2-3: 大量エクスポート検知
# ─────────────────────────────────────────────────────────────────────────────

class TestBulkExportDetection:
    """audit.py の大量エクスポート検知ロジック検証"""

    async def test_bulk_export_below_threshold_returns_false(self):
        """コール数が閾値未満の場合は False を返す。"""
        from app.middleware.audit import _check_and_record_bulk_export, BULK_EXPORT_MAX_CALLS

        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=BULK_EXPORT_MAX_CALLS - 1)
        mock_redis.expire = AsyncMock()

        with patch("app.cache._redis", mock_redis):
            result = await _check_and_record_bulk_export("user@example.com")

        assert result is False

    async def test_bulk_export_at_threshold_returns_true(self):
        """コール数が閾値を超えたら True（アラート対象）を返す。"""
        from app.middleware.audit import _check_and_record_bulk_export, BULK_EXPORT_MAX_CALLS

        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=BULK_EXPORT_MAX_CALLS + 1)
        mock_redis.expire = AsyncMock()

        with patch("app.cache._redis", mock_redis):
            result = await _check_and_record_bulk_export("user@example.com")

        assert result is True

    async def test_bulk_export_no_email_returns_false(self):
        """ユーザーメールが None の場合は False（未認証アクセスは追跡しない）。"""
        from app.middleware.audit import _check_and_record_bulk_export

        result = await _check_and_record_bulk_export(None)

        assert result is False

    async def test_bulk_export_redis_down_fail_open(self):
        """Redis未接続時は False（検知せず通過）を返す。"""
        from app.middleware.audit import _check_and_record_bulk_export

        with patch("app.cache._redis", None):
            result = await _check_and_record_bulk_export("user@example.com")

        assert result is False

    async def test_bulk_export_sets_ttl_on_first_call(self):
        """初回記録時に Redis の TTL が設定されること。"""
        from app.middleware.audit import _check_and_record_bulk_export, BULK_EXPORT_WINDOW_SEC

        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=1)  # 初回
        mock_redis.expire = AsyncMock()

        with patch("app.cache._redis", mock_redis):
            await _check_and_record_bulk_export("user@example.com")

        expected_ttl = BULK_EXPORT_WINDOW_SEC + 60
        mock_redis.expire.assert_called_once()
        _, expire_ttl = mock_redis.expire.call_args[0]
        assert expire_ttl == expected_ttl


# ─────────────────────────────────────────────────────────────────────────────
# P4: SessionGuardMiddleware
# ─────────────────────────────────────────────────────────────────────────────

class TestSessionGuardMiddleware:
    """物理不可能移動検知ミドルウェアの動作検証"""

    def _make_app(self):
        from fastapi import FastAPI
        from app.middleware.session_guard import SessionGuardMiddleware

        app = FastAPI()
        app.add_middleware(SessionGuardMiddleware)

        @app.get("/api/test")
        async def test_endpoint():
            return {"ok": True}

        return app

    async def test_no_auth_header_passes_through(self):
        """Authorizationヘッダーなしのリクエストはそのまま通過する。"""
        app = self._make_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/test")

        # SESSION_COMPROMISED ではないことを確認（認証なしは通過）
        assert resp.status_code != 401 or "SESSION_COMPROMISED" not in resp.text

    async def test_new_session_stores_ip_and_passes(self):
        """初回アクセス（セッション未登録）はIPを記録して通過する。"""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)  # 未登録セッション
        mock_redis.setex = AsyncMock()

        app = self._make_app()
        token = _make_jwt()

        with patch("app.cache._redis", mock_redis):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(
                    "/api/test",
                    headers={"Authorization": f"Bearer {token}"},
                )

        assert resp.status_code == 200
        mock_redis.setex.assert_called_once()

    async def test_same_ip_prefix_passes(self):
        """同じ /8 プレフィックスからのリクエストは通過する。"""
        current_ts = int(time.time())
        stored_data = json.dumps({
            "ip": "10.0.0.1",
            "prefix": "10",
            "ts": current_ts - 10,
        })

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=stored_data)
        mock_redis.setex = AsyncMock()

        app = self._make_app()
        token = _make_jwt()

        with patch("app.cache._redis", mock_redis):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(
                    "/api/test",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "X-Forwarded-For": "10.0.0.99",
                    },
                )

        assert resp.status_code == 200

    async def test_different_ip_prefix_slow_change_passes(self):
        """IPプレフィックスが変わっても5分以上経過していれば通過（モバイル/VPN許容）。"""
        current_ts = int(time.time())
        stored_data = json.dumps({
            "ip": "10.0.0.1",
            "prefix": "10",
            "ts": current_ts - 400,  # 400秒前（5分超）
        })

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=stored_data)
        mock_redis.setex = AsyncMock()

        app = self._make_app()
        token = _make_jwt()

        with patch("app.cache._redis", mock_redis):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(
                    "/api/test",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "X-Forwarded-For": "203.0.113.1",
                    },
                )

        assert resp.status_code == 200

    async def test_impossible_travel_within_window_returns_401(self):
        """5分以内にIPプレフィックスが急変 → 401 SESSION_COMPROMISED を返す。"""
        current_ts = int(time.time())
        stored_data = json.dumps({
            "ip": "10.0.0.1",
            "prefix": "10",
            "ts": current_ts - 60,  # 1分前（5分以内）
        })

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=stored_data)
        mock_redis.setex = AsyncMock()

        app = self._make_app()
        token = _make_jwt()

        with patch("app.cache._redis", mock_redis):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(
                    "/api/test",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "X-Forwarded-For": "185.0.0.1",  # 別プレフィックス（185）
                    },
                )

        assert resp.status_code == 401
        body = resp.json()
        assert body.get("code") == "SESSION_COMPROMISED"

    async def test_session_guard_redis_down_fail_open(self):
        """Redis未接続時は fail-open（通過許可）とする。"""
        app = self._make_app()
        token = _make_jwt()

        with patch("app.cache._redis", None):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(
                    "/api/test",
                    headers={"Authorization": f"Bearer {token}"},
                )

        assert resp.status_code == 200

    async def test_session_guard_skips_health_path(self):
        """ヘルスチェックパスはセッション検証をスキップする。"""
        from fastapi import FastAPI
        from app.middleware.session_guard import SessionGuardMiddleware

        app = FastAPI()
        app.add_middleware(SessionGuardMiddleware)

        @app.get("/health")
        async def health():
            return {"ok": True}

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health")

        assert resp.status_code == 200


# ─────────────────────────────────────────────────────────────────────────────
# IP prefix ユーティリティ関数テスト
# ─────────────────────────────────────────────────────────────────────────────

class TestIpPrefixUtils:
    """_ip_prefix_8 の正確さを検証"""

    def test_ipv4_returns_first_octet(self):
        from app.middleware.session_guard import _ip_prefix_8
        assert _ip_prefix_8("192.168.1.100") == "192"
        assert _ip_prefix_8("10.0.0.1") == "10"
        assert _ip_prefix_8("203.0.113.5") == "203"

    def test_ipv6_returns_first_two_segments(self):
        from app.middleware.session_guard import _ip_prefix_8
        result = _ip_prefix_8("2001:db8::1")
        assert result == "2001:db8"

    def test_different_prefixes_detected_as_different(self):
        from app.middleware.session_guard import _ip_prefix_8
        assert _ip_prefix_8("10.0.0.1") != _ip_prefix_8("185.0.0.1")

    def test_same_prefix_regardless_of_suffix(self):
        from app.middleware.session_guard import _ip_prefix_8
        assert _ip_prefix_8("10.0.0.1") == _ip_prefix_8("10.255.255.255")
