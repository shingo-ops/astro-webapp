"""TenantProfile router (Sprint 8 / F8)

各テナント admin が PO PDF / メールの差出人情報 (会社名・住所・印鑑 URL 等) を
CRUD するエンドポイント。

設計:
  - 1 テナント 1 行運用 (migration 069 で既定行を 1 行 seed)
  - `GET /api/v1/admin/tenant-profile` → 取得 (見るだけなら view 権限)
  - `PUT /api/v1/admin/tenant-profile` → 全フィールド更新 (edit 権限)
  - require_permission("tenant.profile.view" / "tenant.profile.edit")
    permissions は migration 069 で seed 済

関連:
  .claude-pipeline/spec.md F8 / AC8.7
  migrations/069_create_tenant_profile.sql
  backend/app/services/po_renderer.py
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import (
    get_current_tenant,
    get_current_user,
    require_permission,
)
from app.database import get_db
from app.models import User
from app.schemas.tenant_profile import TenantProfileResponse, TenantProfileUpdate
from app.services.audit import record_audit_log

router = APIRouter()


@router.get(
    "/admin/tenant-profile",
    response_model=TenantProfileResponse,
    dependencies=[Depends(require_permission("tenant.profile.view"))],
)
async def get_tenant_profile(
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),  # noqa: ARG001
    current_user: User = Depends(get_current_user),  # noqa: ARG001
):
    """テナント発行者情報を取得 (1 行)。

    migration 069 で既定の空行を seed しているため通常 404 にはならない。
    """
    row = (await db.execute(
        text("""
            SELECT id, company_name, company_name_en, address, phone, email,
                   website, seal_image_url, default_language,
                   created_at, updated_at
            FROM tenant_profile
            ORDER BY id LIMIT 1
        """),
    )).mappings().first()

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="tenant_profile が初期化されていません",
        )
    return TenantProfileResponse(**dict(row))


@router.put(
    "/admin/tenant-profile",
    response_model=TenantProfileResponse,
    dependencies=[Depends(require_permission("tenant.profile.edit"))],
)
async def update_tenant_profile(
    data: TenantProfileUpdate,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """テナント発行者情報を更新 (PATCH 相当だが PUT で全フィールド指定可)。"""
    # 既存行を確認
    existing = (await db.execute(
        text("SELECT id FROM tenant_profile ORDER BY id LIMIT 1"),
    )).mappings().first()
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="tenant_profile が初期化されていません (migration 069 適用要)",
        )

    # 更新フィールドを動的に組み立て
    payload = data.model_dump(exclude_unset=True)
    if not payload:
        # 何も指定なし → 現状返却
        row = (await db.execute(
            text("""
                SELECT id, company_name, company_name_en, address, phone, email,
                       website, seal_image_url, default_language,
                       created_at, updated_at
                FROM tenant_profile WHERE id = :id
            """),
            {"id": existing["id"]},
        )).mappings().first()
        return TenantProfileResponse(**dict(row))

    set_clauses = []
    params: dict = {"id": existing["id"]}
    for k, v in payload.items():
        set_clauses.append(f"{k} = :{k}")
        params[k] = v
    set_sql = ", ".join(set_clauses)

    await db.execute(
        text(f"UPDATE tenant_profile SET {set_sql} WHERE id = :id"),
        params,
    )

    await record_audit_log(
        db=db, tenant_id=tenant_id, user_id=current_user.id,
        action="update", table_name="tenant_profile",
        record_id=existing["id"], new_data=payload,
    )
    await db.commit()

    row = (await db.execute(
        text("""
            SELECT id, company_name, company_name_en, address, phone, email,
                   website, seal_image_url, default_language,
                   created_at, updated_at
            FROM tenant_profile WHERE id = :id
        """),
        {"id": existing["id"]},
    )).mappings().first()
    return TenantProfileResponse(**dict(row))
