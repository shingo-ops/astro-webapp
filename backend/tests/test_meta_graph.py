"""
Meta Graph API クライアント（app.services.meta_graph）の単体テスト。

httpx.MockTransport を使って Meta Graph API の応答をモック化し、
- ハッピーパス（短期/長期 token 交換、Page list、subscribed_apps、IG 取得）
- Meta エラー応答（OAuthException, GraphMethodException 等）
- タイムアウト・ネットワーク失敗
- 必須環境変数の欠落
を網羅する。

実行:
    pytest backend/tests/test_meta_graph.py -v

変更履歴:
    2026-04-30: Phase 1-D Sprint 2 初版
"""

from __future__ import annotations

import json
from typing import Any, Callable, Optional

import httpx
import pytest

from app.services import meta_graph
from app.services.meta_graph import (
    MetaGraphAPIError,
    MetaGraphError,
    MetaGraphTimeoutError,
    MetaGraphTransportError,
    exchange_code_for_short_token,
    exchange_short_token_for_long_token,
    get_instagram_business_account,
    get_user_name,
    graph_api_version,
    graph_base_url,
    list_user_pages,
    subscribe_page_to_app,
    unsubscribe_page_from_app,
)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _meta_env(monkeypatch):
    """各テストで必要な META_APP_ID / META_APP_SECRET を仕込む。"""
    monkeypatch.setenv("META_APP_ID", "test-app-id-123")
    monkeypatch.setenv("META_APP_SECRET", "test-app-secret-shhh")
    monkeypatch.delenv("META_GRAPH_API_VERSION", raising=False)
    yield


def _make_client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    """MockTransport を持つ AsyncClient を生成する。"""
    transport = httpx.MockTransport(handler)
    return httpx.AsyncClient(transport=transport, timeout=5.0)


def _ok(payload: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, content=json.dumps(payload).encode("utf-8"),
                          headers={"content-type": "application/json"})


def _err(status: int, error_body: dict[str, Any]) -> httpx.Response:
    return httpx.Response(status, content=json.dumps({"error": error_body}).encode("utf-8"),
                          headers={"content-type": "application/json"})


# ---------------------------------------------------------------------------
# config helpers
# ---------------------------------------------------------------------------


def test_graph_api_version_default():
    """環境変数未設定なら v19.0 を返す。"""
    assert graph_api_version() == "v19.0"


def test_graph_api_version_override(monkeypatch):
    """`META_GRAPH_API_VERSION` で切り替え可能。"""
    monkeypatch.setenv("META_GRAPH_API_VERSION", "v20.0")
    assert graph_api_version() == "v20.0"
    assert graph_base_url() == "https://graph.facebook.com/v20.0"


def test_app_id_missing_raises(monkeypatch):
    """`META_APP_ID` 未設定で MetaGraphError。"""
    monkeypatch.delenv("META_APP_ID", raising=False)
    import asyncio
    with pytest.raises(MetaGraphError, match="META_APP_ID"):
        asyncio.get_event_loop().run_until_complete(
            exchange_code_for_short_token("dummy-code", "https://example.com/cb",
                                          client=_make_client(lambda req: _ok({"access_token": "x"})))
        )


# ---------------------------------------------------------------------------
# exchange_code_for_short_token
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exchange_code_happy_path():
    """code → short_token、必要パラメータが付与される。"""
    captured: dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["url"] = str(req.url)
        captured["params"] = dict(req.url.params)
        return _ok({"access_token": "short-uat-xyz", "token_type": "bearer"})

    async with _make_client(handler) as client:
        token = await exchange_code_for_short_token(
            "the-code", "https://app.salesanchor.jp/channels/oauth/callback",
            client=client,
        )
    assert token == "short-uat-xyz"
    assert "/v19.0/oauth/access_token" in captured["url"]
    assert captured["params"]["client_id"] == "test-app-id-123"
    assert captured["params"]["client_secret"] == "test-app-secret-shhh"
    assert captured["params"]["redirect_uri"] == "https://app.salesanchor.jp/channels/oauth/callback"
    assert captured["params"]["code"] == "the-code"


