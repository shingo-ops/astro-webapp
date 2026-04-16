#!/usr/bin/env python3
"""
Phase 1 マイグレーションスクリプト。

既存の全テナントに対して Phase 1 のテーブル追加・拡張を適用する。
マイグレーションSQLファイル（migrations/002, 003）を順に実行し、
既存ユーザーへのシステムロール自動割り当てまで行う。

実行方法（VPS側）:
    docker compose exec backend python /app/scripts/migrate_phase1.py

変更履歴:
    2026-04-16: 初版作成
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    logger.error("DATABASE_URL 環境変数が設定されていません")
    sys.exit(1)

# migrations/ ディレクトリを解決（コンテナ内では /app/migrations、ホスト側では相対パス）
BASE_DIR = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = BASE_DIR / "migrations"
PERMISSIONS_SQL = MIGRATIONS_DIR / "002_add_permissions_master.sql"
TENANT_TEMPLATE_SQL = MIGRATIONS_DIR / "003_add_phase1_tenant_tables.sql"

# 「メンバー」ロールに付与するデフォルト権限
MEMBER_PERMISSIONS = {
    "dashboard.view",
    "reports.view",
    "customers.view",
    "leads.view",
    "deals.view",
    "orders.view",
    "teams.view",
}


async def apply_permissions_master(engine) -> None:
    """public.permissions を作成＋シード。全テナント共有なので1回だけ実行。"""
    sql = PERMISSIONS_SQL.read_text(encoding="utf-8")
    async with engine.begin() as conn:
        await conn.execute(text(sql))
    logger.info("✓ public.permissions マスターテーブルを作成/更新")


async def get_active_tenants(engine) -> list[tuple[int, str]]:
    """有効なテナント一覧を返す。"""
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT id, tenant_code FROM public.tenants WHERE is_active = true ORDER BY id")
        )
        return [(row.id, row.tenant_code) for row in result]


def build_tenant_sql(tenant_id: int) -> str:
    """テンプレートSQLに schema 等を埋め込む。"""
    template = TENANT_TEMPLATE_SQL.read_text(encoding="utf-8")
    schema_name = f"tenant_{tenant_id:03d}"
    return template.format(
        schema=schema_name,
        schema_raw=schema_name,
        tenant_id=tenant_id,
    )


async def apply_tenant_migration(engine, tenant_id: int) -> None:
    """テナント単位でスキーマ拡張を適用。"""
    sql = build_tenant_sql(tenant_id)
    async with engine.begin() as conn:
        # DO $$ ブロックや関数定義は ; 分割せず1ステートメントで実行
        await conn.execute(text(sql))
    logger.info("✓ tenant_%03d スキーマ拡張適用完了", tenant_id)


async def seed_system_roles(engine, tenant_id: int) -> None:
    """
    システムロール「オーナー」「メンバー」を作成し、権限を割り当てる。
    既存ユーザー（role=admin → オーナー、それ以外 → メンバー）にも自動付与。
    """
    schema = f"tenant_{tenant_id:03d}"
    async with engine.begin() as conn:
        # RLS用のapp.tenant_idを設定
        await conn.execute(text(f"SET search_path = {schema}, public"))
        await conn.execute(text(f"SET app.tenant_id = '{tenant_id}'"))

        # オーナーロール作成
        owner_result = await conn.execute(
            text("""
                INSERT INTO roles (tenant_id, name, color, priority, is_system, description)
                VALUES (:tid, 'オーナー', '#e74c3c', 1000, TRUE, 'テナントの全権限を持つシステムロール')
                ON CONFLICT (tenant_id, name) DO UPDATE SET priority = EXCLUDED.priority
                RETURNING id
            """),
            {"tid": tenant_id},
        )
        owner_id = owner_result.scalar_one()

        # メンバーロール作成
        member_result = await conn.execute(
            text("""
                INSERT INTO roles (tenant_id, name, color, priority, is_system, description)
                VALUES (:tid, 'メンバー', '#3498db', 1, TRUE, 'デフォルトの標準メンバーロール')
                ON CONFLICT (tenant_id, name) DO UPDATE SET priority = EXCLUDED.priority
                RETURNING id
            """),
            {"tid": tenant_id},
        )
        member_id = member_result.scalar_one()

        # 既存の権限割り当てをクリア（冪等性確保）
        await conn.execute(
            text("DELETE FROM role_permissions WHERE role_id IN (:owner, :member)"),
            {"owner": owner_id, "member": member_id},
        )

        # オーナーに全権限を付与
        await conn.execute(
            text("""
                INSERT INTO role_permissions (role_id, permission_id)
                SELECT :role_id, id FROM public.permissions
            """),
            {"role_id": owner_id},
        )

        # メンバーにデフォルト権限を付与（オーナーは既に全権限所持）
        for key in MEMBER_PERMISSIONS:
            await conn.execute(
                text("""
                    INSERT INTO role_permissions (role_id, permission_id)
                    SELECT :role_id, id FROM public.permissions WHERE key = :key
                    ON CONFLICT DO NOTHING
                """),
                {"role_id": member_id, "key": key},
            )

        # 既存ユーザーへのロール割り当て
        #   role='admin' → オーナー、それ以外 → メンバー
        users_result = await conn.execute(
            text("SELECT id, role FROM public.users WHERE tenant_id = :tid"),
            {"tid": tenant_id},
        )
        for row in users_result:
            target_role_id = owner_id if row.role == "admin" else member_id
            await conn.execute(
                text("""
                    INSERT INTO user_roles (user_id, role_id)
                    VALUES (:uid, :rid)
                    ON CONFLICT (user_id, role_id) DO NOTHING
                """),
                {"uid": row.id, "rid": target_role_id},
            )

    logger.info("✓ tenant_%03d システムロール＋既存ユーザー割り当て完了", tenant_id)


async def main() -> None:
    # asyncpg URL形式に変換（postgresql:// → postgresql+asyncpg://）
    url = DATABASE_URL
    if url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://"):]

    engine = create_async_engine(url, echo=False)

    try:
        logger.info("=== Phase 1 マイグレーション開始 ===")
        await apply_permissions_master(engine)

        tenants = await get_active_tenants(engine)
        logger.info("対象テナント数: %d", len(tenants))

        for tenant_id, tenant_code in tenants:
            logger.info("--- tenant_id=%d (%s) ---", tenant_id, tenant_code)
            await apply_tenant_migration(engine, tenant_id)
            await seed_system_roles(engine, tenant_id)

        logger.info("=== Phase 1 マイグレーション完了 ===")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
