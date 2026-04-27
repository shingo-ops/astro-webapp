#!/usr/bin/env python3
"""
Phase 1-B-2 Step 4 検証スクリプト。

migration 032 で追加した deals/orders/quotes/invoices の company_id/contact_id が
正しく backfill されているかを検証する。

検証項目:
    各テーブル（deals, orders, quotes, invoices）について:
      A. customer_id がある行は company_id/contact_id も埋まっている
      B. company_id と _customer_migration_map.new_company_id が一致
      C. contact_id と _customer_migration_map.new_contact_id が一致
      D. FK 制約（fk_{table}_company / fk_{table}_contact）が存在

実行方法:
    docker compose exec backend python /app/scripts/data_migration/verify_downstream_fk_migration.py

環境変数:
    DATABASE_URL, TENANT_CODE
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    logger.error("DATABASE_URL 環境変数が設定されていません")
    sys.exit(1)

TENANT_CODE = os.getenv("TENANT_CODE", "test-corp")

DOWNSTREAM_TABLES = ["deals", "orders", "quotes", "invoices"]


async def get_tenant_info(engine, tenant_code: str) -> tuple[int, str]:
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT id FROM public.tenants WHERE tenant_code = :code AND is_active = true"),
            {"code": tenant_code},
        )
        row = result.first()
        if not row:
            raise RuntimeError(f"テナント '{tenant_code}' が見つからないか無効です")
        return row.id, f"tenant_{row.id:03d}"


async def check(label: str, ok: bool, detail: str = "") -> bool:
    mark = "✓" if ok else "✗"
    suffix = f" ({detail})" if detail else ""
    if ok:
        logger.info("%s %s%s", mark, label, suffix)
    else:
        logger.error("%s %s%s", mark, label, suffix)
    return ok


async def verify_table(conn, schema: str, table: str) -> bool:
    """単一テーブルの 4 検証項目を実行し、全 PASS なら True。"""
    all_ok = True

    # 行数
    total = (await conn.execute(text(f"SELECT COUNT(*) FROM {schema}.{table}"))).scalar_one()
    with_customer = (await conn.execute(
        text(f"SELECT COUNT(*) FROM {schema}.{table} WHERE customer_id IS NOT NULL")
    )).scalar_one()
    with_company = (await conn.execute(
        text(f"SELECT COUNT(*) FROM {schema}.{table} WHERE company_id IS NOT NULL")
    )).scalar_one()
    with_contact = (await conn.execute(
        text(f"SELECT COUNT(*) FROM {schema}.{table} WHERE contact_id IS NOT NULL")
    )).scalar_one()

    logger.info(
        "  %s: total=%d, customer_id=%d, company_id=%d, contact_id=%d",
        table, total, with_customer, with_company, with_contact,
    )

    # A. customer_id があれば company_id も埋まっている
    missing = (await conn.execute(
        text(f"""
            SELECT COUNT(*) FROM {schema}.{table}
            WHERE customer_id IS NOT NULL
              AND (company_id IS NULL OR contact_id IS NULL)
        """)
    )).scalar_one()
    all_ok &= await check(
        f"  A-{table}: customer_id 有 → company_id/contact_id も有",
        missing == 0,
        f"missing={missing}",
    )

    # B. company_id が migration_map.new_company_id と一致
    if with_customer > 0:
        mismatch = (await conn.execute(
            text(f"""
                SELECT COUNT(*) FROM {schema}.{table} t
                JOIN {schema}._customer_migration_map m ON m.old_customer_id = t.customer_id
                WHERE t.company_id != m.new_company_id OR t.contact_id != m.new_contact_id
            """)
        )).scalar_one()
        all_ok &= await check(
            f"  B/C-{table}: company_id/contact_id が migration_map と一致",
            mismatch == 0,
            f"mismatch={mismatch}",
        )
    else:
        logger.info("  B/C-%s: スキップ（customer_id 有の行なし）", table)

    # D. FK 制約の存在
    fk_company_exists = (await conn.execute(
        text(f"""
            SELECT COUNT(*) FROM pg_constraint
            WHERE conname = 'fk_{table}_company'
              AND connamespace = (SELECT oid FROM pg_namespace WHERE nspname = :schema)
        """),
        {"schema": schema},
    )).scalar_one()
    fk_contact_exists = (await conn.execute(
        text(f"""
            SELECT COUNT(*) FROM pg_constraint
            WHERE conname = 'fk_{table}_contact'
              AND connamespace = (SELECT oid FROM pg_namespace WHERE nspname = :schema)
        """),
        {"schema": schema},
    )).scalar_one()
    all_ok &= await check(
        f"  D-{table}: FK fk_{table}_company 存在",
        fk_company_exists == 1,
        f"count={fk_company_exists}",
    )
    all_ok &= await check(
        f"  D-{table}: FK fk_{table}_contact 存在",
        fk_contact_exists == 1,
        f"count={fk_contact_exists}",
    )
    return all_ok


async def main() -> None:
    engine = create_async_engine(DATABASE_URL, echo=False)
    all_ok = True
    try:
        tenant_id, schema = await get_tenant_info(engine, TENANT_CODE)
        logger.info("=" * 72)
        logger.info("Phase 1-B-2 Step 4 検証: tenant=%s, schema=%s", TENANT_CODE, schema)
        logger.info("=" * 72)

        async with engine.connect() as conn:
            await conn.execute(text(f"SET search_path = {schema}, public"))
            await conn.execute(text(f"SET app.tenant_id = '{tenant_id}'"))

            for table in DOWNSTREAM_TABLES:
                exists = (await conn.execute(
                    text("""
                        SELECT COUNT(*) FROM pg_tables
                        WHERE schemaname = :schema AND tablename = :tbl
                    """),
                    {"schema": schema, "tbl": table},
                )).scalar_one()
                if not exists:
                    logger.warning("テーブル未作成、skip: %s.%s", schema, table)
                    continue
                logger.info("--- %s ---", table)
                all_ok &= await verify_table(conn, schema, table)

            logger.info("=" * 72)
            if all_ok:
                logger.info("✓ 全検証 PASS")
            else:
                logger.error("✗ 一部検証 FAIL（上記エラー参照）")
            logger.info("=" * 72)

    finally:
        await engine.dispose()

    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    asyncio.run(main())
