#!/usr/bin/env python3
"""Meta App Review 撮影用テナント (tenant-review) セットアップスクリプト。

ADR-028: Meta App Review 撮影用テナント分離の実装。

実行方法（VPS側、backendコンテナ内）:
  docker compose exec -e ALLOW_REVIEW_TENANT_SETUP=1 backend \\
      python /app/scripts/setup_review_tenant.py

前提:
  - firebase-credentials.json がコンテナ内 /app に存在すること
  - DATABASE_URL 環境変数が設定されていること
  - ALLOW_REVIEW_TENANT_SETUP=1 を環境変数で渡すこと（誤実行防止のガード）

冪等性:
  - 複数回実行しても安全。既存テナント・ユーザー・顧客データを重複作成しない。

注意:
  - review@salesanchor.jp が既存テナントに紐付いている場合、新テナントに付け替えます。
    既存テナント（tenant_004 等）のスキーマデータは一切変更しません（AC-3）。
  - Meta OAuth 再接続は OAuth フロー経由で別途実施してください（自動化不可）。
  - パスワードは /tmp/review_tenant_setup_*.txt に出力します。
    Mac 側への取り出し: docker compose exec -T backend cat /tmp/review_tenant_setup_*.txt

変更履歴:
  2026-05-14: ADR-028 初版作成
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parent.parent
if str(_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_ROOT))

import firebase_admin
from firebase_admin import auth as firebase_auth, credentials, exceptions as fb_exceptions
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 定数
# ---------------------------------------------------------------------------

TENANT_CODE = "tenant-review"
TENANT_NAME = "Sales Anchor App Review"
REVIEW_EMAIL = "review@salesanchor.jp"
REVIEW_DISPLAY_NAME = "App Review"

# Demo Customer × 7（実顧客データは一切含まない）
DEMO_CUSTOMERS = [
    {"customer_code": "DEMO-001", "company_name": "Demo Trading Co. Ltd."},
    {"customer_code": "DEMO-002", "company_name": "Demo Import Export Inc."},
    {"customer_code": "DEMO-003", "company_name": "Demo EC Solutions Corp."},
    {"customer_code": "DEMO-004", "company_name": "Demo Boutique Japan"},
    {"customer_code": "DEMO-005", "company_name": "Demo Wholesale Group"},
    {"customer_code": "DEMO-006", "company_name": "Demo Retail Partners"},
    {"customer_code": "DEMO-007", "company_name": "Demo Global Commerce"},
]


# ---------------------------------------------------------------------------
# ガードチェック
# ---------------------------------------------------------------------------

def _check_guard() -> None:
    if os.getenv("ALLOW_REVIEW_TENANT_SETUP") != "1":
        logger.error(
            "誤実行防止: 環境変数 ALLOW_REVIEW_TENANT_SETUP=1 を付けて実行してください。\n"
            "  例: docker compose exec -e ALLOW_REVIEW_TENANT_SETUP=1 backend"
            " python /app/scripts/setup_review_tenant.py"
        )
        sys.exit(1)


# ---------------------------------------------------------------------------
# Firebase
# ---------------------------------------------------------------------------

def _init_firebase() -> None:
    if firebase_admin._apps:
        return
    cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "/app/firebase-credentials.json")
    if os.path.exists(cred_path):
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)
    else:
        firebase_admin.initialize_app()


def _firebase_get_uid(email: str) -> str | None:
    try:
        return firebase_auth.get_user_by_email(email).uid
    except fb_exceptions.NotFoundError:
        return None


def _firebase_create_user(email: str, password: str, display_name: str) -> str:
    user = firebase_auth.create_user(
        email=email,
        password=password,
        display_name=display_name,
        email_verified=False,
    )
    logger.info("Firebase: 新規作成 %s (uid=%s)", email, user.uid)
    return user.uid


def _firebase_update_password(uid: str, password: str) -> None:
    firebase_auth.update_user(uid, password=password)
    logger.info("Firebase: uid=%s のパスワードを更新", uid)


# ---------------------------------------------------------------------------
# DB: テナント
# ---------------------------------------------------------------------------

async def _ensure_tenant(engine) -> int:
    """tenant-review テナントを作成または取得し、ID を返す（冪等）。"""
    async with engine.begin() as conn:
        row = (await conn.execute(
            text("SELECT id FROM public.tenants WHERE tenant_code = :code"),
            {"code": TENANT_CODE},
        )).first()
        if row:
            logger.info("テナント '%s' 既存 (id=%d)", TENANT_CODE, row[0])
            return int(row[0])

        row = (await conn.execute(
            text("""
                INSERT INTO public.tenants (tenant_name, tenant_code, is_active)
                VALUES (:name, :code, TRUE)
                RETURNING id
            """),
            {"name": TENANT_NAME, "code": TENANT_CODE},
        )).first()
        tenant_id = int(row[0])
        logger.info("テナント '%s' 新規作成 (id=%d)", TENANT_CODE, tenant_id)

        schema_name = f"tenant_{tenant_id:03d}"
        await conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema_name}"))
        logger.info("  スキーマ %s 作成", schema_name)

    return tenant_id


async def _apply_tenant_schema(engine, tenant_id: int) -> None:
    """テナントスキーマにテーブル・RLS・システムロールを適用する（冪等）。"""
    from app.services.tenant import (
        _TENANT_TABLES_SQL,
        _RLS_ENABLE_SQL,
        _RLS_POLICY_SQL,
        seed_system_roles,
        _split_sql_preserving_do_blocks,
    )

    schema_name = f"tenant_{tenant_id:03d}"
    logger.info("スキーマ %s にテーブル・RLS・ロールを適用中...", schema_name)

    async with engine.begin() as conn:
        tables_sql = _TENANT_TABLES_SQL.format(
            schema=schema_name, schema_raw=schema_name, tenant_id=tenant_id
        )
        for stmt in _split_sql_preserving_do_blocks(tables_sql):
            stmt = stmt.strip()
            if stmt:
                await conn.execute(text(stmt))

        enable_sql = _RLS_ENABLE_SQL.format(schema=schema_name)
        for stmt in enable_sql.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                await conn.execute(text(stmt))

        policy_sql = _RLS_POLICY_SQL.format(schema=schema_name, schema_raw=schema_name)
        await conn.execute(text(policy_sql))

        await seed_system_roles(conn, tenant_id, schema_name)

    logger.info("  テーブル + RLS + ロールシード完了")


# ---------------------------------------------------------------------------
# DB: ユーザー
# ---------------------------------------------------------------------------

async def _resolve_role_id(conn, tenant_id: int, schema_name: str, role_name: str) -> int:
    await conn.execute(text(f"SET search_path = {schema_name}, public"))
    await conn.execute(text(f"SET app.tenant_id = '{tenant_id}'"))
    row = (await conn.execute(
        text("SELECT id FROM roles WHERE tenant_id = :tid AND name = :name"),
        {"tid": tenant_id, "name": role_name},
    )).first()
    if not row:
        raise RuntimeError(
            f"テナント {tenant_id} に CRM ロール '{role_name}' が存在しません。"
            " seed_system_roles が完了しているか確認してください。"
        )
    return int(row[0])


async def _create_staff_record(
    conn,
    *,
    tenant_id: int,
    user_id: int,
    email: str,
    display_name: str,
    role_id: int,
    firebase_uid: str,
) -> int:
    """per-tenant staff レコードを作成する（冪等: 既存なら skip）。"""
    existing = (await conn.execute(
        text("SELECT id FROM staff WHERE primary_email = :email"),
        {"email": email},
    )).first()
    if existing:
        staff_id = int(existing[0])
        logger.info("  staff は既存 (id=%d) のため作成 skip", staff_id)
        await conn.execute(
            text("INSERT INTO staff_ui_preferences (staff_id) VALUES (:sid) ON CONFLICT DO NOTHING"),
            {"sid": staff_id},
        )
        return staff_id

    parts = display_name.replace("　", " ").split(" ", 1)
    surname_jp = parts[0][:50] if parts else "Review"
    given_name_jp = parts[1][:50] if len(parts) >= 2 else "User"

    row = (await conn.execute(
        text("""
            INSERT INTO staff (
                tenant_id, user_id, staff_code,
                surname_jp, given_name_jp,
                primary_email, role_id, status, firebase_uid
            )
            VALUES (
                :tid, :uid, :code,
                :sjp, :gjp,
                :email, :rid, 'active', :fbuid
            )
            RETURNING id
        """),
        {
            "tid": tenant_id,
            "uid": user_id,
            "code": f"EMP-R-{uuid.uuid4().hex[:12]}",
            "sjp": surname_jp,
            "gjp": given_name_jp,
            "email": email,
            "rid": role_id,
            "fbuid": firebase_uid,
        },
    )).first()
    staff_id = int(row[0])
    await conn.execute(
        text("UPDATE staff SET staff_code = :code WHERE id = :id"),
        {"code": f"EMP-{staff_id:05d}", "id": staff_id},
    )
    await conn.execute(
        text("INSERT INTO staff_ui_preferences (staff_id) VALUES (:sid) ON CONFLICT DO NOTHING"),
        {"sid": staff_id},
    )
    logger.info("  staff 作成 (id=%d, user_id=%d)", staff_id, user_id)
    return staff_id


async def _setup_user(engine, tenant_id: int, firebase_uid: str, password_hash: str) -> int:
    """public.users にユーザーを登録・付け替え、staff レコードを作成する。

    AC-3 適合: public.users.tenant_id の UPDATE は公開スキーマへの変更であり、
    既存業務テナント（tenant_004 等）のスキーマデータには一切手を加えない。
    既存テナントの staff レコードはそのまま保持する。
    """
    from app.auth.utils import hash_password as _hash  # noqa: F401 型確認用

    schema_name = f"tenant_{tenant_id:03d}"

    async with engine.begin() as conn:
        existing = (await conn.execute(
            text("SELECT id, tenant_id FROM public.users WHERE email = :email"),
            {"email": REVIEW_EMAIL},
        )).first()

        if existing:
            user_id, current_tenant_id = int(existing[0]), int(existing[1])
            if current_tenant_id != tenant_id:
                # AC-3: public.users.tenant_id の付け替えのみ。既存テナントスキーマは不変。
                await conn.execute(
                    text("""
                        UPDATE public.users
                        SET tenant_id = :new_tid,
                            password_hash = :hash,
                            is_active = TRUE
                        WHERE id = :uid
                    """),
                    {"new_tid": tenant_id, "hash": password_hash, "uid": user_id},
                )
                logger.info(
                    "  public.users: %s を tenant_id=%d → %d に付け替え (id=%d)",
                    REVIEW_EMAIL, current_tenant_id, tenant_id, user_id,
                )
            else:
                await conn.execute(
                    text("UPDATE public.users SET password_hash = :hash, is_active = TRUE WHERE id = :uid"),
                    {"hash": password_hash, "uid": user_id},
                )
                logger.info("  public.users: 既存ユーザー (id=%d) パスワード更新", user_id)
        else:
            row = (await conn.execute(
                text("""
                    INSERT INTO public.users (
                        tenant_id, username, email, password_hash, full_name, role, is_active
                    )
                    VALUES (:tid, :username, :email, :hash, :fullname, 'user', TRUE)
                    RETURNING id
                """),
                {
                    "tid": tenant_id,
                    "username": REVIEW_DISPLAY_NAME,
                    "email": REVIEW_EMAIL,
                    "hash": password_hash,
                    "fullname": REVIEW_DISPLAY_NAME,
                },
            )).first()
            user_id = int(row[0])
            logger.info("  public.users: 新規作成 %s (id=%d)", REVIEW_EMAIL, user_id)

        # Firebase カスタムクレームを新テナントに更新
        firebase_auth.set_custom_user_claims(firebase_uid, {"tenant_id": tenant_id})
        logger.info("  Firebase: tenant_id=%d クレーム設定完了", tenant_id)

        # 新テナントのロール取得 + staff 作成
        role_id = await _resolve_role_id(conn, tenant_id, schema_name, "オーナー")
        await conn.execute(
            text("INSERT INTO user_roles (user_id, role_id) VALUES (:uid, :rid) ON CONFLICT DO NOTHING"),
            {"uid": user_id, "rid": role_id},
        )
        logger.info("  user_roles: オーナーロール付与")

        await _create_staff_record(
            conn,
            tenant_id=tenant_id,
            user_id=user_id,
            email=REVIEW_EMAIL,
            display_name=REVIEW_DISPLAY_NAME,
            role_id=role_id,
            firebase_uid=firebase_uid,
        )

    return user_id


# ---------------------------------------------------------------------------
# DB: Demo Customer シード
# ---------------------------------------------------------------------------

async def _seed_demo_customers(engine, tenant_id: int) -> int:
    """Demo Customer × 7 をシードする（冪等: 既存 customer_code はスキップ）。

    実顧客データは一切含まない。AC-2 適合。
    """
    schema_name = f"tenant_{tenant_id:03d}"
    created = 0

    async with engine.begin() as conn:
        await conn.execute(text(f"SET search_path = {schema_name}, public"))
        await conn.execute(text(f"SET app.tenant_id = '{tenant_id}'"))

        for c in DEMO_CUSTOMERS:
            existing = (await conn.execute(
                text("SELECT id FROM customers WHERE tenant_id = :tid AND customer_code = :code"),
                {"tid": tenant_id, "code": c["customer_code"]},
            )).first()
            if existing:
                logger.info("  顧客 %s は既存 (id=%d) のため skip", c["customer_code"], existing[0])
                continue

            await conn.execute(
                text("""
                    INSERT INTO customers (tenant_id, customer_code, company_name, status)
                    VALUES (:tid, :code, :name, 'active')
                """),
                {"tid": tenant_id, "code": c["customer_code"], "name": c["company_name"]},
            )
            logger.info("  顧客作成: %s / %s", c["customer_code"], c["company_name"])
            created += 1

    logger.info("Demo Customer: %d 件作成（既存 skip 含む合計 %d 件）", created, len(DEMO_CUSTOMERS))
    return created


# ---------------------------------------------------------------------------
# 結果出力
# ---------------------------------------------------------------------------

def _write_result_file(tenant_id: int, password: str) -> Path:
    schema_name = f"tenant_{tenant_id:03d}"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = Path("/tmp") / f"review_tenant_setup_{stamp}.txt"
    content = f"""=== ADR-028: tenant-review セットアップ結果 ===

