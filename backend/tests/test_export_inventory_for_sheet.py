"""Sprint 9 / F9 v1.2: scripts/export_inventory_for_sheet.py の単体テスト (実 PostgreSQL)。

spec.md v1.2 F9 / AC9.2:
  - 列構成: product_id, delta_qty, occurred_at, supplier_id, operator_id, notes
  - tenant_id + since の組合せフィルタが正しく動作
  - 冪等性: 同条件 2 回実行で同じ CSV (順序固定)

SQLite モック禁止 (memory: feedback_evaluator_gap_2026_05_15)。
"""

from __future__ import annotations

import csv
import os
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

TEST_PG_URL = os.getenv("TEST_PG_URL")

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not TEST_PG_URL,
        reason="実 PostgreSQL 環境が必要 (TEST_PG_URL 未設定)。",
    ),
]

# script を import するための path 追加
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))


@pytest.fixture
async def engine():
    from sqlalchemy.ext.asyncio import create_async_engine

    eng = create_async_engine(TEST_PG_URL, echo=False)
    yield eng
    await eng.dispose()


async def _setup_movements(engine, tenant_id: int) -> dict:
    """tenant_id 配下に 3 件の movements を seed する。

    Returns:
        dict with product_ids, supplier_id, operator_id, since_date
    """
    from sqlalchemy import text

    tag = uuid.uuid4().hex[:8]
    sup_id = None
    product_ids: list[int] = []
    op_id = None

    async with engine.begin() as conn:
        # supplier
        sup_id = (
            await conn.execute(
                text(
                    "INSERT INTO public.suppliers (name, supplier_type, default_language) "
                    "VALUES (:n, 'corporate', 'ja') RETURNING id"
                ),
                {"n": f"export_test_sup_{tag}"},
            )
        ).scalar_one()
        # operator (public.users 行を作る)
        op_id = (
            await conn.execute(
                text(
                    "INSERT INTO public.users (firebase_uid, email, name, is_active, is_super_admin) "
                    "VALUES (:uid, :email, :n, TRUE, TRUE) RETURNING id"
                ),
                {
                    "uid": f"export_test_op_{tag}",
                    "email": f"export_test_{tag}@example.com",
                    "n": f"export_test_op_{tag}",
                },
            )
        ).scalar_one()

        # 3 products
        for i in range(3):
            pid = (
                await conn.execute(
                    text(
                        "INSERT INTO public.products (tenant_id, product_code, name, stock_quantity) "
                        "VALUES (:tid, :code, :n, 0) RETURNING id"
                    ),
                    {
                        "tid": tenant_id,
                        "code": f"EX-{tag}-{i}",
                        "n": f"EX-{tag}-{i}",
                    },
                )
            ).scalar_one()
            product_ids.append(int(pid))

        # 3 movements at 異なる occurred_at (since 境界 1 件、since 後 2 件)
        # since = 2026-05-01
        # 0: 2026-04-30 23:00 (= since 直前、フィルタ外)
        # 1: 2026-05-01 10:00 (= since 当日、フィルタ内)
        # 2: 2026-05-02 10:00 (フィルタ内)
        movements_data = [
            (product_ids[0], 10, datetime(2026, 4, 30, 23, 0, 0, tzinfo=timezone.utc), "old"),
            (product_ids[1], 5, datetime(2026, 5, 1, 10, 0, 0, tzinfo=timezone.utc), "new1"),
            (product_ids[2], -3, datetime(2026, 5, 2, 10, 0, 0, tzinfo=timezone.utc), "new2"),
        ]
        for pid, delta, occurred, note in movements_data:
            # before/after は適当 (CHECK trigger 通過用)
            before = 0
            after = before + delta
            await conn.execute(
                text(
                    """
                    INSERT INTO public.inventory_movements
                        (tenant_id, product_id, delta_qty, before_qty, after_qty,
                         source_type, source_id, supplier_id, operator_id, occurred_at, notes)
                    VALUES
                        (:tid, :pid, :delta, :bef, :aft,
                         'discord_inbound_review', NULL, :sup, :op, :occ, :n)
                    """
                ),
                {
                    "tid": tenant_id,
                    "pid": pid,
                    "delta": delta,
                    "bef": before,
                    "aft": after,
                    "sup": sup_id,
                    "op": op_id,
                    "occ": occurred,
                    "n": note,
                },
            )

    return {
        "product_ids": product_ids,
        "supplier_id": int(sup_id),
        "operator_id": int(op_id),
    }


async def _cleanup(engine, tenant_id: int, product_ids: list[int]) -> None:
    from sqlalchemy import text

    async with engine.begin() as conn:
        await conn.execute(
            text(
                "DELETE FROM public.inventory_movements "
                "WHERE tenant_id = :tid AND product_id = ANY(:pids)"
            ),
            {"tid": tenant_id, "pids": product_ids},
        )
        await conn.execute(
            text("DELETE FROM public.products WHERE id = ANY(:pids)"),
            {"pids": product_ids},
        )


