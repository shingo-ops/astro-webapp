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