@pytest.mark.asyncio
async def test_exchange_code_meta_oauth_exception():
    """Meta が `OAuthException` を返したら MetaGraphAPIError を raise。"""
    def handler(req: httpx.Request) -> httpx.Response:
        return _err(400, {
            "type": "OAuthException",
            "code": 100,
            "message": "Invalid verification code format.",
            "fbtrace_id": "ABC123",
        })

    async with _make_client(handler) as client:
        with pytest.raises(MetaGraphAPIError) as exc:
            await exchange_code_for_short_token("bad", "https://x/cb", client=client)
    err = exc.value
    assert err.status_code == 400
    assert err.error_type == "OAuthException"
    assert err.error_code == 100
    assert err.fbtrace_id == "ABC123"
    audit = err.to_audit_dict()
    assert audit["error_type"] == "OAuthException"
    # PII (message) は audit_dict に含まれない
    assert "message" not in audit


@pytest.mark.asyncio
async def test_exchange_code_missing_access_token():
    """200 だが access_token を返さない異常応答 → MetaGraphTransportError。"""
    def handler(req: httpx.Request) -> httpx.Response:
        return _ok({"unexpected": "shape"})

    async with _make_client(handler) as client:
        with pytest.raises(MetaGraphTransportError):
            await exchange_code_for_short_token("c", "https://x/cb", client=client)


@pytest.mark.asyncio
async def test_exchange_code_empty_code_raises():
    """空 code は ValueError（HTTP 呼び出しに行かない）。"""
    with pytest.raises(ValueError):
        await exchange_code_for_short_token("", "https://x/cb")


@pytest.mark.asyncio
async def test_exchange_code_timeout():
    """httpx.TimeoutException → MetaGraphTimeoutError。"""
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out", request=req)

    async with _make_client(handler) as client:
        with pytest.raises(MetaGraphTimeoutError):
            await exchange_code_for_short_token("c", "https://x/cb", client=client)


@pytest.mark.asyncio
async def test_exchange_code_non_json_body():
    """非 JSON 応答 → MetaGraphTransportError。"""
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>down</html>",
                              headers={"content-type": "text/html"})

    async with _make_client(handler) as client:
        with pytest.raises(MetaGraphTransportError):
            await exchange_code_for_short_token("c", "https://x/cb", client=client)


# ---------------------------------------------------------------------------
# exchange_short_token_for_long_token
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exchange_long_token_happy_path():
    """fb_exchange_token grant で長期化成功、expires_in を返す。"""
    captured: dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["params"] = dict(req.url.params)
        return _ok({"access_token": "long-uat-zzz", "expires_in": 5183944,
                    "token_type": "bearer"})

    async with _make_client(handler) as client:
        result = await exchange_short_token_for_long_token("short-uat", client=client)
    assert result["access_token"] == "long-uat-zzz"
    assert result["expires_in"] == 5183944
    assert result["token_type"] == "bearer"
    assert captured["params"]["grant_type"] == "fb_exchange_token"
    assert captured["params"]["fb_exchange_token"] == "short-uat"


@pytest.mark.asyncio
async def test_exchange_long_token_no_expires_in():
    """expires_in が無い場合は None を入れる（壊れない）。"""
    def handler(req: httpx.Request) -> httpx.Response:
        return _ok({"access_token": "long-no-exp"})

    async with _make_client(handler) as client:
        result = await exchange_short_token_for_long_token("short", client=client)
    assert result["access_token"] == "long-no-exp"
    assert result["expires_in"] is None


# ---------------------------------------------------------------------------
# list_user_pages
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_user_pages_happy_path():
    """`/me/accounts` から複数 Page + IG 紐付けを返す。"""
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.params["access_token"] == "long-uat"
        return _ok({"data": [
            {"id": "111", "name": "Page A", "access_token": "page-a-token",
             "instagram_business_account": {"id": "ig-1"}},
            {"id": "222", "name": "Page B", "access_token": "page-b-token"},
        ]})

    async with _make_client(handler) as client:
        pages = await list_user_pages("long-uat", client=client)
    assert len(pages) == 2
    assert pages[0]["id"] == "111"
    assert pages[0]["access_token"] == "page-a-token"
    assert pages[0]["instagram_business_account"]["id"] == "ig-1"
    assert pages[1]["instagram_business_account"] is None


