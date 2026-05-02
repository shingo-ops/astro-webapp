#!/usr/bin/env python3
"""単発テストユーザー作成スクリプト（既存ユーザー保護版）。

`setup_test_users.py` は TENANT_1 (highlife-jpn 本番) を含む全ユーザーを seed する
ため誤実行で本番パスワードを破壊する危険がある。本スクリプトは以下を保証する:

  - **新規ユーザーのみ作成**（同 email の既存ユーザーがあれば中断）
  - **環境変数で設定を渡す**（CLI 引数のシェルヒストリ漏洩を回避）
  - **本番テナント (highlife-jpn) を refuse**（テスト目的の単発作成に絞る）
  - **多重ガード**: ALLOW_TEST_USER_CREATE=1 + テナントコード allow list

実行方法（VPS 側、しんごさん作業）:

  docker compose exec \\
    -e ALLOW_TEST_USER_CREATE=1 \\
    -e TEST_EMAIL=claude-tester@salesanchor.jp \\
    -e TEST_PASSWORD='強力なランダム文字列' \\
    -e TEST_DISPLAY_NAME='Claude Tester' \\
    -e TEST_TENANT_CODE=test-corp \\
    -e TEST_CRM_ROLE=オーナー \\
    backend python /app/scripts/setup_single_test_user.py

オプション環境変数:

  ALLOW_OVERWRITE_PASSWORD=1
    既存ユーザーが見つかった場合にパスワードを上書きする。デフォルトは中断。

削除方法:

  docker compose exec \\
    -e ALLOW_TEST_USER_CREATE=1 \\
    -e DELETE_MODE=1 \\
    -e TEST_EMAIL=claude-tester@salesanchor.jp \\
    backend python /app/scripts/setup_single_test_user.py

前提:
  - firebase-credentials.json がコンテナ内 /app に存在
  - DATABASE_URL 環境変数が設定済み
  - 対象テナントが既に存在する（事前に作成しておくこと）
  - 対象テナントスキーマに roles テーブルが存在し、TEST_CRM_ROLE で指定したロールが seed 済

変更履歴:
  2026-05-02: 初版（オプション B、Claude post-login スモークテスト用）
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
from firebase_admin import auth as firebase_auth, credentials, exceptions as fb_exceptions
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ガードチェック
# ---------------------------------------------------------------------------

# 本番テナントへの作成は禁止（取り違え事故防止）
PRODUCTION_TENANT_CODES = frozenset({"highlife-jpn"})


def _require_env(name: str) -> str:
    val = os.getenv(name)
    if not val:
        logger.error("環境変数 %s が未設定です。", name)
        sys.exit(1)
    return val


def _check_guards() -> None:
    if os.getenv("ALLOW_TEST_USER_CREATE") != "1":
        logger.error(
            "誤実行防止: 環境変数 ALLOW_TEST_USER_CREATE=1 を付けて実行してください。"
        )
        sys.exit(1)


# ---------------------------------------------------------------------------
# Firebase
# ---------------------------------------------------------------------------


def _init_firebase() -> None:
    cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "/app/firebase-credentials.json")
    if firebase_admin._apps:
        return
    if os.path.exists(cred_path):
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)
    else:
        firebase_admin.initialize_app()


def _firebase_get_existing_uid(email: str) -> str | None:
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
    logger.info("Firebase: 既存ユーザー uid=%s のパスワード上書き", uid)


def _firebase_delete_user(uid: str) -> None:
    firebase_auth.delete_user(uid)
    logger.info("Firebase: ユーザー uid=%s 削除", uid)


# ---------------------------------------------------------------------------
# DB
# ---------------------------------------------------------------------------


async def _resolve_tenant_id(engine, tenant_code: str) -> int:
    if tenant_code in PRODUCTION_TENANT_CODES:
        logger.error(
            "本番テナント '%s' へのテストユーザー作成は禁止されています。"
            " 別のテナントコード（test-corp / test-tenant-2 等）を指定してください。",
            tenant_code,
        )
        sys.exit(1)
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT id FROM public.tenants WHERE tenant_code = :code AND is_active = TRUE"),
            {"code": tenant_code},
        )
        row = result.first()
        if not row:
            logger.error(
                "テナント '%s' が public.tenants に存在しないか is_active=FALSE です。"
                " 事前に setup_test_users.py 等でテナントを作成してから本スクリプトを実行してください。",
                tenant_code,
            )
            sys.exit(1)
        return int(row[0])


async def _resolve_role_id(conn, tenant_id: int, schema_name: str, role_name: str) -> int | None:
    await conn.execute(text(f"SET search_path = {schema_name}, public"))
    await conn.execute(text(f"SET app.tenant_id = '{tenant_id}'"))
    role_result = await conn.execute(
        text("SELECT id FROM roles WHERE tenant_id = :tid AND name = :name"),
        {"tid": tenant_id, "name": role_name},
    )
    row = role_result.first()
    return int(row[0]) if row else None


async def _user_exists(conn, email: str) -> tuple[int, int] | None:
    result = await conn.execute(
        text("SELECT id, tenant_id FROM public.users WHERE email = :email"),
        {"email": email},
    )
    row = result.first()
    if row:
        return int(row[0]), int(row[1])
    return None


async def _create_user_record(
    conn,
    *,
    tenant_id: int,
    email: str,
    display_name: str,
    password_hash: str,
) -> int:
    result = await conn.execute(
        text("""
            INSERT INTO public.users (
                tenant_id, username, email, password_hash, full_name, role, is_active
            )
            VALUES (:tid, :username, :email, :hash, :fullname, :role, TRUE)
            RETURNING id
        """),
        {
            "tid": tenant_id,
            "username": display_name,
            "email": email,
            "hash": password_hash,
            "fullname": display_name,
            "role": "user",
        },
    )
    user_id = int(result.scalar_one())
    logger.info("DB: public.users INSERT 完了 (id=%d)", user_id)
    return user_id


async def _assign_role(conn, user_id: int, role_id: int) -> None:
    await conn.execute(
        text(
            "INSERT INTO user_roles (user_id, role_id) VALUES (:uid, :rid) "
            "ON CONFLICT DO NOTHING"
        ),
        {"uid": user_id, "rid": role_id},
    )
    logger.info("DB: user_roles 付与 (user_id=%d, role_id=%d)", user_id, role_id)


async def _delete_user_record(conn, user_id: int) -> None:
    await conn.execute(
        text("DELETE FROM user_roles WHERE user_id = :uid"),
        {"uid": user_id},
    )
    await conn.execute(
        text("DELETE FROM public.users WHERE id = :uid"),
        {"uid": user_id},
    )
    logger.info("DB: ユーザー削除完了 (id=%d)", user_id)


# ---------------------------------------------------------------------------
# モード分岐
# ---------------------------------------------------------------------------


async def _run_create() -> None:
    from app.auth.utils import hash_password

    email = _require_env("TEST_EMAIL")
    password = _require_env("TEST_PASSWORD")
    display_name = os.getenv("TEST_DISPLAY_NAME", "Test User")
    tenant_code = _require_env("TEST_TENANT_CODE")
    crm_role = os.getenv("TEST_CRM_ROLE", "オーナー")
    allow_overwrite = os.getenv("ALLOW_OVERWRITE_PASSWORD") == "1"

    if email.endswith("@treasureislandjp.com"):
        logger.error(
            "本番ドメイン @treasureislandjp.com への作成は禁止です。"
            " 取り違え事故防止のため別ドメインを指定してください。"
        )
        sys.exit(1)

    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        logger.error("DATABASE_URL が未設定です。")
        sys.exit(1)
    if db_url.startswith("postgresql://"):
        db_url = "postgresql+asyncpg://" + db_url[len("postgresql://"):]

    engine = create_async_engine(db_url, echo=False)
    try:
        logger.info("=== 単発テストユーザー作成開始 ===")
        logger.info("email=%s tenant=%s role=%s", email, tenant_code, crm_role)

        tenant_id = await _resolve_tenant_id(engine, tenant_code)
        schema_name = f"tenant_{tenant_id:03d}"

        async with engine.begin() as conn:
            existing = await _user_exists(conn, email)
            if existing:
                user_id, existing_tenant_id = existing
                if not allow_overwrite:
                    logger.error(
                        "email=%s の既存ユーザー (id=%d, tenant_id=%d) が見つかりました。"
                        " 上書きするには ALLOW_OVERWRITE_PASSWORD=1 を付けて再実行してください。",
                        email, user_id, existing_tenant_id,
                    )
                    sys.exit(1)
                logger.warning(
                    "ALLOW_OVERWRITE_PASSWORD=1 が指定されているため既存ユーザーのパスワードを上書きします (id=%d)",
                    user_id,
                )
                password_hash = hash_password(password)
                await conn.execute(
                    text(
                        "UPDATE public.users SET password_hash = :hash, is_active = TRUE "
                        "WHERE id = :id"
                    ),
                    {"hash": password_hash, "id": user_id},
                )
            else:
                # 新規作成パス
                role_id = await _resolve_role_id(conn, tenant_id, schema_name, crm_role)
                if role_id is None:
                    logger.error(
                        "tenant=%s に CRM ロール '%s' が存在しません。先に roles を seed してください。",
                        tenant_code, crm_role,
                    )
                    sys.exit(1)
                password_hash = hash_password(password)
                user_id = await _create_user_record(
                    conn,
                    tenant_id=tenant_id,
                    email=email,
                    display_name=display_name,
                    password_hash=password_hash,
                )
                await _assign_role(conn, user_id, role_id)

        # Firebase
        existing_uid = _firebase_get_existing_uid(email)
        if existing_uid:
            if allow_overwrite:
                _firebase_update_password(existing_uid, password)
            else:
                logger.error(
                    "Firebase 側に email=%s が既存です (uid=%s)。"
                    " 上書きするには ALLOW_OVERWRITE_PASSWORD=1 を付けて再実行してください。",
                    email, existing_uid,
                )
                sys.exit(1)
            uid = existing_uid
        else:
            uid = _firebase_create_user(email, password, display_name)

        # tenant_id クレーム設定
        firebase_auth.set_custom_user_claims(uid, {"tenant_id": tenant_id})
        logger.info("Firebase: tenant_id=%d クレーム設定完了 (uid=%s)", tenant_id, uid)

        logger.info("=== 完了 ===")
        logger.info("email   : %s", email)
        logger.info("tenant  : %s (id=%d)", tenant_code, tenant_id)
        logger.info("role    : %s", crm_role)
        logger.info("uid     : %s", uid)
        logger.info("これで Sales Anchor のログイン画面から email + password でログインできます。")
    finally:
        await engine.dispose()


async def _run_delete() -> None:
    email = _require_env("TEST_EMAIL")

    if email.endswith("@treasureislandjp.com"):
        logger.error("本番ドメインのユーザー削除は本スクリプトでは実行できません。")
        sys.exit(1)

    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        logger.error("DATABASE_URL が未設定です。")
        sys.exit(1)
    if db_url.startswith("postgresql://"):
        db_url = "postgresql+asyncpg://" + db_url[len("postgresql://"):]

    engine = create_async_engine(db_url, echo=False)
    try:
        logger.info("=== 単発テストユーザー削除開始 (email=%s) ===", email)

        async with engine.begin() as conn:
            existing = await _user_exists(conn, email)
            if existing:
                user_id, _tid = existing
                await _delete_user_record(conn, user_id)
            else:
                logger.info("DB に該当ユーザーなし、スキップ")

        existing_uid = _firebase_get_existing_uid(email)
        if existing_uid:
            _firebase_delete_user(existing_uid)
        else:
            logger.info("Firebase に該当ユーザーなし、スキップ")

        logger.info("=== 完了 ===")
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# entrypoint
# ---------------------------------------------------------------------------


async def main() -> None:
    _check_guards()
    _init_firebase()
    if os.getenv("DELETE_MODE") == "1":
        await _run_delete()
    else:
        await _run_create()


if __name__ == "__main__":
    asyncio.run(main())
