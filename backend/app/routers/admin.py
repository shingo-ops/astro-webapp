from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Tenant, User
from app.services.tenant import create_tenant_schema
from app.services.audit import record_audit_log
from app.auth.dependencies import get_current_user

router = APIRouter()


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
    current_user: User = Depends(get_current_user),
):
    """
    テナント（契約企業）を登録し、専用スキーマを自動生成する。

    フロー:
      ① tenant_codeの重複チェック
      ② public.tenants にテナント情報を保存
      ③ tenant_{id:03d} スキーマを自動作成
      ④ スキーマ内に業務テーブル（customers, deals, orders, audit_logs）を作成
      ⑤ Row Level Security（RLS）ポリシーを自動適用

    注意:
      - tenant_codeは英小文字・数字・ハイフンのみ（例: "demo-a", "company-123"）
      - このAPIは管理者のみが呼び出せるようにする（将来的にroleチェックを追加）
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

    # 監査ログ記録
    await record_audit_log(
        db=db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="create",
        table_name="tenants",
        record_id=tenant.id,
        new_data={
            "tenant_name": tenant.tenant_name,
            "tenant_code": tenant.tenant_code,
            "schema_name": schema_name,
        },
    )

    return TenantResponse(
        id=tenant.id,
        tenant_name=tenant.tenant_name,
        tenant_code=tenant.tenant_code,
        is_active=tenant.is_active,
        schema_name=schema_name,
    )
