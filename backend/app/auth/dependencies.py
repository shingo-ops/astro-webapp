import os

import firebase_admin
from firebase_admin import auth as firebase_auth, credentials
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User, Tenant

security = HTTPBearer()

# MFA強制フラグ（本番では必ずTrue）
MFA_REQUIRED = os.getenv("MFA_REQUIRED", "true").lower() == "true"

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
      ① クライアントがAuthorizationヘッダーにFirebase IDトークンを付与
      ② このDependencyがトークンを検証（Googleの公開鍵で署名確認）
      ③ トークンからemailを取得し、DBのusersテーブルから該当ユーザーを検索
      ④ ユーザーが見つかればそのオブジェクトを返す
    """
    _init_firebase()

    token = cred.credentials
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
    """
    tenant_id = user.tenant_id

    # テナントの存在・有効性を確認
    result = await db.execute(
        select(Tenant).where(Tenant.id == tenant_id, Tenant.is_active == True)
    )
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="テナントが無効です",
        )

    # search_pathをテナントスキーマに切り替え
    schema_name = f"tenant_{tenant_id:03d}"
    await db.execute(text(f"SET search_path = {schema_name}, public"))

    # RLS用のapp.tenant_idも設定
    await db.execute(text(f"SET app.tenant_id = '{tenant_id}'"))

    return tenant_id
