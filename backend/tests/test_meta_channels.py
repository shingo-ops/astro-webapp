"""
backend/app/routers/meta_inbox.py の `GET /api/v1/meta/channels` 統合テスト
（Phase 1-D Sprint 3）。

`test_meta_oauth_endpoints.py` と同じ構成（最小 FastAPI app + SQLite + dependency
override）で、Channels 一覧 endpoint の挙動を網羅する。

カバー:
- 接続済 0 件で empty list
- 1 件で正しい payload（page_access_token は絶対に含めない）
- include_inactive=false（既定）で is_active=FALSE 行を除外
- include_inactive=true で全件返却
- 複数件で connected_at DESC ソート
- tenant 分離（自テナントの行のみ返却）

実行:
    pytest backend/tests/test_meta_channels.py -v

変更履歴:
    2026-04-30: Phase 1-D Sprint 3 初版
"""

from __future__ import annotations

import json
import os
from contextlib import ExitStack
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

# DATABASE_URL を SQLite に必ず差し替え（モジュール import 順の罠回避）
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.auth.dependencies import (
    get_current_tenant,
    get_current_user,
)
from app.database import get_db
from app.routers import meta_inbox
from app.services import encryption


# ---------------------------------------------------------------------------
# fixtures（`test_meta_oauth_endpoints.py` の構造を踏襲）
# ---------------------------------------------------------------------------


