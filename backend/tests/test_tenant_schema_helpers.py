"""ADR-072 Phase 1: app.auth.dependencies の公開 helper の単体テスト。

PR #564 / #757 / #768 で各 router ローカルに置いていた `_is_postgresql` / `_t`
ヘルパーを `app.auth.dependencies` に公開 API として統合した
(`is_postgresql` / `tenant_table_ref`)。本ファイルで包括的に検証する。

旧テスト (test_issue_565_schema_prefix.py / test_issue_766_schema_prefix.py /
test_tenant_profile.py の _tenant_profile_table テスト) は本 PR で削除済。
"""
from __future__ import annotations

import pytest

from app.auth.dependencies import is_postgresql, tenant_table_ref


class _StubDialect:
    name = "postgresql"


class _StubBind:
    dialect = _StubDialect()


class _StubSession:
    """PostgreSQL dialect を返す stub session。

    実 AsyncSession を立てるとコストが高いため、`is_postgresql` が見るのは
    `db.get_bind().dialect.name` のみという前提で stub に差し替える。
    """

    def get_bind(self):
        return _StubBind()


# ──────────────────────────────────────────────────────────────────
# PostgreSQL dialect: schema prefix 明示
# ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "name,expected",
    [
        # Issue #563 / PR #564 由来
        ("tenant_profile", "tenant_006.tenant_profile"),
        # Issue #565 / PR #757 由来
        ("bots", "tenant_006.bots"),
        ("staff", "tenant_006.staff"),
        ("leads", "tenant_006.leads"),
        ("contacts", "tenant_006.contacts"),
        ("deals", "tenant_006.deals"),
        ("meta_messages", "tenant_006.meta_messages"),
        ("tenant_meta_config", "tenant_006.tenant_meta_config"),
        ("companies", "tenant_006.companies"),
        ("products", "tenant_006.products"),
        ("quote_items", "tenant_006.quote_items"),
        ("invoice_items", "tenant_006.invoice_items"),
        ("purchase_order_items", "tenant_006.purchase_order_items"),
        ("orders", "tenant_006.orders"),
        ("order_financials", "tenant_006.order_financials"),
        # Issue #766 / PR #768 由来
        ("order_shipping_details", "tenant_006.order_shipping_details"),
        ("order_purchase_details", "tenant_006.order_purchase_details"),
        ("order_commissions", "tenant_006.order_commissions"),
        ("tenant_commission_settings", "tenant_006.tenant_commission_settings"),
    ],
)
def test_tenant_table_ref_postgresql_with_prefix(name, expected):
    """PostgreSQL dialect 下では `tenant_NNN.<name>` 形式の修飾名を返す。"""
    assert tenant_table_ref(_StubSession(), tenant_id=6, name=name) == expected


def test_tenant_table_ref_tenant_id_padding():
    """tenant_id が 3 桁未満なら 0 詰めされ、3 桁以上はそのまま埋め込まれる。"""
    assert tenant_table_ref(_StubSession(), tenant_id=1, name="x") == "tenant_001.x"
    assert tenant_table_ref(_StubSession(), tenant_id=42, name="x") == "tenant_042.x"
    assert tenant_table_ref(_StubSession(), tenant_id=999, name="x") == "tenant_999.x"
    assert tenant_table_ref(_StubSession(), tenant_id=1234, name="x") == "tenant_1234.x"


def test_is_postgresql_with_stub_pg():
    """is_postgresql は dialect.name='postgresql' を検出する。"""
    assert is_postgresql(_StubSession()) is True


# ──────────────────────────────────────────────────────────────────
# SQLite (テスト環境): schema 概念なし → prefix なし
# ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name",
    [
        "tenant_profile",
        "bots",
        "leads",
        "deals",
        "products",
        "orders",
        "order_financials",
        "order_shipping_details",
        "order_purchase_details",
        "order_commissions",
    ],
)
async def test_tenant_table_ref_sqlite_no_prefix(db_session, name):
    """SQLite (pytest) では prefix なしの素の table 名を返す。"""
    assert tenant_table_ref(db_session, tenant_id=999, name=name) == name


@pytest.mark.asyncio
async def test_is_postgresql_with_sqlite_session(db_session):
    """db_session (SQLite) では False を返す。"""
    assert is_postgresql(db_session) is False


# ──────────────────────────────────────────────────────────────────
# 既存 `_dialect_supports_search_path` との等価性
# ──────────────────────────────────────────────────────────────────


def test_is_postgresql_is_thin_wrapper_around_dialect_supports_search_path():
    """ADR-072 §「helper 共通化」: is_postgresql は既存 `_dialect_supports_search_path`
    と同じ挙動でなければならない (二重実装回避)。"""
    from app.auth.dependencies import _dialect_supports_search_path

    stub = _StubSession()
    assert is_postgresql(stub) == _dialect_supports_search_path(stub)


@pytest.mark.asyncio
async def test_is_postgresql_matches_dialect_supports_search_path_on_sqlite(db_session):
    """SQLite 経路でも `_dialect_supports_search_path` と同じ判定。"""
    from app.auth.dependencies import _dialect_supports_search_path

    assert is_postgresql(db_session) == _dialect_supports_search_path(db_session)
