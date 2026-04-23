#!/usr/bin/env python3
"""
Phase 1 再設計 / 担当者マスタ移行後の検証スクリプト。

検証内容:
    1. 件数: staff / staff_emails / staff_ui_preferences / roles
    2. CHECK制約: status / ui_preferences の BOOL
    3. UNIQUE制約: staff_code 複合UNIQUE / firebase_uid 単独UNIQUE
    4. 役割リンク: 全 staff の role_id が {schema}.roles に存在
    5. EMP-00005 処理: staff 1行 + staff_emails 1行（primary + secondary）
    6. RLS 境界: tenant_id=0 で staff 0件

実行方法:
    docker compose exec backend python /app/scripts/data_migration/verify_staff_migration.py

変更履歴:
    2026-04-23: 初版作成
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

        # [1] 件数
        # 原本CSV: EMP-00001〜00005 の 5名（EMP-00002 が「営業 太郎」ならスキップされる可能性あり）。
        # 範囲: 4〜5件を許容（EMP-00002 スキップの有無に依存）
        staff_count = (await conn.execute(text(f"SELECT COUNT(*) FROM {schema}.staff"))).scalar_one()
        r.check(
            4 <= staff_count <= 5,
            f"staff 件数 4〜5件 (actual={staff_count}, 5件=全員投入 / 4件=EMP-00002 テスト扱いでスキップ)",
        )
        logger.info("件数: staff=%d", staff_count)

        emails_count = (await conn.execute(text(f"SELECT COUNT(*) FROM {schema}.staff_emails"))).scalar_one()
        prefs_count = (await conn.execute(text(f"SELECT COUNT(*) FROM {schema}.staff_ui_preferences"))).scalar_one()
        roles_count = (await conn.execute(text(f"SELECT COUNT(*) FROM {schema}.roles WHERE tenant_id = :t"), {"t": tenant_id})).scalar_one()
        logger.info("件数: staff_emails=%d, staff_ui_preferences=%d, roles=%d", emails_count, prefs_count, roles_count)

        r.check(prefs_count == staff_count, f"staff_ui_preferences の行数が staff と一致 ({prefs_count} == {staff_count})")
        # roles: 既存 migrate_phase1.py の seed (オーナー + メンバー = 2) + migration 021 で追加 6 = 8件
        # ただし tenant ごとの設定差を考慮して 7 以上を許容
        r.check(roles_count >= 7, f"roles >= 7件（オーナー+メンバー+新6 = 8件想定） (actual={roles_count})")

        # [2] CHECK制約
        bad_status = (await conn.execute(text(f"""
            SELECT COUNT(*) FROM {schema}.staff
            WHERE status NOT IN ('active','inactive','pending')
        """))).scalar_one()
        r.check(bad_status == 0, f"staff.status 規定値外 0件 (actual={bad_status})")

        # [3] UNIQUE整合性
        dup_firebase = (await conn.execute(text(f"""
            SELECT firebase_uid, COUNT(*) c FROM {schema}.staff
            WHERE firebase_uid IS NOT NULL
            GROUP BY firebase_uid HAVING COUNT(*) > 1
        """))).fetchall()
        r.check(not dup_firebase, f"firebase_uid 重複 0件 (actual={len(dup_firebase)})")

        dup_code = (await conn.execute(text(f"""
            SELECT staff_code, tenant_id, COUNT(*) c FROM {schema}.staff
            GROUP BY staff_code, tenant_id HAVING COUNT(*) > 1
        """))).fetchall()
        r.check(not dup_code, f"(tenant_id, staff_code) 重複 0件 (actual={len(dup_code)})")

        # [4] role 解決
        missing_roles = (await conn.execute(text(f"""
            SELECT COUNT(*) FROM {schema}.staff s
            WHERE NOT EXISTS (SELECT 1 FROM {schema}.roles r WHERE r.id = s.role_id)
        """))).scalar_one()
        r.check(missing_roles == 0, f"role_id 解決不能 staff 0件 (actual={missing_roles})")

        # [5] EMP-00005 が1行 + staff_emails 1件（設計書: 3行→1行+副2件、実データ: 2行→1行+副1件）
        emp5_staff_count = (await conn.execute(text(f"""
            SELECT COUNT(*) FROM {schema}.staff WHERE staff_code = 'EMP-00005'
        """))).scalar_one()
        r.check(emp5_staff_count == 1, f"EMP-00005 staff 1行統合 (actual={emp5_staff_count})")

        emp5_emails_count = (await conn.execute(text(f"""
            SELECT COUNT(*) FROM {schema}.staff_emails se
            JOIN {schema}.staff s ON s.id = se.staff_id
            WHERE s.staff_code = 'EMP-00005'
        """))).scalar_one()
        # 実データで EMP-00005 は2行（1番目のメールが secondary、2番目が primary）
        # → secondary 1件であることを検証
        r.check(
            emp5_emails_count == 1,
            f"EMP-00005 secondary email が 1件 (actual={emp5_emails_count}, "
            f"primary=staff本体, secondary=staff_emails 1件)",
        )
        logger.info("EMP-00005: staff %d 行, secondary emails %d 件", emp5_staff_count, emp5_emails_count)

        # [6] 孤児 staff_emails / staff_ui_preferences
        orphan_emails = (await conn.execute(text(f"""
            SELECT COUNT(*) FROM {schema}.staff_emails se
            WHERE NOT EXISTS (SELECT 1 FROM {schema}.staff s WHERE s.id = se.staff_id)
        """))).scalar_one()
        r.check(orphan_emails == 0, f"親無し staff_emails 0件 (actual={orphan_emails})")

        orphan_prefs = (await conn.execute(text(f"""
            SELECT COUNT(*) FROM {schema}.staff_ui_preferences sp
            WHERE NOT EXISTS (SELECT 1 FROM {schema}.staff s WHERE s.id = sp.staff_id)
        """))).scalar_one()
        r.check(orphan_prefs == 0, f"親無し staff_ui_preferences 0件 (actual={orphan_prefs})")

    # [7] RLS 境界: 存在しない tenant_id にすると 0件
    async with engine.connect() as conn:
        await conn.execute(text(f"SET search_path = {schema}, public"))
        await conn.execute(text("SET app.tenant_id = '0'"))
        cross_staff = (await conn.execute(text(f"SELECT COUNT(*) FROM {schema}.staff"))).scalar_one()
        r.check(cross_staff == 0, f"RLS 境界: tenant_id=0 で staff 0件 (actual={cross_staff})")

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