_ALL_PERMS = {"channels.view", "channels.manage", "messaging.view", "messaging.send"}
_VIEW_ONLY_PERMS = {"channels.view"}


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    @event.listens_for(eng.sync_engine, "connect")
    def _setup(dbapi_conn, _):
        dbapi_conn.create_function("NOW", 0, lambda: "2026-04-30 12:00:00+00:00")
        dbapi_conn.execute("PRAGMA foreign_keys = ON")

    async with eng.begin() as conn:
        # tenant_meta_config（migration 040 を SQLite 用に縮小。ADR-041 で granted_scopes 追加）
        await conn.execute(text("""
            CREATE TABLE tenant_meta_config (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id INTEGER NOT NULL,
                page_id VARCHAR(50) NOT NULL,
                page_name VARCHAR(200) NOT NULL,
                page_access_token_encrypted BLOB NOT NULL,
                page_token_expires_at TIMESTAMP,
                instagram_business_account_id VARCHAR(50),
                instagram_username VARCHAR(100),
                subscribed_fields TEXT,
                connected_by_staff_id INTEGER,
                connected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_token_refreshed_at TIMESTAMP,
                is_active BOOLEAN NOT NULL DEFAULT 1,
                deactivated_at TIMESTAMP,
                notes TEXT,
                granted_scopes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        # staff（migration 019 を SQLite 用に縮小、表示名取得に使う列のみ）
        await conn.execute(text("""
            CREATE TABLE staff (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id INTEGER NOT NULL DEFAULT 999,
                primary_email VARCHAR(255) NOT NULL,
                surname_jp VARCHAR(50),
                given_name_jp VARCHAR(50)
            )
        """))

    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db_session(engine):
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        yield session
        await session.rollback()


@pytest.fixture
def fernet_env(monkeypatch):
    """暗号化鍵を仕込む（既存 token を BLOB に書き込むため必要）。"""
    encryption.reset_cache()
    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("METADATA_FERNET_KEY", key)
    yield
    encryption.reset_cache()


def _mock_user():
    u = MagicMock()
    u.id = 1
    u.tenant_id = 999
    u.email = "tester@example.com"
    return u


def _build_app(db_session, tenant_id: int = 999, perms: set[str] = _ALL_PERMS):
    """meta_inbox ルーター付き最小 FastAPI app を作る（fixture と直接 helper 兼用）。"""
    app = FastAPI()

    async def override_db():
        yield db_session

    async def override_user():
        return _mock_user()

    async def override_tenant():
        return tenant_id

    app.include_router(meta_inbox.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_current_tenant] = override_tenant
    return app


@pytest_asyncio.fixture
async def app_client(db_session, fernet_env):
    """既定の app client（all permissions）。"""
    app = _build_app(db_session, tenant_id=999, perms=_ALL_PERMS)
    transport = ASGITransport(app=app)
    with ExitStack() as stack:
        stack.enter_context(patch(
            "app.auth.dependencies.load_user_permissions",
            new=AsyncMock(return_value=_ALL_PERMS),
        ))
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    app.dependency_overrides.clear()


async def _insert_channel(
    db_session,
    *,
    tenant_id: int,
    page_id: str,
    page_name: str,
    instagram_business_account_id: str | None = None,
    instagram_username: str | None = None,
    is_active: bool = True,
    connected_at: str | None = None,
    page_token_expires_at: str | None = None,
    connected_by_staff_id: int | None = None,
    token_plain: str = "fake-page-token",
    granted_scopes: list[str] | None = None,
):
    """tenant_meta_config に 1 行 INSERT するヘルパー。

    granted_scopes は ADR-041 で追加された再認証判定用 JSONB 列。SQLite では TEXT に
    JSON 文字列で格納する（meta_inbox._parse_scopes が JSONB / TEXT 両方を扱う）。
    None を渡すと列を NULL のまま残し、ADR-041 以前の接続を再現できる。
    """
    encrypted = encryption.encrypt(token_plain).encode("ascii")
    scopes_json = json.dumps(granted_scopes) if granted_scopes is not None else None
    sql = """
        INSERT INTO tenant_meta_config
            (tenant_id, page_id, page_name, page_access_token_encrypted,
             instagram_business_account_id, instagram_username,
             subscribed_fields, connected_by_staff_id,
             connected_at, page_token_expires_at, is_active, granted_scopes)
        VALUES
            (:tenant_id, :page_id, :page_name, :token,
             :ig_id, :ig_user,
             '[]', :staff_id,
             COALESCE(:connected_at, CURRENT_TIMESTAMP),
             :expires_at, :is_active, :granted_scopes)
    """
    await db_session.execute(text(sql), {
        "tenant_id": tenant_id,
        "page_id": page_id,
        "page_name": page_name,
        "token": encrypted,
        "ig_id": instagram_business_account_id,
        "ig_user": instagram_username,
        "staff_id": connected_by_staff_id,
        "connected_at": connected_at,
        "expires_at": page_token_expires_at,
        "is_active": 1 if is_active else 0,
        "granted_scopes": scopes_json,
    })
    await db_session.commit()


# ---------------------------------------------------------------------------
# テスト本体
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_channels_returns_empty_when_no_connections(app_client):
    """接続済 0 件なら channels が空配列で 200。"""
    resp = await app_client.get("/api/v1/meta/channels")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"channels": []}


@pytest.mark.asyncio
async def test_list_channels_returns_single_active_page(app_client, db_session):
    """1 件接続済で page_id/page_name/IG 情報が正しく返る。token は含まれない。"""
    await _insert_channel(
        db_session,
        tenant_id=999,
        page_id="page-1",
        page_name="Highlife JPN",
        instagram_business_account_id="ig-1",
        instagram_username="highlifejpn",
        token_plain="VERY-SECRET-TOKEN-SHOULD-NEVER-LEAK",
    )

    resp = await app_client.get("/api/v1/meta/channels")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["channels"]) == 1
    ch = body["channels"][0]
    assert ch["page_id"] == "page-1"
    assert ch["page_name"] == "Highlife JPN"
    assert ch["instagram_business_account_id"] == "ig-1"
    assert ch["instagram_username"] == "highlifejpn"
    assert ch["is_active"] is True
    assert ch["connected_at"] is not None
    # Page Access Token は絶対に出てこない
    raw_text = resp.text
    assert "VERY-SECRET-TOKEN-SHOULD-NEVER-LEAK" not in raw_text
    assert "page_access_token" not in raw_text
    assert "page_access_token_encrypted" not in raw_text


@pytest.mark.asyncio
async def test_list_channels_excludes_inactive_by_default(app_client, db_session):
    """include_inactive 未指定（既定 false）で is_active=FALSE 行が除外される。"""
    await _insert_channel(
        db_session, tenant_id=999, page_id="active-1", page_name="Active",
        is_active=True,
    )
    await _insert_channel(
        db_session, tenant_id=999, page_id="inactive-1", page_name="Inactive",
        is_active=False,
    )
    resp = await app_client.get("/api/v1/meta/channels")
    assert resp.status_code == 200
    page_ids = [c["page_id"] for c in resp.json()["channels"]]
    assert page_ids == ["active-1"]


@pytest.mark.asyncio
async def test_list_channels_include_inactive_true_returns_all(app_client, db_session):
    """include_inactive=true で is_active=FALSE も含めて返却される。"""
    await _insert_channel(
        db_session, tenant_id=999, page_id="active-1", page_name="Active",
        is_active=True,
    )
    await _insert_channel(
        db_session, tenant_id=999, page_id="inactive-1", page_name="Inactive",
        is_active=False,
    )
    resp = await app_client.get("/api/v1/meta/channels?include_inactive=true")
    assert resp.status_code == 200
    page_ids = sorted([c["page_id"] for c in resp.json()["channels"]])
    assert page_ids == ["active-1", "inactive-1"]
    # is_active boolean が両方 boolean で返る
    actives = {c["page_id"]: c["is_active"] for c in resp.json()["channels"]}
    assert actives["active-1"] is True
    assert actives["inactive-1"] is False


@pytest.mark.asyncio
async def test_list_channels_orders_by_connected_at_desc(app_client, db_session):
    """connected_at が新しい順（DESC）で返る。"""
    await _insert_channel(
        db_session, tenant_id=999, page_id="page-old", page_name="Old",
        connected_at="2026-01-01 00:00:00+00:00",
    )
    await _insert_channel(
        db_session, tenant_id=999, page_id="page-mid", page_name="Mid",
        connected_at="2026-03-01 00:00:00+00:00",
    )
    await _insert_channel(
        db_session, tenant_id=999, page_id="page-new", page_name="New",
        connected_at="2026-04-30 00:00:00+00:00",
    )
    resp = await app_client.get("/api/v1/meta/channels")
    assert resp.status_code == 200
    page_ids = [c["page_id"] for c in resp.json()["channels"]]
    assert page_ids == ["page-new", "page-mid", "page-old"]


@pytest.mark.asyncio
async def test_list_channels_filters_other_tenants(app_client, db_session):
    """別テナントの行は SELECT 結果に含まれない（多重テナント漏洩防止）。"""
    # 自テナント (999) の行
    await _insert_channel(
        db_session, tenant_id=999, page_id="own-page", page_name="Own",
    )
    # 他テナント (888) の行（漏れてはいけない）
    await _insert_channel(
        db_session, tenant_id=888, page_id="other-page", page_name="Other",
    )
    resp = await app_client.get("/api/v1/meta/channels")
    assert resp.status_code == 200
    page_ids = [c["page_id"] for c in resp.json()["channels"]]
    assert page_ids == ["own-page"]
    assert "other-page" not in page_ids


@pytest.mark.asyncio
async def test_list_channels_resolves_staff_name_when_present(app_client, db_session):
    """connected_by_staff_id が staff にある場合、staff_name が `surname_jp + ' ' + given_name_jp` で返る。"""
    # staff 行を投入
    await db_session.execute(text("""
        INSERT INTO staff (id, tenant_id, primary_email, surname_jp, given_name_jp)
        VALUES (5, 999, 'yamada@example.com', '山田', '太郎')
    """))
    await db_session.commit()

    await _insert_channel(
        db_session, tenant_id=999, page_id="page-1", page_name="P",
        connected_by_staff_id=5,
    )
    resp = await app_client.get("/api/v1/meta/channels")
    assert resp.status_code == 200
    ch = resp.json()["channels"][0]
    assert ch["connected_by_staff_id"] == 5
    assert ch["connected_by_staff_name"] == "山田 太郎"


@pytest.mark.asyncio
async def test_list_channels_returns_null_staff_name_when_unlinked(app_client, db_session):
    """connected_by_staff_id が NULL もしくは staff に存在しない場合 staff_name は NULL。"""
    await _insert_channel(
        db_session, tenant_id=999, page_id="page-1", page_name="P",
        connected_by_staff_id=None,
    )
    resp = await app_client.get("/api/v1/meta/channels")
    assert resp.status_code == 200
    ch = resp.json()["channels"][0]
    assert ch["connected_by_staff_id"] is None
    assert ch["connected_by_staff_name"] is None


@pytest.mark.asyncio
async def test_list_channels_returns_token_expires_at_when_set(app_client, db_session):
    """page_token_expires_at がレスポンスに ISO 文字列として返る。"""
    await _insert_channel(
        db_session, tenant_id=999, page_id="page-1", page_name="P",
        page_token_expires_at="2026-06-29 12:00:00+00:00",
    )
    resp = await app_client.get("/api/v1/meta/channels")
    assert resp.status_code == 200
    ch = resp.json()["channels"][0]
    assert ch["page_token_expires_at"] is not None
    # SQLite は str 返却、PostgreSQL は datetime（_format_dt で str 化）。
    # ともかく "2026" を含む文字列であれば OK
    assert "2026" in ch["page_token_expires_at"]


# ---------------------------------------------------------------------------
# ADR-041: 再認証バナー判定（requires_reauth）
# ---------------------------------------------------------------------------
#
# meta_inbox.list_channels の判定式（meta_inbox.py:802-805）:
#   requires_reauth = (
#       granted_scopes is not None
#       and "business_management" not in granted_scopes
#   )
#
# 3 分岐をユニットレベルで網羅する。本番テナント (tenant_004) は 2026-05-21 時点で
# Meta 連携を本格運用していないため実機観察ができない代わりに、ロジック検証を
# ここで担保する（F task の代替検証）。
# ---------------------------------------------------------------------------


_FULL_7_SCOPES = [
    "pages_show_list",
    "pages_manage_metadata",
    "pages_messaging",
    "pages_read_engagement",
    "instagram_basic",
    "instagram_manage_messages",
    "business_management",
]

_LEGACY_6_SCOPES = [
    "pages_show_list",
    "pages_manage_metadata",
    "pages_messaging",
    "pages_read_engagement",
    "instagram_basic",
    "instagram_manage_messages",
]


@pytest.mark.asyncio
async def test_list_channels_requires_reauth_false_when_business_management_present(
    app_client, db_session,
):
    """granted_scopes に business_management 含む 7 scope → requires_reauth=False。"""
    await _insert_channel(
        db_session, tenant_id=999, page_id="page-7scope", page_name="Full 7 scope",
        granted_scopes=_FULL_7_SCOPES,
    )
    resp = await app_client.get("/api/v1/meta/channels")
    assert resp.status_code == 200
    ch = resp.json()["channels"][0]
    assert ch["granted_scopes"] == _FULL_7_SCOPES
    assert ch["requires_reauth"] is False


@pytest.mark.asyncio
async def test_list_channels_requires_reauth_true_when_business_management_missing(
    app_client, db_session,
):
    """granted_scopes に business_management 欠落の 6 scope → requires_reauth=True。

    ADR-041 以前 (旧 6 scope) で接続済の本番テナントを再現するシナリオ。
    UI 側で再認証バナーが表示される。
    """
    await _insert_channel(
        db_session, tenant_id=999, page_id="page-6scope", page_name="Legacy 6 scope",
        granted_scopes=_LEGACY_6_SCOPES,
    )
    resp = await app_client.get("/api/v1/meta/channels")
    assert resp.status_code == 200
    ch = resp.json()["channels"][0]
    assert ch["granted_scopes"] == _LEGACY_6_SCOPES
    assert "business_management" not in ch["granted_scopes"]
    assert ch["requires_reauth"] is True


@pytest.mark.asyncio
async def test_list_channels_requires_reauth_false_when_granted_scopes_null(
    app_client, db_session,
):
    """granted_scopes が NULL → requires_reauth=False。

    意味付け (PR #487 follow-up で更新):
    本番の migration 055 適用済テナントでは、既存行は旧 6 scope で backfill される
    ため NULL 行は存在しない。したがって NULL を観測するのは以下の 2 ケースに限られる:

    1. `sql_no_scopes` フォールバック経路 (meta_inbox.py:748-764)
       — granted_scopes 列がまだ存在しない古い tenant schema を SELECT したとき、
         例外を受けて NULL を返す再試行 SQL が走り、`_parse_scopes(NULL) → None`
         で `requires_reauth=False` に落ちる
    2. migration 055 未適用の新規テナント
       — ADR-034 (新規テナント migration 自動適用) で本来は防がれるはずだが、
         自動適用の取りこぼし・手動 schema 作成等で列が NULL のまま残るケース

    判定式が `granted_scopes is not None and "business_management" not in granted_scopes`
    のため、NULL は「不明 → 強制再認証を避ける」方針で False を返す
    (既存運用への破壊的影響を防ぐ)。
    """
    await _insert_channel(
        db_session, tenant_id=999, page_id="page-null", page_name="Pre-ADR-041",
        granted_scopes=None,
    )
    resp = await app_client.get("/api/v1/meta/channels")
    assert resp.status_code == 200
    ch = resp.json()["channels"][0]
    assert ch["granted_scopes"] is None
    assert ch["requires_reauth"] is False


@pytest.mark.asyncio
async def test_list_channels_requires_reauth_true_when_granted_scopes_empty(
    app_client, db_session,
):
    """granted_scopes が空配列 [] → requires_reauth=True。

    PR #487 follow-up で追加。OAuth callback race / 手動修正 / migration glitch で
    `[]` が観測される可能性があり、6 scope と同じ「business_management 不在」分岐
    に落ちることを保証する。`_parse_scopes("[]") → []` で `requires_reauth` 判定式
    の `granted_scopes is not None and "business_management" not in granted_scopes`
    が True になる経路。
    """
    await _insert_channel(
        db_session, tenant_id=999, page_id="page-empty", page_name="Empty scopes",
        granted_scopes=[],
    )
    resp = await app_client.get("/api/v1/meta/channels")
    assert resp.status_code == 200
    ch = resp.json()["channels"][0]
    assert ch["granted_scopes"] == []
    assert ch["requires_reauth"] is True


# ---------------------------------------------------------------------------
# PR #487 follow-up: _parse_scopes の unit test
# ---------------------------------------------------------------------------
#
# meta_inbox.py:822-839 の `_parse_scopes` は granted_scopes 列の値を list[str] /
# None に正規化する。これまで `list_channels` 経由でしか間接的にカバーされていな
# かったため、関数自体の挙動を直接検証する unit test を追加する。
#
# 仕様（実装の実態）:
#   - None → None
#   - list (JSONB ネイティブ) → list[str] に str 化
#   - JSON 文字列 (TEXT 列) で list → list[str]
#   - 空文字列 / whitespace のみ → None
#   - 不正 JSON (CSV 含む) → None ※CSV は意図的にサポートしない
#   - 空配列 "[]" → [] (空 list を返す。requires_reauth=True に落ちる)
#   - JSON list 以外 (dict, scalar) → None
#   - その他の型 (int 等) → None
# ---------------------------------------------------------------------------


from app.routers.meta_inbox import _parse_scopes  # noqa: E402


class TestParseScopes:
    """`meta_inbox._parse_scopes` の直接 unit test (PR #487 follow-up)。"""

    def test_none_returns_none(self):
        """None 入力は None を返す（granted_scopes 列が NULL のケース）。"""
        assert _parse_scopes(None) is None

    def test_list_returns_string_list(self):
        """list 入力 (JSONB ネイティブ) は list[str] にして返す。"""
        assert _parse_scopes(["a", "b"]) == ["a", "b"]

    def test_list_with_non_string_items_stringified(self):
        """list 内の非文字列要素は str() で変換される。"""
        assert _parse_scopes([1, 2, "x"]) == ["1", "2", "x"]

    def test_empty_list_returns_empty_list(self):
        """空 list は空 list を返す（None には落とさない）。"""
        assert _parse_scopes([]) == []

    def test_json_string_list(self):
        """TEXT 列に JSON 文字列で list が入っているケース。"""
        assert _parse_scopes('["a","b","c"]') == ["a", "b", "c"]

    def test_json_string_empty_list(self):
        """JSON 文字列の空配列は空 list。requires_reauth 判定では「不在」扱い。"""
        assert _parse_scopes("[]") == []

    def test_empty_string_returns_none(self):
        """空文字列は None を返す（NULL と同等に扱う）。"""
        assert _parse_scopes("") is None

    def test_whitespace_only_returns_none(self):
        """空白のみの文字列も None を返す。"""
        assert _parse_scopes("   ") is None

    def test_invalid_json_returns_none(self):
        """不正な JSON 文字列は None を返す（例外を投げない）。"""
        assert _parse_scopes("not a json") is None

    def test_csv_returns_none(self):
        """CSV 形式は意図的にサポートしない（不正 JSON として None を返す）。

        granted_scopes は OAuth callback 時に JSONB として書き込まれる前提で、
        CSV が混入することはないため。CSV 互換が必要になれば実装側に分岐を
        足す形になるが、現状は None フォールバックでセーフに倒す。
        """
        assert _parse_scopes("a,b,c") is None

    def test_json_dict_returns_none(self):
        """list 以外の JSON (dict) は None。"""
        assert _parse_scopes('{"key": "value"}') is None

    def test_json_scalar_returns_none(self):
        """list 以外の JSON (scalar) は None。"""
        assert _parse_scopes('"single-string"') is None
        assert _parse_scopes("42") is None

    def test_other_types_return_none(self):
        """list / str / None 以外の型は None。"""
        assert _parse_scopes(42) is None
        assert _parse_scopes(3.14) is None
        assert _parse_scopes({"a": 1}) is None
        assert _parse_scopes(("a", "b")) is None  # tuple は list 扱いしない


# ---------------------------------------------------------------------------
# PR #487 follow-up: Postgres 統合テスト (requires_reauth 3 ケース)
# ---------------------------------------------------------------------------
#
# 既存の SQLite モック 3 ケース (7 scope / 6 scope / NULL) と同等のシナリオを
# 本物の PostgreSQL + JSONB で実行し、JSONB のネイティブ list 型が `_parse_scopes`
# を正しく通ることを保証する。
#
# 実行条件:
#   環境変数 `RLS_TEST_DATABASE_URL` が設定されているとき (CI で自動設定)。
#   ローカルでは SQLite のみで skip される。test_rls_tenant_meta_config.py と
#   同じ skipif gating パターン。
#
# 設計メモ:
#   list_channels endpoint の HTTP 経路までは通さず、SQL レベルで JSONB 列を
#   読み出して `_parse_scopes` + requires_reauth 判定の同等ロジックを検証する。
#   理由は HTTP 経路には別途 tenant schema / RLS / dependency override の準備が
#   重く、ここで保証したいのは「JSONB list → _parse_scopes → list[str] →
#   requires_reauth 判定」のデータ型 round-trip のみのため。
# ---------------------------------------------------------------------------


_PG_DSN: Optional[str] = os.getenv("RLS_TEST_DATABASE_URL")

_pg_skip = pytest.mark.skipif(
    not _PG_DSN,
    reason=(
        "PostgreSQL ベースの requires_reauth 統合テストは "
        "環境変数 RLS_TEST_DATABASE_URL が設定されたときだけ実行する"
    ),
)


@pytest_asyncio.fixture(scope="module")
async def pg_engine_for_scopes():
    assert _PG_DSN
    eng = create_async_engine(_PG_DSN, echo=False, future=True)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture(scope="module")
async def pg_setup_scopes_schema(pg_engine_for_scopes):
    """tenant_997 schema + tenant_meta_config + granted_scopes JSONB 列を作る。

    test_rls_tenant_meta_config.py と schema 番号がぶつからないように 997 を使う。
    """
    async with pg_engine_for_scopes.begin() as conn:
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS tenant_997"))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS tenant_997.tenant_meta_config (
                id SERIAL PRIMARY KEY,
                tenant_id INTEGER NOT NULL DEFAULT 997,
                page_id VARCHAR(50) NOT NULL,
                page_name VARCHAR(200) NOT NULL,
                page_access_token_encrypted BYTEA NOT NULL,
                granted_scopes JSONB,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                connected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))

    yield

    async with pg_engine_for_scopes.begin() as conn:
        await conn.execute(text("DROP SCHEMA IF EXISTS tenant_997 CASCADE"))


@pytest_asyncio.fixture()
async def pg_conn_scopes(pg_engine_for_scopes, pg_setup_scopes_schema):
    """各テストごとに独立 AsyncConnection。テスト前に TRUNCATE。"""
    async with pg_engine_for_scopes.connect() as conn:
        async with conn.begin():
            await conn.execute(text(
                "TRUNCATE tenant_997.tenant_meta_config RESTART IDENTITY CASCADE"
            ))
        yield conn


def _eval_requires_reauth(scopes_raw) -> tuple[Optional[list[str]], bool]:
    """meta_inbox.list_channels と同じ判定ロジックを再現するヘルパー。"""
    parsed = _parse_scopes(scopes_raw)
    requires_reauth = (
        parsed is not None and "business_management" not in parsed
    )
    return parsed, requires_reauth


@_pg_skip
@pytest.mark.asyncio
async def test_pg_requires_reauth_false_when_business_management_present(pg_conn_scopes):
    """[Postgres] granted_scopes JSONB に business_management 含む 7 scope → False。"""
    async with pg_conn_scopes.begin():
        await pg_conn_scopes.execute(text("""
            INSERT INTO tenant_997.tenant_meta_config
                (tenant_id, page_id, page_name, page_access_token_encrypted, granted_scopes)
            VALUES (997, 'pg-7scope', 'PG Full 7', :tok, CAST(:scopes AS jsonb))
        """), {"tok": b"x", "scopes": json.dumps(_FULL_7_SCOPES)})

    async with pg_conn_scopes.begin():
        row = (await pg_conn_scopes.execute(text(
            "SELECT granted_scopes FROM tenant_997.tenant_meta_config WHERE page_id='pg-7scope'"
        ))).fetchone()

    assert row is not None
    parsed, requires_reauth = _eval_requires_reauth(row[0])
    # JSONB は asyncpg が list として返すことを保証
    assert isinstance(row[0], list), f"JSONB should be list, got {type(row[0])}"
    assert parsed == _FULL_7_SCOPES
    assert requires_reauth is False


@_pg_skip
@pytest.mark.asyncio
async def test_pg_requires_reauth_true_when_business_management_missing(pg_conn_scopes):
    """[Postgres] granted_scopes JSONB が 6 scope (旧) → True。"""
    async with pg_conn_scopes.begin():
        await pg_conn_scopes.execute(text("""
            INSERT INTO tenant_997.tenant_meta_config
                (tenant_id, page_id, page_name, page_access_token_encrypted, granted_scopes)
            VALUES (997, 'pg-6scope', 'PG Legacy 6', :tok, CAST(:scopes AS jsonb))
        """), {"tok": b"x", "scopes": json.dumps(_LEGACY_6_SCOPES)})

    async with pg_conn_scopes.begin():
        row = (await pg_conn_scopes.execute(text(
            "SELECT granted_scopes FROM tenant_997.tenant_meta_config WHERE page_id='pg-6scope'"
        ))).fetchone()

    assert row is not None
    parsed, requires_reauth = _eval_requires_reauth(row[0])
    assert isinstance(row[0], list)
    assert parsed == _LEGACY_6_SCOPES
    assert "business_management" not in parsed
    assert requires_reauth is True


@_pg_skip
@pytest.mark.asyncio
async def test_pg_requires_reauth_false_when_granted_scopes_null(pg_conn_scopes):
    """[Postgres] granted_scopes JSONB が NULL → False (sql_no_scopes 経路相当)。"""
    async with pg_conn_scopes.begin():
        await pg_conn_scopes.execute(text("""
            INSERT INTO tenant_997.tenant_meta_config
                (tenant_id, page_id, page_name, page_access_token_encrypted, granted_scopes)
            VALUES (997, 'pg-null', 'PG NULL', :tok, NULL)
        """), {"tok": b"x"})

    async with pg_conn_scopes.begin():
        row = (await pg_conn_scopes.execute(text(
            "SELECT granted_scopes FROM tenant_997.tenant_meta_config WHERE page_id='pg-null'"
        ))).fetchone()

    assert row is not None
    parsed, requires_reauth = _eval_requires_reauth(row[0])
    assert row[0] is None
    assert parsed is None
    assert requires_reauth is False
