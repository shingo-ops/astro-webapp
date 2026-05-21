import os

import firebase_admin
from firebase_admin import auth as firebase_auth, credentials
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache import (
    cache_jwt_result,
    cache_tenant,
    cache_user_permissions,
    get_cached_jwt,
    get_cached_tenant,
    get_cached_user_permissions,
    is_token_blacklisted,
)
from app.database import get_db
from app.models import User, Tenant

security = HTTPBearer()

# MFA強制フラグ（本番では必ずTrue）
MFA_REQUIRED = os.getenv("MFA_REQUIRED", "true").lower() == "true"

# Firebase Admin SDK の初期化（スレッドセーフ）
import threading

_firebase_init_lock = threading.Lock()
_firebase_initialized = False


def _init_firebase():
    global _firebase_initialized
    if _firebase_initialized:
        return
    with _firebase_init_lock:
        if _firebase_initialized:
            return
        cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        if cred_path and os.path.exists(cred_path):
            cred = credentials.Certificate(cred_path)
            firebase_admin.initialize_app(cred)
        else:
            firebase_admin.initialize_app()
        _firebase_initialized = True


async def get_current_user(
    cred: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Firebase IDトークンを検証し、対応するDBユーザーを返す。
    全認証付きエンドポイントの共通Dependency。

    フロー:
      ① ブラックリスト確認（ログアウト済みトークンを拒否）
      ② Redisキャッシュからユーザー情報を取得（キャッシュヒット時はFirebase検証スキップ）
      ③ キャッシュミス時: Firebase検証 → MFAチェック → DB検索 → 結果をキャッシュ
    """
    _init_firebase()

    token = cred.credentials

    # ブラックリスト確認（ログアウト済みトークンを拒否）
    if await is_token_blacklisted(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="このトークンは無効化されています",
        )

    # Redisキャッシュからユーザー情報を取得
    cached = await get_cached_jwt(token)
    if cached:
        email = cached["email"]
        result = await db.execute(
            select(User).where(User.email == email, User.is_active == True)
        )
        user = result.scalar_one_or_none()
        if user:
            return user

    # キャッシュミス: Firebase検証
    try:
        decoded = firebase_auth.verify_id_token(token)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="無効な認証トークンです",
        )

    # MFA完了チェック: sign_in_second_factorクレームがないとMFA未完了
    if MFA_REQUIRED:
        firebase_claims = decoded.get("firebase", {})
        second_factor = firebase_claims.get("sign_in_second_factor")
        if not second_factor:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="MFA認証が必要です。認証アプリを設定してください",
            )

    email = decoded.get("email")
    if not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="トークンにメール情報がありません",
        )

    result = await db.execute(
        select(User).where(User.email == email, User.is_active == True)
    )
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="ユーザーが見つかりません",
        )

    # JWTカスタムクレームのtenant_idとDB上のtenant_idの一致を検証
    jwt_tenant_id = decoded.get("tenant_id")
    if jwt_tenant_id is not None and jwt_tenant_id != user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="テナント情報が不正です",
        )

    # 検証結果をキャッシュ
    await cache_jwt_result(token, {"email": email})

    return user


async def get_current_tenant(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> int:
    """
    認証済みユーザーのtenant_idを返す。
    JWTからではなくDB上のuser.tenant_idを使用する（IDOR脆弱性防止）。
    URLパラメータからtenant_idを受け取ることは絶対にしない。

    さらにDBセッションのsearch_pathをテナントスキーマに切り替える。
    テナントの有効性はRedisキャッシュで高速に確認する。
    """
    safe_id = int(user.tenant_id)

    # Redisキャッシュからテナント情報を取得
    cached = await get_cached_tenant(safe_id)
    if cached:
        if not cached["is_active"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="テナントが無効です",
            )
    else:
        # キャッシュミス: DB確認してキャッシュに保存
        result = await db.execute(
            select(Tenant).where(Tenant.id == safe_id)
        )
        tenant = result.scalar_one_or_none()
        if not tenant or not tenant.is_active:
            await cache_tenant(safe_id, False)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="テナントが無効です",
            )
        await cache_tenant(safe_id, True)

    # search_pathをテナントスキーマに切り替え（int()で型を強制しSQLi防止）
    schema_name = f"tenant_{safe_id:03d}"
    await db.execute(text(f"SET search_path = {schema_name}, public"))

    # RLS用のapp.tenant_idも設定
    await db.execute(text(f"SET app.tenant_id = '{safe_id}'"))

    return safe_id


def _dialect_supports_search_path(db: AsyncSession) -> bool:
    """PostgreSQL 系のみ SET search_path / SET app.tenant_id をサポートする。

    pytest は SQLite (aiosqlite) で実行されるため、SET 構文は syntax error になる。
    本判定で SQLite 系（および bind 不明）を検出して no-op に倒す。
    """
    bind = db.get_bind() if hasattr(db, "get_bind") else None
    if bind is None:
        bind = getattr(db, "bind", None)
    name = getattr(getattr(bind, "dialect", None), "name", "") or ""
    return name.startswith("postgresql")


async def reset_tenant_context(db: AsyncSession, tenant_id: int) -> None:
    """
    トランザクションコミット後にテナントコンテキスト（search_path + app.tenant_id）
    を再設定する。

    背景:
      SQLAlchemy の AsyncSession は `commit()` 後に新しいトランザクションを開始する際、
      プールから別のコネクションが払い出される可能性がある。その場合、元のコネクションで
      設定された session-level の search_path が新コネクションには反映されない。
      結果として commit 後のクエリが "relation ... does not exist" で失敗する。

    使用例:
        await db.commit()
        await reset_tenant_context(db, tenant_id)
        # ここからテナントスキーマのテーブルに対して再度クエリ可能

    SQLite は SET 構文を解釈できないため、本関数は dialect が postgresql 系の場合のみ
    SET を実行する（pytest 環境での no-op 化）。
    """
    if not _dialect_supports_search_path(db):
        return
    safe_id = int(tenant_id)
    schema_name = f"tenant_{safe_id:03d}"
    await db.execute(text(f"SET search_path = {schema_name}, public"))
    await db.execute(text(f"SET app.tenant_id = '{safe_id}'"))


async def get_current_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """管理者ロールを要求するDependency。adminルーターレベルで適用する。"""
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="この操作には管理者権限が必要です",
        )
    return current_user


async def require_super_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Jarvis 運用 admin（マーケットプレイス中央 admin）を要求する Dependency。

    背景:
      spec.md v1.1 F2 (Sprint 2) の二層権限構造:
        - 中央 admin (is_super_admin = true): /super-admin/masters 配下で
          public schema のマスタを編集（knowledge_rules / supplier_aliases /
          tcg_series_master / pokemon_dex / trainer_dex / suppliers /
          supplier_discord_routing）
        - テナント admin (role = 'admin'): 自テナント内の操作のみ
          （/admin/inventory-visibility 等）

    判定:
      public.users.is_super_admin = TRUE のユーザーのみ通過。
      テナント admin (role='admin') でも is_super_admin=false なら 403。

    使用例:
        @router.get("/super-admin/...",
                    dependencies=[Depends(require_super_admin)])
    """
    if not getattr(current_user, "is_super_admin", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="この操作にはJarvis運用admin（中央admin）権限が必要です",
        )
    return current_user


async def load_user_permissions(
    db: AsyncSession,
    tenant_id: int,
    user_id: int,
) -> set[str]:
    """
    ユーザーの有効パーミッションキー集合を取得する。
    キャッシュヒット時はDBクエリをスキップ。

    Discord方式: 複数ロールの権限を和集合で判定。
    """
    cached = await get_cached_user_permissions(tenant_id, user_id)
    if cached is not None:
        return cached

    # DBクエリ: user_roles → role_permissions → public.permissions をJOIN
    # search_pathは呼び出し元（get_current_tenant）で設定済みのため
    # user_roles/role_permissionsはテナントスキーマから参照される
    result = await db.execute(
        text("""
            SELECT DISTINCT p.key
            FROM user_roles ur
            JOIN role_permissions rp ON rp.role_id = ur.role_id
            JOIN public.permissions p ON p.id = rp.permission_id
            WHERE ur.user_id = :user_id
        """),
        {"user_id": user_id},
    )
    keys = {row[0] for row in result.fetchall()}

    # admin後方互換: User.role='admin'なら全権限を持つ扱い
    # （Phase 1移行期間中、ロール未割当ユーザーを救済）
    if not keys:
        # adminユーザーなら全権限取得、それ以外は最低限のビュー権限を付与
        user_result = await db.execute(
            text("SELECT role FROM public.users WHERE id = :uid"),
            {"uid": user_id},
        )
        row = user_result.fetchone()
        if row and row[0] == "admin":
            all_perms = await db.execute(text("SELECT key FROM public.permissions"))
            keys = {r[0] for r in all_perms.fetchall()}

    await cache_user_permissions(tenant_id, user_id, keys)
    return keys


def require_permission(*permission_keys: str):
    """
    指定された権限のいずれか1つを持つことを要求するDependencyファクトリ。
    Discord方式: ユーザーの全ロールの権限の和集合で判定。

    使用例:
        @router.post("/customers",
                     dependencies=[Depends(require_permission("customers.create"))])
    """
    required: set[str] = set(permission_keys)
    if not required:
        raise ValueError("require_permission には1つ以上のキーが必要です")

    async def checker(
        current_user: User = Depends(get_current_user),
        tenant_id: int = Depends(get_current_tenant),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        user_perms = await load_user_permissions(db, tenant_id, current_user.id)
        if required & user_perms:
            return current_user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"権限が不足しています: {', '.join(sorted(required))}",
        )

    return checker