@pytest.mark.asyncio
async def test_list_user_pages_empty():
    """data=[] の場合は空 list。"""
    def handler(req: httpx.Request) -> httpx.Response:
        return _ok({"data": []})
    async with _make_client(handler) as client:
        pages = await list_user_pages("uat", client=client)
    assert pages == []


@pytest.mark.asyncio
async def test_list_user_pages_data_not_a_list():
    """`data` が list でない異常 → MetaGraphTransportError。"""
    def handler(req: httpx.Request) -> httpx.Response:
        return _ok({"data": {"oops": "object"}})
    async with _make_client(handler) as client:
        with pytest.raises(MetaGraphTransportError):
            await list_user_pages("uat", client=client)


# ---------------------------------------------------------------------------
# get_instagram_business_account
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_instagram_business_account_happy_path():
    """Page → IG Business Account を返却。"""
    def handler(req: httpx.Request) -> httpx.Response:
        assert "instagram_business_account" in req.url.params["fields"]
        return _ok({"instagram_business_account": {"id": "ig-99", "username": "highlifejpn"}})

    async with _make_client(handler) as client:
        iba = await get_instagram_business_account("page-1", "page-token", client=client)
    assert iba == {"id": "ig-99", "username": "highlifejpn"}


@pytest.mark.asyncio
async def test_get_instagram_business_account_not_linked():
    """Page に IG が紐付いていない → None を返す。"""
    def handler(req: httpx.Request) -> httpx.Response:
        return _ok({})  # IG キー無し

    async with _make_client(handler) as client:
        iba = await get_instagram_business_account("page-1", "page-token", client=client)
    assert iba is None


# ---------------------------------------------------------------------------
# subscribe_page_to_app
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_subscribe_page_to_app_default_fields():
    """既定 subscribed_fields が POST される。"""
    captured: dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["method"] = req.method
        captured["params"] = dict(req.url.params)
        captured["body"] = req.read().decode("utf-8")
        return _ok({"success": True})

    async with _make_client(handler) as client:
        fields = await subscribe_page_to_app("page-1", "page-token", client=client)

    assert captured["method"] == "POST"
    assert captured["params"]["access_token"] == "page-token"
    # form 値: subscribed_fields=messages,messaging_postbacks,...
    assert "subscribed_fields=messages" in captured["body"]
    assert "messaging_postbacks" in captured["body"]
    assert "messages" in fields
    assert "messaging_postbacks" in fields


@pytest.mark.asyncio
async def test_subscribe_page_to_app_custom_fields():
    """custom subscribed_fields を渡せる。"""
    captured: dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["body"] = req.read().decode("utf-8")
        return _ok({"success": True})

    async with _make_client(handler) as client:
        fields = await subscribe_page_to_app(
            "page-1", "page-token",
            subscribed_fields=("messages", "messaging_postbacks"),
            client=client,
        )
    assert fields == ["messages", "messaging_postbacks"]
    assert "messages%2Cmessaging_postbacks" in captured["body"] or \
           "messages,messaging_postbacks" in captured["body"]


@pytest.mark.asyncio
async def test_subscribe_page_to_app_success_false():
    """success=false なら MetaGraphTransportError。"""
    def handler(req: httpx.Request) -> httpx.Response:
        return _ok({"success": False})
    async with _make_client(handler) as client:
        with pytest.raises(MetaGraphTransportError):
            await subscribe_page_to_app("page-1", "page-token", client=client)


