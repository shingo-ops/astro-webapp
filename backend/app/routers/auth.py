from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache import blacklist_token
from app.database import get_db
from app.models import User, Tenant
from app.auth.utils import hash_password, set_tenant_claim
from app.auth.schemas import UserRegister, UserResponse
from app.auth.dependencies import get_current_user
from app.services.audit import record_audit_log

router = APIRouter()
security = HTTPBearer()


@router.post("/register", response_model=UserResponse, status_code=201)
async def register_user(
    data: UserRegister,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    ユーザー登録API（管理者のみ実行可能）。

    フロー:
      ① 管理者権限を確認
      ② tenant_codeからテナントを検索
      ③ 同じメールアドレスのユーザーがいないか確認（いれば409）
      ④ パスワードをbcryptでハッシュ化（平文は保存しない）
      ⑤ usersテーブルにユーザーを作成

    注意:
      - このAPIで登録した後、ユーザーはFirebase Authenticationにも
        アカウントを作成する必要がある（フロントエンド側で実施）
      - パスワードはDB側のバックアップ認証用（Firebase障害時のフォールバック）
    """
    # 管理者権限チェック
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="ユーザー登録は管理者のみ可能です",
        )

    # テナントの存在確認（エラーメッセージにテナントコードを含めない）
    result = await db.execute(
        select(Tenant).where(
            Tenant.tenant_code == data.tenant_code,
            Tenant.is_active == True,
        )
    )
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="テナントコードが無効です",
        )

    # メールアドレスの重複チェック
    result = await db.execute(
        select(User).where(User.email == data.email)
    )
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="このメールアドレスは既に登録されています",
        )

    # ユーザー作成（パスワードはbcryptハッシュ化して保存）
    user = User(
        tenant_id=tenant.id,
        username=data.username,
        email=data.email,
        password_hash=hash_password(data.password),
        full_name=data.full_name,
        role="user",
        is_active=True,
    )
    db.add(user)
    await db.flush()

    # 監査ログ記録（パスワード等の機密情報は記録しない）
    await record_audit_log(
        db=db,
        tenant_id=tenant.id,
        user_id=user.id,
        action="create",
        table_name="users",
        record_id=user.id,
        new_data={
            "email": user.email,
            "username": user.username,
            "role": user.role,
        },
    )

    # FirebaseカスタムクレームにテナントIDを埋め込み（同期APIをスレッドで実行）
    import asyncio
    try:
        await asyncio.to_thread(set_tenant_claim, data.firebase_uid, tenant.id)
    except Exception:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Firebase連携に失敗しました。再度お試しください",
        )

    await db.commit()
    await db.refresh(user)

    return user


@router.post("/logout", status_code=200)
async def logout(
    cred: HTTPAuthorizationCredentials = Depends(security),
):
    """
    ログアウトAPI。
    トークンをブラックリストに追加し、以降の利用を拒否する。
    Firebase IDトークンの残存有効期限（最大1時間）をTTLとする。
    """
    token = cred.credentials
    await blacklist_token(token, ttl=3600)
    return {"message": "ログアウトしました"}
