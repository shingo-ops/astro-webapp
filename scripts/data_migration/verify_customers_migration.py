#!/usr/bin/env python3
"""
Phase 1 再設計 / 顧客マスタ移行後の検証スクリプト。

検証内容:
    1. 件数: customers / customer_addresses / customer_sales_channels / customer_discord
    2. CHECK制約: trust_level / address_type / status / monthly_forecast_source
    3. 外部整合性: address の country_code が有効 ISO 3166-1 alpha-2、phone が E.164 形式 or NULL
    4. 重複候補: CT-00030 / CT-00032 が status='pending_dedup_review' タグ付きで投入されている
    5. RLS: テナント越境で他テナント行が見えない（SET app.tenant_id=0 で件数 0 になるか）

実行方法:
    docker compose exec backend python /app/scripts/data_migration/verify_customers_migration.py

変更履歴:
    2026-04-23: 初版作成
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
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
E164_PATTERN = re.compile(r"^\+\d{6,15}$")
ISO_ALPHA2_PATTERN = re.compile(r"^[A-Z]{2}$")


class VerifyResult:
    def __init__(self) -> None:
        self.failed: list[str] = []
        self.passed: list[str] = []

    def check(self, cond: bool, msg: str) -> None:
        (self.passed if cond else self.failed).append(msg)

    def report(self) -> bool:
        logger.info("--- 検証結果 ---")
        for m in self.passed:
            logger.info("  ✓ %s", m)
        for m in self.failed:
            logger.error("  ✗ %s", m)
        logger.info("PASS: %d / FAIL: %d", len(self.passed), len(self.failed))
        return not self.failed


async def get_tenant_info(engine, tenant_code: str) -> tuple[int, str]:
    async with engine.connect() as conn:
        row = (await conn.execute(
            text("SELECT id FROM public.tenants WHERE tenant_code = :code AND is_active = true"),
            {"code": tenant_code},
        )).first()
        if not row:
            raise RuntimeError(f"テナント '{tenant_code}' が見つかりません")
        return row.id, f"tenant_{row.id:03d}"


async def verify(engine, tenant_id: int, schema: str) -> VerifyResult:
    r = VerifyResult()
    async with engine.connect() as conn:
        await conn.execute(text(f"SET search_path = {schema}, public"))
        await conn.execute(text(f"SET app.tenant_id = '{tenant_id}'"))

        # [1] 件数（原本CSV: CT-00001〜CT-00052 の約52件）
        total_customers = (await conn.execute(text(f"SELECT COUNT(*) FROM {schema}.customers"))).scalar_one()
        # 設計書想定 52 件、実データは CSV エクスポートの最終行有無で ±1 の誤差あり
        r.check(
            50 <= total_customers <= 52,
            f"customers 件数が 50-52 の範囲内 (actual={total_customers})",
        )
        logger.info("件数: customers=%d", total_customers)

        addr_count = (await conn.execute(text(f"SELECT COUNT(*) FROM {schema}.customer_addresses"))).scalar_one()
        channels_count = (await conn.execute(text(f"SELECT COUNT(*) FROM {schema}.customer_sales_channels"))).scalar_one()
        discord_count = (await conn.execute(text(f"SELECT COUNT(*) FROM {schema}.customer_discord"))).scalar_one()
        logger.info("件数: addresses=%d, channels=%d, discord=%d", addr_count, channels_count, discord_count)
        # 設計書目安: 約104行（1顧客あたり billing+delivery の2行、住所未記入は例外）
        r.check(
            addr_count <= total_customers * 2,
            f"customer_addresses が customers の2倍以内 (actual={addr_count}, max={total_customers * 2})",
        )
        # (customer_id, address_type) の重複が無い（再実行時に二重化しない前提の検証）
        dup_addr = (await conn.execute(text(f"""
            SELECT customer_id, address_type, COUNT(*) c
            FROM {schema}.customer_addresses
            GROUP BY customer_id, address_type HAVING COUNT(*) > 1
        """))).fetchall()
        r.check(
            not dup_addr,
            f"customer_addresses の (customer_id, address_type) 重複 0件 (actual={len(dup_addr)})",
        )

        # [2] CHECK制約違反が無いこと
        bad_trust = (await conn.execute(text(f"""
            SELECT COUNT(*) FROM {schema}.customers
            WHERE trust_level IS NOT NULL AND (trust_level < 1 OR trust_level > 5)
        """))).scalar_one()
        r.check(bad_trust == 0, f"customers.trust_level の範囲外 0件 (actual={bad_trust})")

        bad_addr_type = (await conn.execute(text(f"""
            SELECT COUNT(*) FROM {schema}.customer_addresses
            WHERE address_type NOT IN ('billing', 'delivery')
        """))).scalar_one()
        r.check(bad_addr_type == 0, f"customer_addresses.address_type 規定値外 0件 (actual={bad_addr_type})")

        bad_status = (await conn.execute(text(f"""
            SELECT COUNT(*) FROM {schema}.customers
            WHERE status NOT IN ('active','inactive','archived','pending_dedup_review')
        """))).scalar_one()
        r.check(bad_status == 0, f"customers.status 規定値外 0件 (actual={bad_status})")

        bad_forecast_src = (await conn.execute(text(f"""
            SELECT COUNT(*) FROM {schema}.customers
            WHERE monthly_forecast_source IS NOT NULL
              AND monthly_forecast_source NOT IN ('manual','ai_analysis')
        """))).scalar_one()
        r.check(bad_forecast_src == 0, f"customers.monthly_forecast_source 規定値外 0件 (actual={bad_forecast_src})")

        # [3] country_code / 電話番号フォーマット
        bad_country_rows = (await conn.execute(text(f"""
            SELECT country_code FROM {schema}.customer_addresses
            WHERE country_code IS NOT NULL
        """))).fetchall()
        bad_country = [row.country_code for row in bad_country_rows if not ISO_ALPHA2_PATTERN.match(row.country_code)]
        r.check(not bad_country, f"country_code が ISO 3166-1 alpha-2 形式 (不正 {len(bad_country)}件: {bad_country[:5]})")

        phones_rows = (await conn.execute(text(f"""
            SELECT telephone FROM {schema}.customer_addresses
            WHERE telephone IS NOT NULL
        """))).fetchall()
        bad_phones = [row.telephone for row in phones_rows if not E164_PATTERN.match(row.telephone)]
        r.check(not bad_phones, f"電話番号が E.164 形式 (不正 {len(bad_phones)}件: {bad_phones[:5]})")

        # [4] 重複候補タグ
        dup_tag_count = (await conn.execute(text(f"""
            SELECT COUNT(*) FROM {schema}.customers
            WHERE status = 'pending_dedup_review'
              AND customer_code IN ('CT-00030', 'CT-00032')
        """))).scalar_one()
        r.check(dup_tag_count == 2, f"CT-00030/00032 が pending_dedup_review 2件 (actual={dup_tag_count})")

        # [4.5] sales_rep_id NULL 件数（テストデータスキップや lookup 失敗で発生）
        null_rep_rows = (await conn.execute(text(f"""
            SELECT customer_code FROM {schema}.customers
            WHERE sales_rep_id IS NULL
            ORDER BY customer_code
        """))).fetchall()
        logger.info(
            "sales_rep_id=NULL の顧客: %d 件 (%s)",
            len(null_rep_rows),
            [row.customer_code for row in null_rep_rows[:10]],
        )
        # エラーにはせず情報として出す（営業担当者列が空の顧客は許容）

        # [5] 副テーブル関連性（親の customer が全て存在する）
        orphan_addr = (await conn.execute(text(f"""
            SELECT COUNT(*) FROM {schema}.customer_addresses a
            WHERE NOT EXISTS (SELECT 1 FROM {schema}.customers c WHERE c.id = a.customer_id)
        """))).scalar_one()
        r.check(orphan_addr == 0, f"親無し customer_addresses 0件 (actual={orphan_addr})")

        orphan_chan = (await conn.execute(text(f"""
            SELECT COUNT(*) FROM {schema}.customer_sales_channels cs
            WHERE NOT EXISTS (SELECT 1 FROM {schema}.customers c WHERE c.id = cs.customer_id)
        """))).scalar_one()
        r.check(orphan_chan == 0, f"親無し customer_sales_channels 0件 (actual={orphan_chan})")

        # [6] RLS 境界確認: app.tenant_id を存在しない値にすると 0件
    async with engine.connect() as conn:
        await conn.execute(text(f"SET search_path = {schema}, public"))
        await conn.execute(text("SET app.tenant_id = '0'"))
        cross_tenant = (await conn.execute(text(f"SELECT COUNT(*) FROM {schema}.customers"))).scalar_one()
        r.check(cross_tenant == 0, f"RLS 境界: tenant_id=0 で customers 0件 (actual={cross_tenant})")

    return r


async def main() -> None:
    engine = create_async_engine(DATABASE_URL, echo=False)
    try:
        tenant_id, schema = await get_tenant_info(engine, TENANT_CODE)
        logger.info("検証対象: tenant_id=%d, schema=%s", tenant_id, schema)
        result = await verify(engine, tenant_id, schema)
        if result.report():
            logger.info("🎉 全検証 PASS")
            sys.exit(0)
        else:
            logger.error("💥 検証 FAIL")
            sys.exit(1)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
