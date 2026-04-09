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
    get_cached_jwt,
    get_cached_tenant,
    is_token_blacklisted,
)
from app.database import get_db
from app.models import User, Tenant

security = HTTPBearer()

# Firebase Admin SDK の初期化（アプリ起動時に1回だけ実行）
_firebase_app = None


def _init_firebase():
    global _firebase_app
    if _firebase_app is not None:
        return
    cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if cred_path and os.path.exists(cred_path):
        cred = credentials.Certificate(cred_path)
        _firebase_app = firebase_admin.initialize_app(cred)
    else:
        # 環境変数 or デフォルト認証情報を使用
        _firebase_app = firebase_admin.initialize_app()


async def get_current_user(
    cred: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Firebase IDトークンを検証し、対応するDBユーザーを返す。
    全認証付きエンドポイントの共通Dependency。

    フロー:
      ① ブラックリスト確認（ログアウト済みトークンを拒否）
      ② Redisキャッシュからユーザー情報を取得（キャッシュヒット時はDB不要）
      ③ キャッシュミス時: Firebase検証 → DB検索 → 結果をキャッシュ
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
    tenant_id = user.tenant_id

    # Redisキャッシュからテナント情報を取得
    cached = await get_cached_tenant(tenant_id)
    if cached:
        if not cached["is_active"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="テナントが無効です",
            )
    else:
        # キャッシュミス: DB確認してキャッシュに保存
        result = await db.execute(
            select(Tenant).where(Tenant.id == tenant_id)
        )
        tenant = result.scalar_one_or_none()
        if not tenant or not tenant.is_active:
            await cache_tenant(tenant_id, False)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="テナントが無効です",
            )
        await cache_tenant(tenant_id, True)

    # search_pathをテナントスキーマに切り替え
    schema_name = f"tenant_{tenant_id:03d}"
    await db.execute(text(f"SET search_path = {schema_name}, public"))

    # RLS用のapp.tenant_idも設定
    await db.execute(text(f"SET app.tenant_id = '{tenant_id}'"))

    return tenant_id
