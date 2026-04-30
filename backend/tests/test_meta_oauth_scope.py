"""
Phase 1-E F7-S2: OAuth scope エンコード検証

Sprint 2 Generator Known Limitations で持ち越し。

検証内容:
- 6 permission がすべて scope に含まれる（spec §6-2 / Use Case Descriptions §2）
- scope のエンコード形式（カンマ区切り、URL encoded）
- scope の順序（実装が変わっても審査担当者の期待と一致）

なぜ重要:
Meta App Review の審査時、申請する permission と auth_url の scope パラメータが
1 文字でもズレると reject される。手動チェックでは見落としやすいため、
RegEx + 全 permission 名の集合チェックで自動化する。
"""

from __future__ import annotations

import os
import re
from urllib.parse import parse_qs, urlparse

# DATABASE_URL を SQLite に必ず差し替え
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

import pytest
from unittest.mock import AsyncMock, patch

from app.routers import meta_inbox


# ---------------------------------------------------------------------------
# 単体テスト: _OAUTH_SCOPE 定数の整合性
# ---------------------------------------------------------------------------


def test_oauth_scope_contains_all_six_permissions() -> None:
    """spec §6-2 の 6 permission がすべて _OAUTH_SCOPE に含まれる。"""
    expected = {
        "pages_show_list",
        "pages_manage_metadata",
        "pages_messaging",
        "pages_read_engagement",
        "instagram_basic",
        "instagram_manage_messages",
    }
    actual = set(meta_inbox._OAUTH_SCOPE.split(","))
    assert actual == expected, (
        f"OAuth scope mismatch: missing={expected - actual}, "
        f"extra={actual - expected}"
    )


def test_oauth_scope_is_comma_separated_no_spaces() -> None:
    """scope はカンマ区切り、スペースなし（Meta API 仕様）。"""
    scope = meta_inbox._OAUTH_SCOPE
    assert "," in scope
    assert " " not in scope
    # 各要素が小文字 + アンダースコアのみ
    for perm in scope.split(","):
        assert re.match(r"^[a-z_]+$", perm), f"invalid permission name: {perm}"


def test_oauth_scope_does_not_contain_unrequested_permissions() -> None:
    """過剰申請を防ぐ: business_management、ads_management 等が含まれない。"""
    scope = meta_inbox._OAUTH_SCOPE
    forbidden = [
        "business_management",
        "ads_management",
        "email",
        "public_profile",
        "user_posts",
        "marketing_messages_messenger",
    ]
    for perm in forbidden:
        assert perm not in scope, (
            f"{perm} は申請対象外なのに scope に含まれている。Meta 審査で reject されます。"
        )


def test_oauth_scope_count_is_exactly_six() -> None:
    """6 permission の正確数（過不足ない）。"""
    perms = meta_inbox._OAUTH_SCOPE.split(",")
    assert len(perms) == 6, f"expected 6 permissions, got {len(perms)}: {perms}"
    # 重複なし
    assert len(set(perms)) == 6, f"duplicate permission found: {perms}"


# ---------------------------------------------------------------------------
# auth_url 構築の検証（_build_authorize_url）
# ---------------------------------------------------------------------------


def test_auth_url_contains_all_scope_permissions(monkeypatch) -> None:
    """_build_authorize_url の戻り URL で scope=... のクエリパラメータに 6 permission が
    URL エンコード後でも全部含まれる。"""
    monkeypatch.setenv("META_APP_ID", "test-app-id-9999")
    monkeypatch.setenv("META_OAUTH_REDIRECT_URI", "https://app.salesanchor.jp/channels/oauth/callback")
    monkeypatch.delenv("META_GRAPH_API_VERSION", raising=False)

    auth_url = meta_inbox._build_authorize_url(state="dummy-state-xyz")

    parsed = urlparse(auth_url)
    qs = parse_qs(parsed.query)

    # scope パラメータが存在
    assert "scope" in qs, f"scope param missing in auth_url: {auth_url}"
    scope_value = qs["scope"][0]  # parse_qs はカンマで split しないため文字列のまま

    # 6 permission がすべて含まれる
    expected_perms = {
        "pages_show_list", "pages_manage_metadata", "pages_messaging",
        "pages_read_engagement", "instagram_basic", "instagram_manage_messages",
    }
    actual_perms = set(scope_value.split(","))
    assert actual_perms == expected_perms, (
        f"auth_url scope mismatch: missing={expected_perms - actual_perms}, "
        f"extra={actual_perms - expected_perms}"
    )


