#!/usr/bin/env python3
"""
GAS版互換ロールへの移行スクリプト。

既存テナントに対して以下を実施:
  1. GAS版5ロール（オーナー / システム管理者 / リーダー / 営業 / CS）を作成・upsert
  2. 既存「メンバー」ロールの保持者を「CS」ロールに移し替え
  3. 「メンバー」ロールを削除

実行方法（VPS側、backendコンテナ内）:
  docker compose exec backend python /app/scripts/migrate_roles_gas_compat.py

冪等性: 複数回実行しても安全。
  - seed_system_roles が既存ロールの権限を上書きしない
  - メンバー→CS再割当は ON CONFLICT DO NOTHING
  - メンバー削除は IF EXISTS 相当

変更履歴:
  2026-04-16: 初版作成
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

# /app/scripts/ から /app を sys.path に追加（app.services.tenant を import するため）
_APP_ROOT = Path(__file__).resolve().parent.parent
if str(_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_ROOT))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.services.tenant import seed_system_roles

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    logger.error("DATABASE_URL 環境変数が設定されていません")
    sys.exit(1)


async def get_active_tenants(engine) -> list[tuple[int, str]]:
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT id, tenant_code FROM public.tenants WHERE is_active = true ORDER BY id")
        )
        return [(row.id, row.tenant_code) for row in result]


async def migrate_tenant(engine, tenant_id: int) -> None:
    """単一テナントに対してロール移行を実施。"""
    schema_name = f"tenant_{tenant_id:03d}"
    async with engine.begin() as conn:
        # search_pathとtenant_idを設定（RLS用）
        await conn.execute(text(f"SET search_path = {schema_name}, public"))
        await conn.execute(text(f"SET app.tenant_id = '{tenant_id}'"))

        # 1. GAS版互換の5ロールをシード（既存ロールの権限は保持される）
        # SQLAlchemyのAsyncConnection を AsyncSession 互換インターフェースとして渡す
        # seed_system_roles は db.execute() を呼ぶだけなので動作する
        await seed_system_roles(conn, tenant_id, schema_name)

        # 2. メンバー → CS 移行
        role_ids = await conn.execute(
            text(f"""
                SELECT name, id FROM {schema_name}.roles
                WHERE tenant_id = :tid AND name IN ('メンバー', 'CS')
            """),
            {"tid": tenant_id},
        )
        role_map = {row.name: row.id for row in role_ids}
        member_id = role_map.get("メンバー")
        cs_id = role_map.get("CS")

        if member_id is not None and cs_id is not None:
            # メンバー役割を持つユーザーをCSに移行
            reassign = await conn.execute(
                text(f"""
                    INSERT INTO {schema_name}.user_roles (user_id, role_id, assigned_at)
                    SELECT user_id, :cs_id, NOW()
                    FROM {schema_name}.user_roles
                    WHERE role_id = :mid
                    ON CONFLICT (user_id, role_id) DO NOTHING
                    RETURNING user_id
                """),
                {"cs_id": cs_id, "mid": member_id},
            )
            migrated = len(reassign.fetchall())
            logger.info("  メンバー→CS 移行: %d ユーザー", migrated)

            # メンバーロールを削除（CASCADEでuser_roles/role_permissionsも自動削除）
            await conn.execute(
                text(f"DELETE FROM {schema_name}.roles WHERE id = :id"),
                {"id": member_id},
            )
            logger.info("  メンバーロールを削除")
        elif member_id is not None and cs_id is None:
            logger.warning("  CS ロールが作成されていません（seed失敗？）。メンバー削除をスキップ")
        else:
            logger.info("  メンバーロールなし（既にGAS互換）")

    logger.info("✓ tenant_%03d 移行完了", tenant_id)


async def main() -> None:
    url = DATABASE_URL
    if url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://"):]

    engine = create_async_engine(url, echo=False)
    try:
        logger.info("=== GAS互換ロール移行 開始 ===")
        tenants = await get_active_tenants(engine)
        logger.info("対象テナント: %d", len(tenants))
        for tenant_id, tenant_code in tenants:
            logger.info("--- tenant_id=%d (%s) ---", tenant_id, tenant_code)
            await migrate_tenant(engine, tenant_id)
        logger.info("=== 完了 ===")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
