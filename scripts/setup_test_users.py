#!/usr/bin/env python3
"""
内部テスト用ユーザーセットアップスクリプト。

Firebase Auth にユーザー作成 → DB 登録 → ロール付与を一括実行。

実行方法（VPS側、backendコンテナ内）:
  docker compose exec -e ALLOW_TEST_USER_RESET=1 backend python /app/scripts/setup_test_users.py

前提:
  - firebase-credentials.json がコンテナ内に存在すること
  - DATABASE_URL 環境変数が設定されていること
  - テナントが既に作成済みであること
  - ALLOW_TEST_USER_RESET=1 を環境変数で渡すこと（誤実行防止のガード）

変更履歴:
  2026-04-17: 初版作成
  2026-04-21: ユーザーごとにランダムパスワード生成、CSV出力、既存ユーザーのパスワード上書きに対応
  2026-04-21: ALLOW_TEST_USER_RESET ガード追加、副作用最小化、generate_password を共有モジュールへ移動
"""
from __future__ import annotations

import asyncio
import csv
import logging
import os
import sys
from datetime import datetime, timezone
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

# 本番事故防止ガード：このスクリプトは email 一致で password_hash を強制上書きするため、
# 本番運用後に誤って実行されると本番ユーザーのパスワードが破壊される。
# 明示的に環境変数を立てない限り起動を拒否する。
if os.getenv("ALLOW_TEST_USER_RESET") != "1":
    logger.error(
        "誤実行防止: 環境変数 ALLOW_TEST_USER_RESET=1 を付けて実行してください。"
        " 例: docker compose exec -e ALLOW_TEST_USER_RESET=1 backend python /app/scripts/setup_test_users.py"
    )
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

# (tenant_code, username, email, crm_role, password)
PasswordRow = tuple[str, str, str, str, str]


def create_or_update_firebase_user(email: str, display_name: str, password: str) -> str:
    """Firebase Auth にユーザーを作成または既存ユーザーのパスワードを上書きし、UID を返す。

    既存ユーザーの display_name はユーザー側でカスタマイズされている可能性があるため触らず、
    パスワードのみ上書きする。
    """
    try:
        user = firebase_auth.get_user_by_email(email)
        firebase_auth.update_user(user.uid, password=password)
        logger.info("  Firebase: 既存ユーザー %s のパスワードを更新 (uid=%s)", email, user.uid)
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


async def register_user(engine, tenant_id: int, firebase_uid: str, user_data: dict, password: str):
    """DB にユーザーを登録（既存なら password_hash を上書き）し、ロールを付与する。

    既存ユーザーの tenant_id はテナント移動の可能性があるため UPDATE 対象から除外する。
    新規作成時のみ tenant_id を設定する。
    """
    from app.auth.utils import hash_password

    schema_name = f"tenant_{tenant_id:03d}"
    password_hash = hash_password(password)

    async with engine.begin() as conn:
        existing = await conn.execute(
            text("SELECT id, tenant_id FROM public.users WHERE email = :email"),
            {"email": user_data["email"]},
        )
        existing_row = existing.first()
        if existing_row:
            user_id, existing_tenant_id = existing_row
            if existing_tenant_id != tenant_id:
                logger.warning(
                    "  DB: %s は別テナント (id=%d) に存在するため tenant_id は変更しません（パスワード等のみ更新）",
                    user_data["email"], existing_tenant_id,
                )
            await conn.execute(
                text("""
                    UPDATE public.users
                    SET password_hash = :hash,
                        is_active = TRUE
                    WHERE id = :id
                """),
                {
                    "hash": password_hash,
                    "id": user_id,
                },
            )
            logger.info("  DB: 既存ユーザー %s のパスワードを更新 (id=%d)", user_data["email"], user_id)
        else:
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
                    "hash": password_hash,
                    "fullname": user_data["username"],
                    "role": user_data["role"],
                },
            )
            user_id = result.scalar_one()
            logger.info("  DB: ユーザー作成 %s (id=%d)", user_data["email"], user_id)

        firebase_auth.set_custom_user_claims(firebase_uid, {"tenant_id": tenant_id})
        logger.info("  Firebase: tenant_id=%d クレーム設定", tenant_id)

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


def write_passwords_csv(rows: list[PasswordRow]) -> Path:
    """生成パスワードを CSV に書き出し、出力先パスを返す。"""
    out_dir = Path("/app/scripts/output")
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"passwords_{stamp}.csv"
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["tenant_code", "username", "email", "crm_role", "password"])
        w.writerows(rows)
    try:
        os.chmod(out_path, 0o600)
    except OSError:
        pass
    return out_path


async def process_tenant(engine, tenant_code: str, tenant_name: str, users: list[dict]) -> list[PasswordRow]:
    from app.auth.utils import generate_password

    logger.info("\n--- テナント: %s ---", tenant_name)
    tenant_id = await ensure_tenant(engine, tenant_code, tenant_name)
    await apply_tenant_schema(engine, tenant_id)

    results: list[PasswordRow] = []
    for u in users:
        password = generate_password()
        firebase_uid = create_or_update_firebase_user(u["email"], u["username"], password)
        await register_user(engine, tenant_id, firebase_uid, u, password)
        results.append((tenant_code, u["username"], u["email"], u["crm_role"], password))
    return results


async def main():
    url = DATABASE_URL
    if url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://"):]

    engine = create_async_engine(url, echo=False)

    try:
        logger.info("=== テストユーザーセットアップ開始 ===")

        rows: list[PasswordRow] = []
        rows += await process_tenant(engine, TENANT_1_CODE, TENANT_1_NAME, TENANT_1_USERS)
        rows += await process_tenant(engine, TENANT_2_CODE, TENANT_2_NAME, TENANT_2_USERS)

        out_path = write_passwords_csv(rows)

        logger.info("\n=== セットアップ完了 ===")
        logger.info("CSV出力: %s", out_path)
        logger.info("Mac側へ取り出すには（VPSで実行）:")
        logger.info("  docker compose cp backend:%s ~/passwords.csv && chmod 600 ~/passwords.csv", out_path)
        logger.info("配布後は VPS 内のCSVを削除してください: docker compose exec backend rm %s", out_path)

    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
