"""
app.services.oauth_state の単体テスト。

実 Redis は使わず、`app.cache._redis` を AsyncMock で差し替える。
state 値は推測不可・one-time 使用・Fernet 暗号化往復を確認する。

実行:
    pytest backend/tests/test_oauth_state.py -v

変更履歴:
    2026-04-30: Phase 1-D Sprint 2 初版
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.fernet import Fernet

from app.services import encryption, oauth_state
from app.services.oauth_state import (
    OAuthStateError,
    consume_state,
    generate_state,
    issue_state,
)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _fernet_key(monkeypatch):
    """encryption に有効な Fernet 鍵をセット。"""
    encryption.reset_cache()
    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("METADATA_FERNET_KEY", key)
    yield
    encryption.reset_cache()


def _make_pipeline_mock(get_return_value: object) -> MagicMock:
    """`async with redis.pipeline(transaction=True)` パターンを再現する MagicMock。"""
    pipe = MagicMock()
    pipe.get = MagicMock(return_value=None)
    pipe.delete = MagicMock(return_value=None)
    pipe.execute = AsyncMock(return_value=[get_return_value, 1])
    # `async with redis.pipeline(transaction=True) as pipe:` をサポート
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=pipe)
    cm.__aexit__ = AsyncMock(return_value=None)
    return cm, pipe


# ---------------------------------------------------------------------------
# generate_state
# ---------------------------------------------------------------------------


def test_generate_state_unique_each_call():
    """毎回違う state（推測不可能）。"""
    seen = {generate_state() for _ in range(50)}
    assert len(seen) == 50


def test_generate_state_url_safe_length():
    """state は URL-safe で十分に長い（>= 32 文字）。"""
    s = generate_state()
    assert len(s) >= 32
    # urlsafe charset: [A-Za-z0-9_-]
    assert all(c.isalnum() or c in "-_" for c in s)


# ---------------------------------------------------------------------------
# issue_state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_issue_state_persists_encrypted_payload_with_ttl():
    """issue_state は Redis に setex で 10 分 TTL で書き込む。"""
    redis_mock = AsyncMock()
    with patch("app.services.oauth_state.get_redis", return_value=redis_mock):
        result = await issue_state(tenant_id=4, staff_id=42)

    assert "state" in result
    assert isinstance(result["state"], str) and len(result["state"]) >= 32
    assert result["ttl_seconds"] == 600
    assert "expires_at" in result

    # Redis 書き込み引数の検証
    redis_mock.setex.assert_called_once()
    args = redis_mock.setex.call_args.args
    key, ttl, value = args
    assert key.startswith("meta_oauth_state:")
    assert key.endswith(result["state"])
    assert ttl == 600
    assert isinstance(value, str)
    # value は Fernet ciphertext（平文 tenant_id を含まない）
    assert "tenant_id" not in value
    assert "4" not in value or len(value) > 80  # ざっくり: ciphertext は十分長い


@pytest.mark.asyncio
async def test_issue_state_payload_is_recoverable():
    """書き込んだ ciphertext を復号すると tenant_id / staff_id が戻る。"""
    redis_mock = AsyncMock()
    captured = {}

    async def _setex(key, ttl, value):
        captured["key"] = key
        captured["ttl"] = ttl
        captured["value"] = value

    redis_mock.setex.side_effect = _setex

    with patch("app.services.oauth_state.get_redis", return_value=redis_mock):
        await issue_state(tenant_id=7, staff_id=99)

    payload = json.loads(encryption.decrypt(captured["value"]))
    assert payload["tenant_id"] == 7
    assert payload["staff_id"] == 99
    assert "created_at" in payload
    assert "nonce" in payload


@pytest.mark.asyncio
async def test_issue_state_redis_unavailable_raises():
    """Redis 未接続なら OAuthStateError。"""
    with patch("app.services.oauth_state.get_redis", return_value=None):
        with pytest.raises(OAuthStateError):
            await issue_state(tenant_id=1, staff_id=1)


@pytest.mark.asyncio
async def test_issue_state_validates_inputs():
    redis_mock = AsyncMock()
    with patch("app.services.oauth_state.get_redis", return_value=redis_mock):
        with pytest.raises(ValueError):
            await issue_state(tenant_id=1, staff_id=1, ttl_seconds=0)
        with pytest.raises(ValueError):
            await issue_state(tenant_id=1, staff_id=1, ttl_seconds=-5)


@pytest.mark.asyncio
async def test_issue_state_custom_ttl():
    redis_mock = AsyncMock()
    with patch("app.services.oauth_state.get_redis", return_value=redis_mock):
        result = await issue_state(tenant_id=1, staff_id=1, ttl_seconds=120)
    assert result["ttl_seconds"] == 120
    args = redis_mock.setex.call_args.args
    assert args[1] == 120


# ---------------------------------------------------------------------------
# consume_state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_consume_state_happy_path_returns_payload_and_deletes_key():
    """正しい state なら payload を返し、Redis から削除する。"""
    payload = {
        "tenant_id": 4,
        "staff_id": 42,
        "created_at": "2026-04-30T12:00:00+00:00",
        "nonce": "abcd1234",
    }
    encrypted = encryption.encrypt(json.dumps(payload, separators=(",", ":")))

    redis_mock = AsyncMock()
    cm, pipe = _make_pipeline_mock(encrypted)
    redis_mock.pipeline = MagicMock(return_value=cm)

    with patch("app.services.oauth_state.get_redis", return_value=redis_mock):
        result = await consume_state("the-state")

    assert result is not None
    assert result["tenant_id"] == 4
    assert result["staff_id"] == 42
    # GET と DEL が両方呼ばれている
    pipe.get.assert_called_once()
    pipe.delete.assert_called_once()
    pipe.execute.assert_awaited()


@pytest.mark.asyncio
async def test_consume_state_unknown_state_returns_none():
    """Redis に該当なしなら None。"""
    redis_mock = AsyncMock()
    cm, pipe = _make_pipeline_mock(None)
    redis_mock.pipeline = MagicMock(return_value=cm)

    with patch("app.services.oauth_state.get_redis", return_value=redis_mock):
        result = await consume_state("missing-state")
    assert result is None


@pytest.mark.asyncio
async def test_consume_state_empty_string_returns_none():
    """空 state は HTTP 呼び出しに行かず None を返す。"""
    result = await consume_state("")
    assert result is None


@pytest.mark.asyncio
async def test_consume_state_redis_unavailable_raises_error():
    """Redis 未接続は OAuthStateError を raise する（#30: Redis障害とstate期限切れを区別）。"""
    from app.services.oauth_state import OAuthStateError
    with patch("app.services.oauth_state.get_redis", return_value=None):
        with pytest.raises(OAuthStateError):
            await consume_state("any")