@pytest.mark.asyncio
async def test_subscribe_page_to_app_meta_error():
    """Meta が GraphMethodException を返したら MetaGraphAPIError。"""
    def handler(req: httpx.Request) -> httpx.Response:
        return _err(400, {
            "type": "GraphMethodException",
            "code": 100,
            "message": "Unsupported post request",
        })
    async with _make_client(handler) as client:
        with pytest.raises(MetaGraphAPIError) as exc:
            await subscribe_page_to_app("page-1", "bad-token", client=client)
    assert exc.value.error_type == "GraphMethodException"


# ---------------------------------------------------------------------------
# unsubscribe_page_from_app
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unsubscribe_page_from_app_happy_path():
    captured: dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["method"] = req.method
        return _ok({"success": True})

    async with _make_client(handler) as client:
        ok = await unsubscribe_page_from_app("page-1", "page-token", client=client)
    assert ok is True
    assert captured["method"] == "DELETE"


@pytest.mark.asyncio
async def test_unsubscribe_page_from_app_returns_false_when_meta_says_so():
    """Meta が success=false を返すと False。"""
    def handler(req: httpx.Request) -> httpx.Response:
        return _ok({"success": False})
    async with _make_client(handler) as client:
        ok = await unsubscribe_page_from_app("page-1", "page-token", client=client)
    assert ok is False


# ---------------------------------------------------------------------------
# 入力検証
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_user_pages_empty_token_raises():
    with pytest.raises(ValueError):
        await list_user_pages("")


@pytest.mark.asyncio
async def test_get_instagram_empty_args_raise():
    with pytest.raises(ValueError):
        await get_instagram_business_account("", "token")
    with pytest.raises(ValueError):
        await get_instagram_business_account("page", "")


@pytest.mark.asyncio
async def test_subscribe_empty_args_raise():
    with pytest.raises(ValueError):
        await subscribe_page_to_app("", "token")
    with pytest.raises(ValueError):
        await subscribe_page_to_app("page", "")


# ---------------------------------------------------------------------------
# Phase 1-E F15-S6 / F15-FU2: get_user_name (Page Scoped User → 表示名)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_user_name_happy_path():
    """正常系: Graph API が name を返したらそのまま返す + 正しいパス・パラメータ。"""
    captured: dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["url"] = str(req.url)
        captured["params"] = dict(req.url.params)
        return _ok({"name": "山田 太郎", "id": "PSID-1"})

    async with _make_client(handler) as client:
        name = await get_user_name("PSID-1", "page-token-xyz", client=client)

    assert name == "山田 太郎"
    assert "/v19.0/PSID-1" in captured["url"]
    assert captured["params"]["fields"] == "name"
    assert captured["params"]["access_token"] == "page-token-xyz"


@pytest.mark.asyncio
async def test_get_user_name_returns_none_when_name_missing():
    """name フィールドが空 / 欠落なら None を返す。"""
    def handler(req: httpx.Request) -> httpx.Response:
        return _ok({"id": "PSID-1"})  # name 欠落

    async with _make_client(handler) as client:
        name = await get_user_name("PSID-1", "page-token", client=client)
    assert name is None


@pytest.mark.asyncio
async def test_get_user_name_returns_none_when_name_is_empty_string():
    """name が空文字なら None。"""
    def handler(req: httpx.Request) -> httpx.Response:
        return _ok({"name": "", "id": "PSID-1"})

    async with _make_client(handler) as client:
        name = await get_user_name("PSID-1", "page-token", client=client)
    assert name is None


@pytest.mark.asyncio
async def test_get_user_name_propagates_graph_api_error():
    """Meta が error を返したら MetaGraphAPIError が伝播（呼び出し側で握り潰す前提）。"""
    def handler(req: httpx.Request) -> httpx.Response:
        return _err(403, {
            "message": "Permissions error",
            "type": "OAuthException",
            "code": 200,
        })

    async with _make_client(handler) as client:
        with pytest.raises(MetaGraphAPIError) as exc:
            await get_user_name("PSID-1", "bad-token", client=client)
    assert exc.value.error_code == 200


@pytest.mark.asyncio
async def test_get_user_name_empty_args_raise():
    with pytest.raises(ValueError):
        await get_user_name("", "token")
    with pytest.raises(ValueError):
        await get_user_name("PSID-1", "")
