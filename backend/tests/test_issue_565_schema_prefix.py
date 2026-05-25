"""Issue #565 回帰テスト — 6 router の _t() ヘルパーが
PostgreSQL dialect では `tenant_NNN.<name>` を組み立て、SQLite では prefix なしの
`<name>` を返すことを確認する。

PR #564 (Issue #563 / tenant_profile.py) と同じ dialect-aware パターンを
bots.py / leads.py / deals.py / products.py / orders.py / order_financials.py に
展開したのが本 PR。tenant_profile.py 側のテストは test_tenant_profile.py 参照。
"""
from __future__ import annotations

import pytest

from app.routers.bots import _t as _bots_t, _is_postgresql as _bots_pg
from app.routers.leads import _t as _leads_t, _is_postgresql as _leads_pg
from app.routers.deals import _t as _deals_t, _is_postgresql as _deals_pg
from app.routers.products import _t as _products_t, _is_postgresql as _products_pg
from app.routers.orders import _t as _orders_t, _is_postgresql as _orders_pg
from app.routers.order_financials import (
    _t as _ofin_t,
    _is_postgresql as _ofin_pg,
)


class _StubDialect:
    name = "postgresql"


class _StubBind:
    dialect = _StubDialect()


class _StubSession:
    """get_bind() で PostgreSQL dialect の bind を返す stub session。

    実 AsyncSession を立てるとコストが高いため、_is_postgresql が見るのは
    `db.get_bind().dialect.name` のみという前提で stub に差し替える。
    """

    def get_bind(self):
        return _StubBind()


# ──────────────────────────────────────────────────────────────────
# PostgreSQL dialect: schema prefix 明示
# ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "t_fn,name,expected",
    [
        # bots.py が触る tenant スキーマ内テーブル
        (_bots_t, "bots", "tenant_006.bots"),
        (_bots_t, "staff", "tenant_006.staff"),
        # leads.py
        (_leads_t, "leads", "tenant_006.leads"),
        (_leads_t, "contacts", "tenant_006.contacts"),
        (_leads_t, "deals", "tenant_006.deals"),
        (_leads_t, "meta_messages", "tenant_006.meta_messages"),
        (_leads_t, "tenant_meta_config", "tenant_006.tenant_meta_config"),
        (_leads_t, "staff", "tenant_006.staff"),
        # deals.py
        (_deals_t, "deals", "tenant_006.deals"),
        (_deals_t, "contacts", "tenant_006.contacts"),
        (_deals_t, "companies", "tenant_006.companies"),
        (_deals_t, "leads", "tenant_006.leads"),
        # products.py
        (_products_t, "products", "tenant_006.products"),
        (_products_t, "quote_items", "tenant_006.quote_items"),
        (_products_t, "invoice_items", "tenant_006.invoice_items"),
        (_products_t, "purchase_order_items", "tenant_006.purchase_order_items"),
        # orders.py
        (_orders_t, "orders", "tenant_006.orders"),
        (_orders_t, "deals", "tenant_006.deals"),
        (_orders_t, "contacts", "tenant_006.contacts"),
        (_orders_t, "companies", "tenant_006.companies"),
        # order_financials.py
        (_ofin_t, "orders", "tenant_006.orders"),
        (_ofin_t, "order_financials", "tenant_006.order_financials"),
    ],
)
def test_router_t_postgresql_with_prefix(t_fn, name, expected):
    """PostgreSQL dialect 下では `tenant_NNN.<name>` 形式の修飾名を返す。"""
    assert t_fn(_StubSession(), tenant_id=6, name=name) == expected


@pytest.mark.parametrize(
    "t_fn",
    [_bots_t, _leads_t, _deals_t, _products_t, _orders_t, _ofin_t],
)
def test_router_t_tenant_id_padding(t_fn):
    """tenant_id が 3 桁未満なら 0 詰めされ、3 桁以上はそのまま埋め込まれる。"""
    assert t_fn(_StubSession(), tenant_id=1, name="x") == "tenant_001.x"
    assert t_fn(_StubSession(), tenant_id=42, name="x") == "tenant_042.x"
    assert t_fn(_StubSession(), tenant_id=999, name="x") == "tenant_999.x"
    assert t_fn(_StubSession(), tenant_id=1234, name="x") == "tenant_1234.x"


@pytest.mark.parametrize(
    "pg_fn",
    [_bots_pg, _leads_pg, _deals_pg, _products_pg, _orders_pg, _ofin_pg],
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
        (_bots_t, "bots"),
        (_leads_t, "leads"),
        (_deals_t, "deals"),
        (_products_t, "products"),
        (_orders_t, "orders"),
        (_ofin_t, "order_financials"),
    ],
)
async def test_router_t_sqlite_no_prefix(db_session, t_fn, name):
    """SQLite (pytest) では prefix なしの素の table 名を返す。"""
    assert t_fn(db_session, tenant_id=999, name=name) == name


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "pg_fn",
    [_bots_pg, _leads_pg, _deals_pg, _products_pg, _orders_pg, _ofin_pg],
)
async def test_is_postgresql_with_sqlite_session(db_session, pg_fn):
    """db_session (SQLite) では False を返す。"""
    assert pg_fn(db_session) is False
