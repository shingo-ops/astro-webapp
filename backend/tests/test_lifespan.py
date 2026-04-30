"""
Phase 1-E F5: Backend lifespan unit tests

main.py の lifespan で実装されている METADATA_FERNET_KEY のチェック挙動を
ENFORCE_METADATA_FERNET_KEY 切替式で網羅するテスト。

カバレッジ:
- _fernet_fail_fast_enforced() の真偽値判定（truthy / falsy / 大文字小文字）
- lifespan が EncryptionConfigurationError を warning ログだけにする既定動作
- ENFORCE=1 で lifespan が raise する動作
- encryption._get_default_fernet() のキャッシュ動作
- Redis init/close が呼ばれる動作（モック）

既存 test_encryption.py との被りは避け、main.py の lifespan + フラグ判定に集中。
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest
from cryptography.fernet import Fernet


# ---------------------------------------------------------------------------
# _fernet_fail_fast_enforced() 単体テスト
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "value",
    ["1", "true", "yes", "on", "True", "YES", "ON", "TRUE", "  1  ", "  true "],
)
def test_fernet_fail_fast_enforced_truthy(monkeypatch, value: str) -> None:
    """ENFORCE_METADATA_FERNET_KEY が truthy 値で True を返す（大文字小文字・空白を許容）"""
    monkeypatch.setenv("ENFORCE_METADATA_FERNET_KEY", value)
    from app.main import _fernet_fail_fast_enforced

    assert _fernet_fail_fast_enforced() is True


@pytest.mark.parametrize(
    "value",
    ["", "0", "false", "no", "off", "False", "NO", "OFF", "random", "2", "yesno"],
)
def test_fernet_fail_fast_enforced_falsy(monkeypatch, value: str) -> None:
    """ENFORCE_METADATA_FERNET_KEY が falsy 値・未設定相当で False を返す"""
    monkeypatch.setenv("ENFORCE_METADATA_FERNET_KEY", value)
    from app.main import _fernet_fail_fast_enforced

    assert _fernet_fail_fast_enforced() is False


def test_fernet_fail_fast_enforced_unset(monkeypatch) -> None:
    """ENFORCE_METADATA_FERNET_KEY が未設定（環境変数なし）で False を返す"""
    monkeypatch.delenv("ENFORCE_METADATA_FERNET_KEY", raising=False)
    from app.main import _fernet_fail_fast_enforced

    assert _fernet_fail_fast_enforced() is False


# ---------------------------------------------------------------------------
# lifespan の挙動テスト（async context manager 直接呼び出し）
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_lifespan_with_valid_key_succeeds(monkeypatch) -> None:
    """正常な Fernet 鍵が設定されていれば lifespan が成功して yield する"""
    monkeypatch.setenv("METADATA_FERNET_KEY", Fernet.generate_key().decode())
    monkeypatch.delenv("ENFORCE_METADATA_FERNET_KEY", raising=False)

    # encryption モジュールのキャッシュをクリア（前テスト影響を排除）
    from app.services import encryption as _encryption
    _encryption._get_default_fernet.cache_clear()

    # init_redis / close_redis をモック化
    with patch("app.main.init_redis", new=AsyncMock()) as mock_init, \
         patch("app.main.close_redis", new=AsyncMock()) as mock_close:
        from app.main import lifespan
        from fastapi import FastAPI
        app = FastAPI()
        async with lifespan(app):
            mock_init.assert_awaited_once()
            assert not mock_close.called
        mock_close.assert_awaited_once()


@pytest.mark.asyncio
async def test_lifespan_with_missing_key_no_enforce_logs_warning(monkeypatch, caplog) -> None:
    """鍵未設定 + ENFORCE 無効 → warning ログを出して startup 継続"""
    monkeypatch.delenv("METADATA_FERNET_KEY", raising=False)
    monkeypatch.delenv("ENFORCE_METADATA_FERNET_KEY", raising=False)

    from app.services import encryption as _encryption
    _encryption._get_default_fernet.cache_clear()

    with patch("app.main.init_redis", new=AsyncMock()), \
         patch("app.main.close_redis", new=AsyncMock()), \
         caplog.at_level(logging.WARNING, logger="app.main"):
        from app.main import lifespan
        from fastapi import FastAPI
        app = FastAPI()
        async with lifespan(app):
            pass

    # warning ログが出ているはず
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("METADATA_FERNET_KEY" in r.getMessage() for r in warnings)


@pytest.mark.asyncio
async def test_lifespan_with_missing_key_enforce_raises(monkeypatch) -> None:
    """鍵未設定 + ENFORCE=1 → EncryptionConfigurationError で startup 失敗"""
    monkeypatch.delenv("METADATA_FERNET_KEY", raising=False)
    monkeypatch.setenv("ENFORCE_METADATA_FERNET_KEY", "1")

    from app.services import encryption as _encryption
    _encryption._get_default_fernet.cache_clear()

    with patch("app.main.init_redis", new=AsyncMock()), \
         patch("app.main.close_redis", new=AsyncMock()):
        from app.main import lifespan
        from fastapi import FastAPI
        app = FastAPI()
        with pytest.raises(_encryption.EncryptionConfigurationError):
            async with lifespan(app):
                pytest.fail("lifespan must not yield when key is missing and enforce=1")


@pytest.mark.asyncio
async def test_lifespan_with_invalid_key_enforce_raises(monkeypatch) -> None:
    """不正な Fernet 鍵 + ENFORCE=1 → EncryptionConfigurationError で startup 失敗"""
    monkeypatch.setenv("METADATA_FERNET_KEY", "not-a-valid-fernet-key")
    monkeypatch.setenv("ENFORCE_METADATA_FERNET_KEY", "1")

    from app.services import encryption as _encryption
    _encryption._get_default_fernet.cache_clear()

    with patch("app.main.init_redis", new=AsyncMock()), \
         patch("app.main.close_redis", new=AsyncMock()):
        from app.main import lifespan
        from fastapi import FastAPI
        app = FastAPI()
        with pytest.raises(_encryption.EncryptionConfigurationError):
            async with lifespan(app):
                pytest.fail("lifespan must not yield when key is invalid and enforce=1")


@pytest.mark.asyncio
async def test_lifespan_with_invalid_key_no_enforce_logs_warning(monkeypatch, caplog) -> None:
    """不正な Fernet 鍵 + ENFORCE 無効 → warning ログを出して startup 継続"""
    monkeypatch.setenv("METADATA_FERNET_KEY", "not-a-valid-fernet-key")
    monkeypatch.delenv("ENFORCE_METADATA_FERNET_KEY", raising=False)

    from app.services import encryption as _encryption
    _encryption._get_default_fernet.cache_clear()

    with patch("app.main.init_redis", new=AsyncMock()), \
         patch("app.main.close_redis", new=AsyncMock()), \
         caplog.at_level(logging.WARNING, logger="app.main"):
        from app.main import lifespan
        from fastapi import FastAPI
        app = FastAPI()
        async with lifespan(app):
            pass

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("METADATA_FERNET_KEY" in r.getMessage() for r in warnings)


@pytest.mark.asyncio
async def test_lifespan_redis_init_close_called_in_order(monkeypatch) -> None:
    """正常系: init_redis が yield 前、close_redis が yield 後に 1 回ずつ呼ばれる"""
    monkeypatch.setenv("METADATA_FERNET_KEY", Fernet.generate_key().decode())

    from app.services import encryption as _encryption
    _encryption._get_default_fernet.cache_clear()

    init_mock = AsyncMock()
    close_mock = AsyncMock()
    call_order: list[str] = []
    init_mock.side_effect = lambda: call_order.append("init")
    close_mock.side_effect = lambda: call_order.append("close")

    with patch("app.main.init_redis", new=init_mock), \
         patch("app.main.close_redis", new=close_mock):
        from app.main import lifespan
        from fastapi import FastAPI
        app = FastAPI()
        async with lifespan(app):
            call_order.append("yielded")

    assert call_order == ["init", "yielded", "close"]


# ---------------------------------------------------------------------------
# encryption._get_default_fernet() のキャッシュ動作（lifespan で利用される観点）
# ---------------------------------------------------------------------------

def test_get_default_fernet_caches_after_lifespan(monkeypatch) -> None:
    """lifespan で呼んだ後、encrypt/decrypt を呼ぶときに同じインスタンスが再利用される"""
    monkeypatch.setenv("METADATA_FERNET_KEY", Fernet.generate_key().decode())

    from app.services import encryption as _encryption
    _encryption._get_default_fernet.cache_clear()

    f1 = _encryption._get_default_fernet()
    f2 = _encryption._get_default_fernet()
    assert f1 is f2  # lru_cache でキャッシュされている


def test_get_default_fernet_cache_cleared_after_env_change(monkeypatch) -> None:
    """環境変数変更後 cache_clear() で新しい Fernet が再生成される"""
    monkeypatch.setenv("METADATA_FERNET_KEY", Fernet.generate_key().decode())
    from app.services import encryption as _encryption
    _encryption._get_default_fernet.cache_clear()
    f1 = _encryption._get_default_fernet()

    monkeypatch.setenv("METADATA_FERNET_KEY", Fernet.generate_key().decode())
    _encryption._get_default_fernet.cache_clear()
    f2 = _encryption._get_default_fernet()

    assert f1 is not f2  # 新しいインスタンスになっている