テナント情報:
  tenant_code : {TENANT_CODE}
  tenant_name : {TENANT_NAME}
  tenant_id   : {tenant_id}
  schema_name : {schema_name}

ログイン情報:
  email    : {REVIEW_EMAIL}
  password : {password}

Demo Customer 数: {len(DEMO_CUSTOMERS)} 件

次のステップ（手動実施）:
  1. ブラウザで https://app.salesanchor.jp/ にアクセス
  2. 上記 email / password でログイン
  3. Dashboard に Demo Customer のみ表示されることを確認（AC-1, AC-2）
  4. Meta Inbox → 接続 から OAuth 再接続を実施（AC-4）
     - HIGH LIFE JPN Test Page と treasureislandjapan を紐付ける
  5. Messenger / Instagram で実際にメッセージ送受信を確認（AC-4, AC-5）
"""
    out_path.write_text(content, encoding="utf-8")
    try:
        os.chmod(out_path, 0o600)
    except OSError:
        pass
    return out_path


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------

async def main() -> None:
    from app.auth.utils import generate_password, hash_password

    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        logger.error("DATABASE_URL が未設定です。")
        sys.exit(1)
    if db_url.startswith("postgresql://"):
        db_url = "postgresql+asyncpg://" + db_url[len("postgresql://"):]

    engine = create_async_engine(db_url, echo=False)

    try:
        logger.info("=== ADR-028: tenant-review セットアップ開始 ===")

        # 1. テナント作成（冪等）
        tenant_id = await _ensure_tenant(engine)

        # 2. スキーマ適用（冪等）
        await _apply_tenant_schema(engine, tenant_id)

        # 3. Firebase ユーザー準備
        password = generate_password()
        password_hash = hash_password(password)

        _init_firebase()
        existing_uid = _firebase_get_uid(REVIEW_EMAIL)
        if existing_uid:
            _firebase_update_password(existing_uid, password)
            firebase_uid = existing_uid
        else:
            firebase_uid = _firebase_create_user(REVIEW_EMAIL, password, REVIEW_DISPLAY_NAME)

        # 4. DB ユーザー登録・テナント付け替え（冪等）
        await _setup_user(engine, tenant_id, firebase_uid, password_hash)

        # 5. Demo Customer × 7 シード（冪等）
        await _seed_demo_customers(engine, tenant_id)

        # 6. 結果ファイル出力
        out_path = _write_result_file(tenant_id, password)

        logger.info("\n=== セットアップ完了 ===")
        logger.info("結果ファイル: %s", out_path)
        logger.info("Mac 側への取り出し（VPS で実行）:")
        logger.info("  docker compose exec -T backend cat %s", out_path)

    finally:
        await engine.dispose()


if __name__ == "__main__":
    _check_guard()
    asyncio.run(main())