@pytest.mark.asyncio
async def test_consume_state_garbled_ciphertext_returns_none():
    """Fernet 復号失敗 → None（鍵ローテーション後など）。"""
    redis_mock = AsyncMock()
    cm, pipe = _make_pipeline_mock("not-a-valid-fernet-ciphertext")
    redis_mock.pipeline = MagicMock(return_value=cm)

    with patch("app.services.oauth_state.get_redis", return_value=redis_mock):
        result = await consume_state("the-state")
    assert result is None


@pytest.mark.asyncio
async def test_consume_state_payload_missing_required_keys_returns_none():
    """tenant_id / staff_id が無い壊れた payload → None。"""
    bogus = encryption.encrypt(json.dumps({"foo": "bar"}))
    redis_mock = AsyncMock()
    cm, pipe = _make_pipeline_mock(bogus)
    redis_mock.pipeline = MagicMock(return_value=cm)

    with patch("app.services.oauth_state.get_redis", return_value=redis_mock):
        result = await consume_state("the-state")
    assert result is None


@pytest.mark.asyncio
async def test_consume_state_one_time_use_pattern():
    """同じ state を 2 回 consume → 2 回目は None（pipeline で削除されるため）。"""
    payload = {"tenant_id": 1, "staff_id": 2, "created_at": "x", "nonce": "y"}
    encrypted = encryption.encrypt(json.dumps(payload, separators=(",", ":")))

    redis_mock = AsyncMock()
    # 1 回目: payload あり、2 回目: None
    call_count = {"n": 0}

    def make_pipeline(transaction=True):
        cm_inner = MagicMock()
        pipe_inner = MagicMock()
        pipe_inner.get = MagicMock(return_value=None)
        pipe_inner.delete = MagicMock(return_value=None)

        async def _execute():
            call_count["n"] += 1
            return [encrypted if call_count["n"] == 1 else None, 1]

        pipe_inner.execute = _execute
        cm_inner.__aenter__ = AsyncMock(return_value=pipe_inner)
        cm_inner.__aexit__ = AsyncMock(return_value=None)
        return cm_inner

    redis_mock.pipeline = MagicMock(side_effect=make_pipeline)

    with patch("app.services.oauth_state.get_redis", return_value=redis_mock):
        first = await consume_state("the-state")
        second = await consume_state("the-state")

    assert first is not None
    assert first["tenant_id"] == 1
    assert second is None