async def _ensure_tenant(engine, tenant_code: str) -> int:
    from sqlalchemy import text

    async with engine.begin() as conn:
        row = (
            await conn.execute(
                text("SELECT id FROM public.tenants WHERE tenant_code = :code"),
                {"code": tenant_code},
            )
        ).first()
        if row is not None:
            return int(row[0])
        row = (
            await conn.execute(
                text(
                    "INSERT INTO public.tenants (tenant_code, company_name, is_active) "
                    "VALUES (:c, :n, TRUE) RETURNING id"
                ),
                {"c": tenant_code, "n": f"export_test_{tenant_code}"},
            )
        ).first()
        if row is None:
            raise RuntimeError("tenants INSERT failed")
        return int(row[0])


async def test_export_csv_columns_and_rows(engine, tmp_path):
    """AC9.2: 列構成 + 期間フィルタ + 行数。"""
    from export_inventory_for_sheet import export_inventory

    tag = uuid.uuid4().hex[:8]
    tenant_id = await _ensure_tenant(engine, f"ex_test_{tag}")
    ctx = await _setup_movements(engine, tenant_id)

    output = tmp_path / "out.csv"
    rows_count = await export_inventory(
        tenant_id=tenant_id,
        since=date(2026, 5, 1),
        until=None,
        output=output,
        db_url=TEST_PG_URL,
    )

    assert rows_count == 2, "since=2026-05-01 で 2 件残ること（4/30 1件はフィルタ外）"

    # CSV ヘッダ確認
    with output.open("r", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        rows = list(reader)
    assert rows[0] == [
        "product_id",
        "delta_qty",
        "occurred_at",
        "supplier_id",
        "operator_id",
        "notes",
    ]
    # データ行 2 件
    assert len(rows) == 3  # header + 2 data rows

    # 順序固定: occurred_at ASC で 5/1 → 5/2
    assert "2026-05-01" in rows[1][2]
    assert "2026-05-02" in rows[2][2]

    # delta_qty
    assert rows[1][1] == "5"
    assert rows[2][1] == "-3"

    await _cleanup(engine, tenant_id, ctx["product_ids"])


async def test_export_csv_idempotent(engine, tmp_path):
    """AC9.2: 同条件 2 回実行で CSV の中身が同一。"""
    from export_inventory_for_sheet import export_inventory

    tag = uuid.uuid4().hex[:8]
    tenant_id = await _ensure_tenant(engine, f"ex_idem_{tag}")
    ctx = await _setup_movements(engine, tenant_id)

    out1 = tmp_path / "run1.csv"
    out2 = tmp_path / "run2.csv"
    await export_inventory(
        tenant_id=tenant_id, since=date(2026, 5, 1), until=None, output=out1,
        db_url=TEST_PG_URL,
    )
    await export_inventory(
        tenant_id=tenant_id, since=date(2026, 5, 1), until=None, output=out2,
        db_url=TEST_PG_URL,
    )

    assert out1.read_text("utf-8") == out2.read_text("utf-8"), \
        "同条件で 2 回実行した CSV は完全に同一であること"

    await _cleanup(engine, tenant_id, ctx["product_ids"])


async def test_export_csv_tenant_isolation(engine, tmp_path):
    """tenant_id でフィルタが効くこと (他テナントの movements は含まれない)。"""
    from export_inventory_for_sheet import export_inventory

    tag = uuid.uuid4().hex[:8]
    tenant_a = await _ensure_tenant(engine, f"ex_iso_a_{tag}")
    tenant_b = await _ensure_tenant(engine, f"ex_iso_b_{tag}")
    ctx_a = await _setup_movements(engine, tenant_a)
    ctx_b = await _setup_movements(engine, tenant_b)

    output = tmp_path / "tenant_a.csv"
    rows_count = await export_inventory(
        tenant_id=tenant_a,
        since=date(2026, 5, 1),
        until=None,
        output=output,
        db_url=TEST_PG_URL,
    )

    # 各テナント 2 件 × 1 テナントのみ
    assert rows_count == 2

    # CSV 内に tenant_b の product_id は含まれないこと
    with output.open("r", encoding="utf-8") as fh:
        content = fh.read()
    for pid in ctx_b["product_ids"]:
        assert f",{pid}," not in content and not content.startswith(f"{pid},"), \
            f"tenant_b の product_id={pid} が tenant_a の CSV に混入している"

    await _cleanup(engine, tenant_a, ctx_a["product_ids"])
    await _cleanup(engine, tenant_b, ctx_b["product_ids"])