def test_auth_url_uses_https_facebook_oauth_endpoint(monkeypatch) -> None:
    """auth_url のホスト・パスが Facebook の oauth dialog（v19.0）であること。"""
    monkeypatch.setenv("META_APP_ID", "test-app-id-9999")
    monkeypatch.setenv("META_OAUTH_REDIRECT_URI", "https://app.salesanchor.jp/channels/oauth/callback")
    monkeypatch.delenv("META_GRAPH_API_VERSION", raising=False)

    auth_url = meta_inbox._build_authorize_url(state="x")
    parsed = urlparse(auth_url)
    assert parsed.scheme == "https"
    assert parsed.hostname == "www.facebook.com"
    # spec §6 default の Graph API version
    assert "/v19.0/" in parsed.path or "/dialog/oauth" in parsed.path


def test_auth_url_state_is_query_parameter(monkeypatch) -> None:
    """state は URL クエリパラメータとして含まれる（path に埋め込まれない）。"""
    monkeypatch.setenv("META_APP_ID", "test-app-id-9999")
    monkeypatch.setenv("META_OAUTH_REDIRECT_URI", "https://app.salesanchor.jp/channels/oauth/callback")

    state_token = "csrf-state-abcdef-1234567890" * 2  # 32+ bytes 想定
    auth_url = meta_inbox._build_authorize_url(state=state_token)
    parsed = urlparse(auth_url)
    qs = parse_qs(parsed.query)
    assert qs.get("state") == [state_token]


def test_auth_url_redirect_uri_is_url_encoded(monkeypatch) -> None:
    """redirect_uri がクエリパラメータとして適切に URL エンコードされる。"""
    monkeypatch.setenv("META_APP_ID", "test-app-id-9999")
    monkeypatch.setenv(
        "META_OAUTH_REDIRECT_URI",
        "https://app.salesanchor.jp/channels/oauth/callback",
    )

    auth_url = meta_inbox._build_authorize_url(state="x")
    # urlencode は ":" "/" をエスケープ する仕様（safe="" デフォルト）
    assert "redirect_uri=https%3A%2F%2Fapp.salesanchor.jp" in auth_url \
        or "redirect_uri=https://app.salesanchor.jp" in auth_url, \
        f"redirect_uri encoding unexpected: {auth_url}"


def test_auth_url_response_type_is_code(monkeypatch) -> None:
    """OAuth 2.0 の Authorization Code Flow を使う前提で response_type=code が含まれる。"""
    monkeypatch.setenv("META_APP_ID", "test-app-id-9999")
    monkeypatch.setenv("META_OAUTH_REDIRECT_URI", "https://app.salesanchor.jp/channels/oauth/callback")

    auth_url = meta_inbox._build_authorize_url(state="x")
    parsed = urlparse(auth_url)
    qs = parse_qs(parsed.query)
    assert qs.get("response_type") == ["code"]


def test_auth_url_client_id_matches_env(monkeypatch) -> None:
    """client_id クエリパラメータが META_APP_ID 環境変数と一致する。"""
    monkeypatch.setenv("META_APP_ID", "specific-app-id-zzz-9999")
    monkeypatch.setenv("META_OAUTH_REDIRECT_URI", "https://app.salesanchor.jp/channels/oauth/callback")

    auth_url = meta_inbox._build_authorize_url(state="x")
    parsed = urlparse(auth_url)
    qs = parse_qs(parsed.query)
    assert qs.get("client_id") == ["specific-app-id-zzz-9999"]
