"""Issue #766 回帰テスト — 3 router の _t() ヘルパーが
PostgreSQL dialect では `tenant_NNN.<name>` を組み立て、SQLite では prefix なしの
`<name>` を返すことを確認する。

PR #757 (Issue #565) と同じ dialect-aware パターンを
order_shipping_details.py / order_purchase_details.py / order_commissions.py に
展開したのが本 PR。test_issue_565_schema_prefix.py の続編。
"""
from __future__ import annotations

import pytest

from app.routers.order_shipping_details import (
    _t as _shipping_t,
    _is_postgresql as _shipping_pg,
)
from app.routers.order_purchase_details import (
    _t as _purchase_t,
    _is_postgresql as _purchase_pg,
)
from app.routers.order_commissions import (
    _t as _commissions_t,
    _is_postgresql as _commissions_pg,
)


class _StubDialect:
    name = "postgresql"


class _StubBind:
    dialect = _StubDialect()


class _StubSession:
    """PostgreSQL dialect 模擬 stub session (PR #757 同パターン)。"""

    def get_bind(self):
        return _StubBind()


# ──────────────────────────────────────────────────────────────────
# PostgreSQL dialect: schema prefix 明示
# ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "t_fn,name,expected",
    [
        # order_shipping_details.py が触る tenant スキーマ内テーブル
        (_shipping_t, "orders", "tenant_006.orders"),
        (_shipping_t, "order_shipping_details", "tenant_006.order_shipping_details"),
        # order_purchase_details.py
        (_purchase_t, "orders", "tenant_006.orders"),
        (_purchase_t, "order_purchase_details", "tenant_006.order_purchase_details"),
        # order_commissions.py
        (_commissions_t, "orders", "tenant_006.orders"),
        (_commissions_t, "order_commissions", "tenant_006.order_commissions"),
        (_commissions_t, "order_financials", "tenant_006.order_financials"),
        (_commissions_t, "staff", "tenant_006.staff"),
        (_commissions_t, "tenant_commission_settings", "tenant_006.tenant_commission_settings"),
    ],
)
def test_router_t_postgresql_with_prefix(t_fn, name, expected):
    """PostgreSQL dialect 下では `tenant_NNN.<name>` 形式の修飾名を返す。"""
    assert t_fn(_StubSession(), tenant_id=6, name=name) == expected


@pytest.mark.parametrize(
    "t_fn",
    [_shipping_t, _purchase_t, _commissions_t],
)
def test_router_t_tenant_id_padding(t_fn):
    """tenant_id が 3 桁未満なら 0 詰めされ、3 桁以上はそのまま埋め込まれる。"""
    assert t_fn(_StubSession(), tenant_id=1, name="x") == "tenant_001.x"
    assert t_fn(_StubSession(), tenant_id=42, name="x") == "tenant_042.x"
    assert t_fn(_StubSession(), tenant_id=999, name="x") == "tenant_999.x"
    assert t_fn(_StubSession(), tenant_id=1234, name="x") == "tenant_1234.x"


@pytest.mark.parametrize(
    "pg_fn",
    [_shipping_pg, _purchase_pg, _commissions_pg],
)
def test_is_postgresql_with_stub_pg(pg_fn):
    """_is_postgresql は dialect.name='postgresql' を検出する。"""
    assert pg_fn(_StubSession()) is True


# ──────────────────────────────────────────────────────────────────
# SQLite (テスト環境): schema 概念なし → prefix なし
# ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "t_fn,name",
    [
        (_shipping_t, "order_shipping_details"),
        (_purchase_t, "order_purchase_details"),
        (_commissions_t, "order_commissions"),
    ],
)
async def test_router_t_sqlite_no_prefix(db_session, t_fn, name):
    """SQLite (pytest) では prefix なしの素の table 名を返す。"""
    assert t_fn(db_session, tenant_id=999, name=name) == name


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "pg_fn",
    [_shipping_pg, _purchase_pg, _commissions_pg],
)
async def test_is_postgresql_with_sqlite_session(db_session, pg_fn):
    """db_session (SQLite) では False を返す。"""
    assert pg_fn(db_session) is False
