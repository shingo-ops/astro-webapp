from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.database import get_db
from app.models import Tenant, User
from app.services.tenant import create_tenant_schema

router = APIRouter()


async def require_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """管理者ロールを要求するDependency。"""
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="この操作には管理者権限が必要です",
        )
    return current_user


class TenantCreate(BaseModel):
    """テナント登録リクエスト"""
    tenant_name: str = Field(min_length=1, max_length=255)
    tenant_code: str = Field(min_length=1, max_length=50, pattern=r"^[a-z0-9\-]+$")


class TenantResponse(BaseModel):
    """テナント情報レスポンス"""
    id: int
    tenant_name: str
    tenant_code: str
    is_active: bool
    schema_name: str

    model_config = {"from_attributes": True}


@router.post("/tenants", response_model=TenantResponse, status_code=201)
async def register_tenant(
    data: TenantCreate,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    """
    テナント（契約企業）を登録し、専用スキーマを自動生成する。
    管理者権限（role="admin"）が必要。
    """
    # tenant_codeの重複チェック
    result = await db.execute(
        select(Tenant).where(Tenant.tenant_code == data.tenant_code)
    )
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"テナントコード '{data.tenant_code}' は既に使用されています",
        )

    # テナント作成
    tenant = Tenant(
        tenant_name=data.tenant_name,
        tenant_code=data.tenant_code,
        is_active=True,
    )
    db.add(tenant)
    await db.flush()  # IDを確定させる（commit前にIDが必要）

    # 専用スキーマを自動生成（テーブル + RLSポリシー込み）
    schema_name = await create_tenant_schema(db, tenant.id)

    return TenantResponse(
        id=tenant.id,
        tenant_name=tenant.tenant_name,
        tenant_code=tenant.tenant_code,
        is_active=tenant.is_active,
        schema_name=schema_name,
    )
