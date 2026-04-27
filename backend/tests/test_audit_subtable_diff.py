"""PR #145 F9: companies/contacts の audit_log に副テーブル差分が記録されているか検証する smoke test。

実 pytest baseline は別件 (app.auth.dependencies AttributeError) で動かないことが多いが、
この test は audit.py のユーティリティ関数（純 Python）を直接呼ぶ単体テストと、
companies / contacts の routers を import して構造を grep する静的検証で構成しているため
依存ライブラリのロードに成功する範囲では実行可能。

検証項目:
  1. diff_rows / diff_scalars / diff_single_row の単体動作
  2. build_subtable_diff の動作（list[dict] / list[scalar] / dict / None の混在）
  3. companies.py / contacts.py で副テーブル diff を audit_log に渡している grep 確認
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


# -----------------------------------------------------------------------------
# 1. diff ユーティリティの単体テスト
# -----------------------------------------------------------------------------
def test_diff_rows_added_only():
    from app.services.audit import diff_rows

    out = diff_rows(
        [],
        [{"address_type": "billing", "branch_name": "Tokyo"}],
    )
    assert out == {"added": [{"address_type": "billing", "branch_name": "Tokyo"}]}


def test_diff_rows_removed_only():
    from app.services.audit import diff_rows

    out = diff_rows(
        [{"address_type": "billing", "branch_name": "Tokyo"}],
        [],
    )
    assert out == {"removed": [{"address_type": "billing", "branch_name": "Tokyo"}]}


def test_diff_rows_added_and_removed_treats_edit_as_pair():
    """1 件の編集は added + removed のペアとして表現される（natural key 仮定なし）。"""
    from app.services.audit import diff_rows

    old = [{"address_type": "billing", "branch_name": "Tokyo", "email": "old@x.jp"}]
    new = [{"address_type": "billing", "branch_name": "Tokyo", "email": "new@x.jp"}]
    out = diff_rows(old, new)
    assert out is not None
    assert {"address_type": "billing", "branch_name": "Tokyo", "email": "new@x.jp"} in out["added"]
    assert {"address_type": "billing", "branch_name": "Tokyo", "email": "old@x.jp"} in out["removed"]


def test_diff_rows_no_change_returns_none():
    from app.services.audit import diff_rows

    rows = [{"a": 1, "b": 2}]
    assert diff_rows(rows, rows) is None
    assert diff_rows([], []) is None
    assert diff_rows(None, None) is None


def test_diff_rows_ignores_id_and_timestamp_columns():
    """`id` / `created_at` / `updated_at` は diff の対象外（INSERT で滑るため）。"""
    from app.services.audit import diff_rows

    old = [{"id": 1, "name": "A", "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00"}]
    new = [{"id": 99, "name": "A", "created_at": "2026-04-27T00:00:00", "updated_at": "2026-04-27T00:00:00"}]
    assert diff_rows(old, new) is None


def test_diff_scalars():
    from app.services.audit import diff_scalars

    assert diff_scalars(["EC", "実店舗"], ["EC", "卸"]) == {
        "added": ["卸"],
        "removed": ["実店舗"],
    }
    assert diff_scalars([], []) is None
    assert diff_scalars(["EC"], ["EC"]) is None
    assert diff_scalars(None, ["EC"]) == {"added": ["EC"]}
    assert diff_scalars(["EC"], None) == {"removed": ["EC"]}


def test_diff_single_row():
    from app.services.audit import diff_single_row

    assert diff_single_row(None, None) is None
    assert diff_single_row({"is_joined": True}, {"is_joined": True}) is None
    assert diff_single_row(None, {"is_joined": True}) == {
        "old": None,
        "new": {"is_joined": True},
    }
    assert diff_single_row({"is_joined": True}, None) == {
        "old": {"is_joined": True},
        "new": None,
    }
    assert diff_single_row({"is_joined": True}, {"is_joined": False}) == {
        "old": {"is_joined": True},
        "new": {"is_joined": False},
    }


def test_diff_single_row_strips_id_and_timestamps():
    from app.services.audit import diff_single_row

    old = {"id": 1, "is_joined": True, "created_at": "2026-01-01", "updated_at": "2026-01-01"}
    new = {"id": 1, "is_joined": True, "created_at": "2026-04-27", "updated_at": "2026-04-27"}
    assert diff_single_row(old, new) is None


# -----------------------------------------------------------------------------
# 2. build_subtable_diff の総合動作
# -----------------------------------------------------------------------------
def test_build_subtable_diff_company_pattern():
    """companies の副テーブル 2 種を一括 diff したシナリオ。"""
    from app.services.audit import build_subtable_diff

    old = {
        "company_addresses": [
            {"address_type": "billing", "branch_name": "Tokyo", "email": "a@x.jp"},
        ],
        "company_sales_channels": ["EC", "実店舗"],
    }
    new = {
        "company_addresses": [
            {"address_type": "billing", "branch_name": "Tokyo", "email": "a@x.jp"},
            {"address_type": "delivery", "branch_name": "Osaka", "email": "b@x.jp"},
        ],
        "company_sales_channels": ["EC"],
    }
    out = build_subtable_diff(old, new)
    assert out is not None
    assert "company_addresses" in out
    assert out["company_addresses"]["added"] == [
        {"address_type": "delivery", "branch_name": "Osaka", "email": "b@x.jp"}
    ]
    assert "removed" not in out["company_addresses"]
    assert out["company_sales_channels"] == {"removed": ["実店舗"]}


def test_build_subtable_diff_contact_pattern_with_discord():
    """contacts の副テーブル 3 種（うち 1 つは 1:1 の dict）を一括 diff。"""
    from app.services.audit import build_subtable_diff

    old = {
        "contact_emails": [{"email": "a@x.jp", "purpose": "billing"}],
        "contact_discord": None,
        "contact_contact_channels": [{"channel": "email", "purpose": None, "is_primary": True}],
    }
    new = {
        "contact_emails": [{"email": "a@x.jp", "purpose": "billing"}],
        "contact_discord": {
            "is_joined": True,
            "channel_id": "C1",
            "user_id": "U1",
            "invoice_webhook": None,
            "shipment_webhook": None,
        },
        "contact_contact_channels": [
            {"channel": "email", "purpose": None, "is_primary": True},
            {"channel": "discord", "purpose": "Discord連携", "is_primary": False},
        ],
    }
    out = build_subtable_diff(old, new)
    assert out is not None
    # email は不変なので含まれない
    assert "contact_emails" not in out
    # discord は新規 join
    assert out["contact_discord"]["old"] is None
    assert out["contact_discord"]["new"]["is_joined"] is True
    assert out["contact_discord"]["new"]["channel_id"] == "C1"
    # contact_contact_channels は discord 行が added
    assert out["contact_contact_channels"]["added"] == [
        {"channel": "discord", "purpose": "Discord連携", "is_primary": False}
    ]


def test_build_subtable_diff_no_change_returns_none():
    from app.services.audit import build_subtable_diff

    snap = {
        "company_addresses": [{"address_type": "billing", "branch_name": "Tokyo"}],
        "company_sales_channels": ["EC"],
    }
    assert build_subtable_diff(snap, snap) is None


def test_build_subtable_diff_only_parent_change_no_subtable_noise():
    """副テーブルが全く動いていない update では _subtables キーが組み立てられないこと。"""
    from app.services.audit import build_subtable_diff

    old = {
        "company_addresses": [{"address_type": "billing", "branch_name": "Tokyo"}],
        "company_sales_channels": ["EC"],
    }
    new = old  # 親側（companies テーブル）だけ更新するシナリオ
    assert build_subtable_diff(old, new) is None


# -----------------------------------------------------------------------------
# 3. companies.py / contacts.py が build_subtable_diff を audit log に渡している grep 確認
# -----------------------------------------------------------------------------
def test_companies_router_uses_subtable_diff():
    src = (REPO_ROOT / "backend" / "app" / "routers" / "companies.py").read_text(encoding="utf-8")
    # import が入っている
    assert "build_subtable_diff" in src
    assert "snapshot_subtable_rows" in src
    assert "_snapshot_company_subtables" in src
    # update / delete / create で _subtables キーを new_data または old_data に積んでいる
    assert "\"_subtables\"" in src or "'_subtables'" in src


def test_contacts_router_uses_subtable_diff():
    src = (REPO_ROOT / "backend" / "app" / "routers" / "contacts.py").read_text(encoding="utf-8")
    assert "build_subtable_diff" in src
    assert "snapshot_subtable_rows" in src
    assert "_snapshot_contact_subtables" in src
    assert "\"_subtables\"" in src or "'_subtables'" in src


def test_companies_update_takes_old_snapshot_before_replace():
    """update_company 内で old スナップショットが _replace_addresses より前に取られている順序確認。

    順序が逆だと old/new が同一になり diff が常に空になるため重要。
    """
    src = (REPO_ROOT / "backend" / "app" / "routers" / "companies.py").read_text(encoding="utf-8")
    # PATCH ハンドラの開始から末尾までを切り出す
    m = re.search(r"async def update_company\(.*?(?=\n@router\.|\nasync def )", src, re.DOTALL)
    assert m, "update_company が見つからない"
    body = m.group(0)
    snap_idx = body.find("_snapshot_company_subtables(db, company_id)")
    replace_idx = body.find("_replace_addresses(db, company_id")
    assert snap_idx != -1 and replace_idx != -1
    # 最初の snap 呼び出し（old）の方が _replace_addresses より前にある
    assert snap_idx < replace_idx, "old スナップショットが _replace_addresses より後にある"


def test_contacts_update_takes_old_snapshot_before_replace():
    src = (REPO_ROOT / "backend" / "app" / "routers" / "contacts.py").read_text(encoding="utf-8")
    m = re.search(r"async def update_contact\(.*?(?=\n@router\.|\nasync def )", src, re.DOTALL)
    assert m, "update_contact が見つからない"
    body = m.group(0)
    snap_idx = body.find("_snapshot_contact_subtables(db, contact_id)")
    replace_idx = body.find("_replace_emails(db, contact_id")
    assert snap_idx != -1 and replace_idx != -1
    assert snap_idx < replace_idx, "old スナップショットが _replace_emails より後にある"


# -----------------------------------------------------------------------------
# 4. snapshot_subtable_rows / snapshot_subtable_scalars が SQLite で動く（async smoke）
# -----------------------------------------------------------------------------
import pytest


@pytest.mark.asyncio
async def test_snapshot_helpers_against_sqlite(db_session):
    """conftest の SQLite に直接 INSERT して snapshot 関数の SQL が動くことを確認。"""
    from sqlalchemy import text as _t
    from app.services.audit import snapshot_subtable_rows, snapshot_subtable_scalars

    # company を 1 件作って副テーブルにも 1 行ずつ入れる
    res = await db_session.execute(
        _t("INSERT INTO companies (tenant_id, company_code, name) VALUES (999, 'CO-T1', 'T1') RETURNING id")
    )
    cid = res.scalar_one()
    await db_session.execute(
        _t("INSERT INTO company_addresses (company_id, address_type, branch_name, country_code, is_default) "
           "VALUES (:cid, 'billing', 'Tokyo', 'JP', 1)"),
        {"cid": cid},
    )
    await db_session.execute(
        _t("INSERT INTO company_sales_channels (company_id, channel) VALUES (:cid, 'EC')"),
        {"cid": cid},
    )

    rows = await snapshot_subtable_rows(
        db_session, "company_addresses", "company_id", cid,
        ["address_type", "branch_name", "country_code", "is_default"],
    )
    assert len(rows) == 1
    assert rows[0]["address_type"] == "billing"
    assert rows[0]["branch_name"] == "Tokyo"

    channels = await snapshot_subtable_scalars(
        db_session, "company_sales_channels", "company_id", cid, "channel",
    )
    assert channels == ["EC"]
