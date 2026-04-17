#!/usr/bin/env python3
"""
内部テスト用ユーザーセットアップスクリプト。

Firebase Auth にユーザー作成 → DB 登録 → ロール付与を一括実行。

実行方法（VPS側、backendコンテナ内）:
  docker compose exec backend python /app/scripts/setup_test_users.py

前提:
  - firebase-credentials.json がコンテナ内に存在すること
  - DATABASE_URL 環境変数が設定されていること
  - テナントが既に作成済みであること

変更履歴:
  2026-04-17: 初版作成
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parent.parent
if str(_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_ROOT))

import firebase_admin
from firebase_admin import auth as firebase_auth, credentials
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    logger.error("DATABASE_URL not set")
    sys.exit(1)

# Firebase 初期化
cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "/app/firebase-credentials.json")
if os.path.exists(cred_path):
    cred = credentials.Certificate(cred_path)
    firebase_admin.initialize_app(cred)
else:
    firebase_admin.initialize_app()

# ===========================================================================
# テストユーザー定義
# ===========================================================================

# テナント1: HIGH LIFE JPN
TENANT_1_CODE = "highlife-jpn"
TENANT_1_NAME = "HIGH LIFE JPN"
TENANT_1_USERS = [
    {"username": "谷澤 伸吾", "email": "shingo@treasureislandjp.com", "role": "admin", "crm_role": "オーナー"},
    {"username": "営業 一郎", "email": "highlifejpn@gmail.com", "role": "user", "crm_role": "営業"},
    {"username": "カスタ マイコ", "email": "tani.shingo.0115@gmail.com", "role": "user", "crm_role": "CS"},
    {"username": "受注 発送", "email": "highlifeexport@gmail.com", "role": "user", "crm_role": "営業"},
]

# テナント2
TENANT_2_CODE = "test-tenant-2"
TENANT_2_NAME = "テストテナント2"
TENANT_2_USERS = [
    {"username": "山田 太郎", "email": "justhavefunnnnn@gmail.com", "role": "admin", "crm_role": "オーナー"},
    {"username": "営業 二郎", "email": "hlj20200401@gmail.com", "role": "user", "crm_role": "CS"},
]

DEFAULT_PASSWORD = "JarvisTest2026!"  # 初回ログイン後に変更を促す


def create_or_get_firebase_user(email: str, display_name: str, password: str) -> str:
    """Firebase Auth にユーザーを作成（既存なら取得）し、UID を返す。"""
    try:
        user = firebase_auth.get_user_by_email(email)
        logger.info("  Firebase: 既存ユーザー %s (uid=%s)", email, user.uid)
        return user.uid
    except firebase_admin.exceptions.NotFoundError:
        user = firebase_auth.create_user(
            email=email,
            password=password,
            display_name=display_name,
            email_verified=False,
        )
        logger.info("  Firebase: 新規作成 %s (uid=%s)", email, user.uid)
        return user.uid


async def ensure_tenant(engine, tenant_code: str, tenant_name: str) -> int:
    """テナントを作成または取得し、ID を返す。"""
    async with engine.begin() as conn:
        result = await conn.execute(
            text("SELECT id FROM public.tenants WHERE tenant_code = :code"),
            {"code": tenant_code},
        )
        row = result.first()
        if row:
            logger.info("テナント '%s' 既存 (id=%d)", tenant_code, row[0])
            return row[0]

        # 新規作成
        result = await conn.execute(
            text("""
                INSERT INTO public.tenants (tenant_name, tenant_code, is_active)
                VALUES (:name, :code, TRUE)
                RETURNING id
            """),
            {"name": tenant_name, "code": tenant_code},
        )
        tenant_id = result.scalar_one()
        logger.info("テナント '%s' 新規作成 (id=%d)", tenant_code, tenant_id)

        # テナントスキーマ作成
        from app.services.tenant import create_tenant_schema
        # create_tenant_schema は AsyncSession を期待するが、
        # ここでは raw connection を使う。代替として SQL を直接実行。
        schema_name = f"tenant_{tenant_id:03d}"
        await conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema_name}"))
        logger.info("  スキーマ %s 作成", schema_name)

    return tenant_id


async def apply_tenant_schema(engine, tenant_id: int):
    """テナントスキーマにテーブルとRLSを適用する。"""
    from app.services.tenant import (
        _TENANT_TABLES_SQL,
        _RLS_ENABLE_SQL,
        _RLS_POLICY_SQL,
        seed_system_roles,
        _split_sql_preserving_do_blocks,
    )

    schema_name = f"tenant_{tenant_id:03d}"

    async with engine.begin() as conn:
        # テーブル作成
        tables_sql = _TENANT_TABLES_SQL.format(schema=schema_name, schema_raw=schema_name, tenant_id=tenant_id)
        for stmt in _split_sql_preserving_do_blocks(tables_sql):
            stmt = stmt.strip()
            if stmt:
                await conn.execute(text(stmt))

        # RLS有効化
        enable_sql = _RLS_ENABLE_SQL.format(schema=schema_name)
        for stmt in enable_sql.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                await conn.execute(text(stmt))

        # RLSポリシー
        policy_sql = _RLS_POLICY_SQL.format(schema=schema_name, schema_raw=schema_name)
        await conn.execute(text(policy_sql))

        # システムロールシード
        await seed_system_roles(conn, tenant_id, schema_name)

    logger.info("  テーブル + RLS + ロールシード完了")


async def register_user(engine, tenant_id: int, firebase_uid: str, user_data: dict):
    """DB にユーザーを登録し、ロールを付与する。"""
    from app.auth.utils import hash_password

    schema_name = f"tenant_{tenant_id:03d}"

    async with engine.begin() as conn:
        # 既存チェック
        existing = await conn.execute(
            text("SELECT id FROM public.users WHERE email = :email"),
            {"email": user_data["email"]},
        )
        if existing.first():
            logger.info("  DB: 既存ユーザー %s（スキップ）", user_data["email"])
            return

        # ユーザー作成
        result = await conn.execute(
            text("""
                INSERT INTO public.users (tenant_id, username, email, password_hash, full_name, role, is_active)
                VALUES (:tid, :username, :email, :hash, :fullname, :role, TRUE)
                RETURNING id
            """),
            {
                "tid": tenant_id,
                "username": user_data["username"],
                "email": user_data["email"],
                "hash": hash_password(DEFAULT_PASSWORD),
                "fullname": user_data["username"],
                "role": user_data["role"],
            },
        )
        user_id = result.scalar_one()
        logger.info("  DB: ユーザー作成 %s (id=%d)", user_data["email"], user_id)

        # Firebase カスタムクレーム設定
        firebase_auth.set_custom_user_claims(firebase_uid, {"tenant_id": tenant_id})
        logger.info("  Firebase: tenant_id=%d クレーム設定", tenant_id)

        # CRMロール付与
        await conn.execute(text(f"SET search_path = {schema_name}, public"))
        await conn.execute(text(f"SET app.tenant_id = '{tenant_id}'"))

        role_result = await conn.execute(
            text("SELECT id FROM roles WHERE tenant_id = :tid AND name = :name"),
            {"tid": tenant_id, "name": user_data["crm_role"]},
        )
        role_row = role_result.first()
        if role_row:
            await conn.execute(
                text("INSERT INTO user_roles (user_id, role_id) VALUES (:uid, :rid) ON CONFLICT DO NOTHING"),
                {"uid": user_id, "rid": role_row[0]},
            )
            logger.info("  ロール '%s' 付与完了", user_data["crm_role"])
        else:
            logger.warning("  ロール '%s' が見つかりません", user_data["crm_role"])


async def main():
    url = DATABASE_URL
    if url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://"):]

    engine = create_async_engine(url, echo=False)

    try:
        logger.info("=== テストユーザーセットアップ開始 ===")

        # テナント1
        logger.info("\n--- テナント1: %s ---", TENANT_1_NAME)
        t1_id = await ensure_tenant(engine, TENANT_1_CODE, TENANT_1_NAME)
        await apply_tenant_schema(engine, t1_id)
        for u in TENANT_1_USERS:
            firebase_uid = create_or_get_firebase_user(u["email"], u["username"], DEFAULT_PASSWORD)
            await register_user(engine, t1_id, firebase_uid, u)

        # テナント2
        logger.info("\n--- テナント2: %s ---", TENANT_2_NAME)
        t2_id = await ensure_tenant(engine, TENANT_2_CODE, TENANT_2_NAME)
        await apply_tenant_schema(engine, t2_id)
        for u in TENANT_2_USERS:
            firebase_uid = create_or_get_firebase_user(u["email"], u["username"], DEFAULT_PASSWORD)
            await register_user(engine, t2_id, firebase_uid, u)

        logger.info("\n=== セットアップ完了 ===")
        logger.info("初期パスワード: %s", DEFAULT_PASSWORD)
        logger.info("※ 各ユーザーは初回ログイン後にMFA設定とパスワード変更が必要です")

    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
