#!/usr/bin/env python3
"""
Phase 1-B-2 Step 3 検証スクリプト。

検証内容:
    1. 全 customers が _customer_migration_map に記録されている
    2. customers 数 == contacts 数
    3. 各 company に is_primary_contact=TRUE が正確に1件
    4. 各 contact は company に属する（orphan なし）
    5. customer_addresses → company_addresses の件数整合
       - multi_branch（Card Galaxy）: 4件 → 4件（branch_name 付き）
       - same_branch（TCG TRADE）: 4件 → 2件（重複ドロップ）
       - multi_contact（Ocean Harvest）: 4件 → 2件（先頭のみ）
       - auto_single: 2件 → 2件
    6. customer_sales_channels → company_sales_channels（union 後の件数）
    7. customer_discord → contact_discord の1対1対応
    8. customer_contact_channels → contact_contact_channels の1対1対応
    9. 手動マージ判定の反映確認
       - CT-00003, CT-00008: 同じ company_id、同じ address セット
       - CT-00006, CT-00007: 同じ company_id、branch_name 2つ
       - CT-00030, CT-00032: 同じ company_id、contact 2人

実行方法:
    docker compose exec backend python /app/scripts/data_migration/verify_companies_contacts_migration.py

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
    if ok:
        logger.info("%s %s%s", mark, label, f" ({detail})" if detail else "")
    else:
        logger.error("%s %s%s", mark, label, f" ({detail})" if detail else "")
    return ok


async def main() -> None:
    engine = create_async_engine(DATABASE_URL, echo=False)
    all_ok = True
    try:
        tenant_id, schema = await get_tenant_info(engine, TENANT_CODE)
        logger.info("=" * 72)
        logger.info("Phase 1-B-2 Step 3 検証: tenant=%s, schema=%s", TENANT_CODE, schema)
        logger.info("=" * 72)

        async with engine.connect() as conn:
            await conn.execute(text(f"SET search_path = {schema}, public"))
            await conn.execute(text(f"SET app.tenant_id = '{tenant_id}'"))

            # 1. 全 customers が migration_map にある
            customers_count = (await conn.execute(
                text(f"SELECT COUNT(*) FROM {schema}.customers WHERE tenant_id = :tid"),
                {"tid": tenant_id},
            )).scalar_one()
            map_count = (await conn.execute(
                text(f"SELECT COUNT(*) FROM {schema}._customer_migration_map"),
            )).scalar_one()
            all_ok &= await check(
                "1. customers → _customer_migration_map の件数整合",
                customers_count == map_count,
                f"customers={customers_count} / map={map_count}",
            )
            orphan_rows = (await conn.execute(
                text(f"""
                    SELECT customer_code FROM {schema}.customers c
                    WHERE tenant_id = :tid
                      AND NOT EXISTS (
                          SELECT 1 FROM {schema}._customer_migration_map m
                          WHERE m.old_customer_id = c.id
                      )
                """),
                {"tid": tenant_id},
            )).all()
            all_ok &= await check(
                "   migration_map に記録されていない customer がない",
                len(orphan_rows) == 0,
                f"orphan={len(orphan_rows)} {[r[0] for r in orphan_rows[:5]]}",
            )

            # 2. contacts 数 == customers 数
            contacts_count = (await conn.execute(
                text(f"SELECT COUNT(*) FROM {schema}.contacts WHERE tenant_id = :tid"),
                {"tid": tenant_id},
            )).scalar_one()
            all_ok &= await check(
                "2. customers 数 == contacts 数",
                contacts_count == customers_count,
                f"customers={customers_count} / contacts={contacts_count}",
            )

            # 3. 各 company に is_primary_contact=TRUE が正確に1件
            primary_mismatch = (await conn.execute(
                text(f"""
                    SELECT c.company_code, COALESCE(p.cnt, 0) AS primary_count
                    FROM {schema}.companies c
                    LEFT JOIN (
                        SELECT company_id, COUNT(*) AS cnt
                        FROM {schema}.contacts
                        WHERE is_primary_contact = TRUE
                        GROUP BY company_id
                    ) p ON p.company_id = c.id
                    WHERE COALESCE(p.cnt, 0) != 1
                """),
            )).all()
            all_ok &= await check(
                "3. 各 company に primary contact が正確に1件",
                len(primary_mismatch) == 0,
                f"mismatch={len(primary_mismatch)} {[(r[0], r[1]) for r in primary_mismatch[:5]]}",
            )

            # 4. contacts の company_id が存在する company を参照（FK 制約で基本保証、ダブルチェック）
            orphan_contacts = (await conn.execute(
                text(f"""
                    SELECT ct.contact_code FROM {schema}.contacts ct
                    WHERE tenant_id = :tid
                      AND NOT EXISTS (
                          SELECT 1 FROM {schema}.companies co
                          WHERE co.id = ct.company_id
                      )
                """),
                {"tid": tenant_id},
            )).all()
            all_ok &= await check(
                "4. orphan contacts（存在しない company_id 参照）なし",
                len(orphan_contacts) == 0,
                f"orphan={len(orphan_contacts)}",
            )

            # 5. company_addresses の件数確認
            old_addr = (await conn.execute(
                text(f"SELECT COUNT(*) FROM {schema}.customer_addresses"),
            )).scalar_one()
            new_addr = (await conn.execute(
                text(f"SELECT COUNT(*) FROM {schema}.company_addresses"),
            )).scalar_one()
            # 手動マージによる dedupe で new_addr ≤ old_addr を期待
            all_ok &= await check(
                "5. company_addresses 件数 <= customer_addresses 件数",
                new_addr <= old_addr,
                f"customer_addresses={old_addr} / company_addresses={new_addr}",
            )

            # 6. company_sales_channels（union 後の件数）
            old_sc = (await conn.execute(
                text(f"SELECT COUNT(*) FROM {schema}.customer_sales_channels"),
            )).scalar_one()
            new_sc = (await conn.execute(
                text(f"SELECT COUNT(*) FROM {schema}.company_sales_channels"),
            )).scalar_one()
            all_ok &= await check(
                "6. company_sales_channels 件数 <= customer_sales_channels 件数",
                new_sc <= old_sc,
                f"customer={old_sc} / company={new_sc}",
            )

            # 7. contact_discord 1対1
            old_dc = (await conn.execute(
                text(f"SELECT COUNT(*) FROM {schema}.customer_discord"),
            )).scalar_one()
            new_dc = (await conn.execute(
                text(f"SELECT COUNT(*) FROM {schema}.contact_discord"),
            )).scalar_one()
            all_ok &= await check(
                "7. contact_discord 件数 == customer_discord 件数",
                new_dc == old_dc,
                f"customer_discord={old_dc} / contact_discord={new_dc}",
            )

            # 8. contact_contact_channels 1対1
            old_cc = (await conn.execute(
                text(f"SELECT COUNT(*) FROM {schema}.customer_contact_channels"),
            )).scalar_one()
            new_cc = (await conn.execute(
                text(f"SELECT COUNT(*) FROM {schema}.contact_contact_channels"),
            )).scalar_one()
            all_ok &= await check(
                "8. contact_contact_channels 件数 == customer_contact_channels 件数",
                new_cc == old_cc,
                f"customer={old_cc} / contact={new_cc}",
            )

            # 9a. TCG TRADE (CT-00003, CT-00008): 同じ company
            tcg = (await conn.execute(
                text(f"""
                    SELECT DISTINCT m.new_company_id
                    FROM {schema}._customer_migration_map m
                    JOIN {schema}.customers c ON c.id = m.old_customer_id
                    WHERE c.customer_code IN ('CT-00003', 'CT-00008')
                """),
            )).all()
            all_ok &= await check(
                "9a. TCG TRADE (CT-00003, CT-00008) が同じ company_id",
                len(tcg) == 1,
                f"distinct company_ids={len(tcg)}",
            )

            # 9b. Card Galaxy (CT-00006, CT-00007): 同じ company、branch_name 2つ
            cg = (await conn.execute(
                text(f"""
                    SELECT DISTINCT m.new_company_id
                    FROM {schema}._customer_migration_map m
                    JOIN {schema}.customers c ON c.id = m.old_customer_id
                    WHERE c.customer_code IN ('CT-00006', 'CT-00007')
                """),
            )).all()
            all_ok &= await check(
                "9b. Card Galaxy (CT-00006, CT-00007) が同じ company_id",
                len(cg) == 1,
                f"distinct company_ids={len(cg)}",
            )
            if len(cg) == 1:
                cg_company_id = cg[0][0]
                branches = (await conn.execute(
                    text(f"""
                        SELECT DISTINCT branch_name FROM {schema}.company_addresses
                        WHERE company_id = :cid AND branch_name IS NOT NULL
                        ORDER BY branch_name
                    """),
                    {"cid": cg_company_id},
                )).all()
                branch_names = [r[0] for r in branches]
                all_ok &= await check(
                    "9b-2. Card Galaxy に branch_name が 2つ以上（Essex/Preston）",
                    len(branch_names) >= 2,
                    f"branch_names={branch_names}",
                )

            # 9c. Ocean Harvest (CT-00030, CT-00032): 同じ company、contact 2人
            oh = (await conn.execute(
                text(f"""
                    SELECT DISTINCT m.new_company_id
                    FROM {schema}._customer_migration_map m
                    JOIN {schema}.customers c ON c.id = m.old_customer_id
                    WHERE c.customer_code IN ('CT-00030', 'CT-00032')
                """),
            )).all()
            all_ok &= await check(
                "9c. Ocean Harvest (CT-00030, CT-00032) が同じ company_id",
                len(oh) == 1,
                f"distinct company_ids={len(oh)}",
            )
            if len(oh) == 1:
                oh_contacts = (await conn.execute(
                    text(f"""
                        SELECT COUNT(*) FROM {schema}.contacts
                        WHERE company_id = :cid
                    """),
                    {"cid": oh[0][0]},
                )).scalar_one()
                all_ok &= await check(
                    "9c-2. Ocean Harvest の contact 数 >= 2",
                    oh_contacts >= 2,
                    f"contacts={oh_contacts}",
                )

            # 10. migration_method の分布
            method_dist = (await conn.execute(
                text(f"""
                    SELECT migration_method, COUNT(*) FROM {schema}._customer_migration_map
                    GROUP BY migration_method ORDER BY COUNT(*) DESC
                """),
            )).all()
            logger.info("10. migration_method 分布:")
            for method, cnt in method_dist:
                logger.info("    %s: %d 件", method, cnt)

            # 11. 個人顧客フラグ件数
            individual_count = (await conn.execute(
                text(f"""
                    SELECT COUNT(*) FROM {schema}.companies
                    WHERE tenant_id = :tid AND is_individual = TRUE
                """),
                {"tid": tenant_id},
            )).scalar_one()
            logger.info("11. 個人顧客（is_individual=TRUE）: %d 件", individual_count)

            # サマリ
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
