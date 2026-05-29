"""QA 2026-05-30: maintenance.purge_expired_inventory_offers の実 PostgreSQL 検証。

仕入元オファーの時間失効モデル: public.inventory の expires_at < NOW() の行のみを
削除し、expires_at が未来 / NULL の行は残すことを確認する。中央在庫は触らない。

SQLite モック禁止 (memory: feedback_evaluator_gap_2026_05_15)。purge タスクは同期
SQLAlchemy なので、_get_sync_engine を実 PostgreSQL 同期エンジンに差し替えて検証する。
"""

from __future__ import annotations

import os
import uuid
from unittest.mock import patch

import pytest

TEST_PG_URL = os.getenv("TEST_PG_URL")

pytestmark = pytest.mark.skipif(
    not TEST_PG_URL,
    reason="実 PostgreSQL 環境が必要 (TEST_PG_URL 未設定)。",
)


def _sync_url() -> str:
    # async ドライバ指定を剥がして同期 (psycopg2) URL にする
    return TEST_PG_URL.replace("+asyncpg", "")


def test_purge_deletes_only_expired_offers():
    from sqlalchemy import create_engine, text

    from app.tasks.maintenance import purge_expired_inventory_offers

    engine = create_engine(_sync_url())
    tag = uuid.uuid4().hex[:8]

    with engine.begin() as conn:
        supplier_id = conn.execute(
            text(
                "INSERT INTO public.suppliers (supplier_code, name, type, language) "
                "VALUES (:c, :n, 'individual', 'ja') RETURNING id"
            ),
            {"c": f"PURGE-S-{tag}", "n": f"purge_supplier_{tag}"},
        ).scalar_one()
        # public.inventory.product_id は FK 未設定 (INTEGER) のためダミー値で可。
        pid = 900000 + (int(supplier_id) % 100000)

        def _ins(cond: str, exp_sql: str) -> int:
            return conn.execute(
                text(
                    "INSERT INTO public.inventory "
                    "(supplier_id, product_id, condition, quantity, unit_price, "
                    " status, source, expires_at) "
                    f"VALUES (:sid, :pid, :cond, 1, 100, 'in_stock', 'f6_approved', {exp_sql}) "
                    "RETURNING id"
                ),
                {"sid": supplier_id, "pid": pid, "cond": cond},
            ).scalar_one()

        # UNIQUE(supplier_id, product_id, condition) を満たすよう condition を変える
        id_expired = _ins("new", "NOW() - INTERVAL '1 hour'")
        id_fresh = _ins("used_a", "NOW() + INTERVAL '5 hours'")
        id_perm = _ins("sealed", "NULL")

    try:
        with patch(
            "app.tasks.maintenance._get_sync_engine", return_value=engine
        ):
            result = purge_expired_inventory_offers()

        assert result["deleted"] >= 1

        with engine.connect() as conn:
            remaining = {
                r[0]
                for r in conn.execute(
                    text(
                        "SELECT id FROM public.inventory WHERE supplier_id = :sid"
                    ),
                    {"sid": supplier_id},
                )
            }
        assert id_expired not in remaining, "期限切れ (expires_at < NOW()) は削除される"
        assert id_fresh in remaining, "未来 expires_at のオファーは残る"
        assert id_perm in remaining, "expires_at NULL の恒久オファーは残る"
    finally:
        with engine.begin() as conn:
            conn.execute(
                text("DELETE FROM public.inventory WHERE supplier_id = :sid"),
                {"sid": supplier_id},
            )
            conn.execute(
                text("DELETE FROM public.suppliers WHERE id = :sid"),
                {"sid": supplier_id},
            )
        engine.dispose()
