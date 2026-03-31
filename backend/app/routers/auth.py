from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User, Tenant
from app.auth.utils import hash_password
from app.auth.schemas import UserRegister, UserResponse
from app.services.audit import record_audit_log

router = APIRouter()


@router.post("/register", response_model=UserResponse, status_code=201)
async def register_user(
    data: UserRegister,
    db: AsyncSession = Depends(get_db),
):
    """
    ユーザー登録API。

    フロー:
      ① tenant_codeからテナントを検索（存在しなければ404）
      ② 同じメールアドレスのユーザーがいないか確認（いれば409）
      ③ パスワードをbcryptでハッシュ化（平文は保存しない）
      ④ usersテーブルにユーザーを作成

    注意:
      - このAPIで登録した後、ユーザーはFirebase Authenticationにも
        アカウントを作成する必要がある（フロントエンド側で実施）
      - パスワードはDB側のバックアップ認証用（Firebase障害時のフォールバック）
    """
    # テナントの存在確認
    result = await db.execute(
        select(Tenant).where(
            Tenant.tenant_code == data.tenant_code,
            Tenant.is_active == True,
        )
    )
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"テナント '{data.tenant_code}' が見つかりません",
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

    await db.commit()
    await db.refresh(user)

    return user
