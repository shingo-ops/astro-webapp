"""TenantProfile router (Sprint 8 / F8)

各テナント admin が PO PDF / メールの差出人情報 (会社名・住所・印鑑 URL 等) を
CRUD するエンドポイント。

設計:
  - 1 テナント 1 行運用 (migration 069 で既定行を 1 行 seed)
  - `GET /api/v1/admin/tenant-profile` → 取得 (見るだけなら view 権限)
  - `PUT /api/v1/admin/tenant-profile` → 全フィールド更新 (edit 権限)
  - require_permission("tenant.profile.view" / "tenant.profile.edit")
    permissions は migration 069 で seed 済

raw SQL は dialect-aware な schema prefix を付ける (search_path に依存しない)。
  - 背景: Issue #563 で PUT 側の commit 直後再 SELECT が
    "relation \"tenant_profile\" does not exist" で失敗する事象が観測された。
    SQLAlchemy AsyncSession の commit 後は新コネクションが払い出されて
    session-level の search_path が失われる可能性があるため、
    raw text() を使う router は schema prefix を明示するのが安全。
  - PostgreSQL では `tenant_{id:03d}.tenant_profile`、
    SQLite (pytest) では schema 概念がないので prefix なしに倒す
    (`_dialect_supports_search_path` と同じ dialect 判定で分岐)。

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


def _is_postgresql(db: AsyncSession) -> bool:
    """db の dialect が PostgreSQL 系か判定する。

    pytest は SQLite (aiosqlite) で実行されるため、schema prefix を入れると
    "no such table: tenant_NNN.tenant_profile" で失敗する。本判定で
    SQLite 系を検出して prefix なしに倒す。
    """
    bind = db.get_bind() if hasattr(db, "get_bind") else None
    if bind is None:
        bind = getattr(db, "bind", None)
    name = getattr(getattr(bind, "dialect", None), "name", "") or ""
    return name.startswith("postgresql")


def _tenant_profile_table(db: AsyncSession, tenant_id: int) -> str:
    """raw SQL の FROM/UPDATE に埋め込むテーブル参照を返す。

    - PostgreSQL: `tenant_{id:03d}.tenant_profile` (schema prefix 明示)
    - SQLite (pytest): `tenant_profile` (schema 概念なし)
    """
    if _is_postgresql(db):
        safe_id = int(tenant_id)
        return f"tenant_{safe_id:03d}.tenant_profile"
    return "tenant_profile"


@router.get(
    "/admin/tenant-profile",
    response_model=TenantProfileResponse,
    dependencies=[Depends(require_permission("tenant.profile.view"))],
)
async def get_tenant_profile(
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),  # noqa: ARG001
):
    """テナント発行者情報を取得 (1 行)。

    migration 069 で既定の空行を seed しているため通常 404 にはならない。
    """
    table = _tenant_profile_table(db, tenant_id)
    row = (await db.execute(
        text(f"""
            SELECT id, company_name, company_name_en, address, phone, email,
                   website, seal_image_url, default_language,
                   created_at, updated_at
            FROM {table}
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
    table = _tenant_profile_table(db, tenant_id)

    # 既存行を確認
    existing = (await db.execute(
        text(f"SELECT id FROM {table} ORDER BY id LIMIT 1"),
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
            text(f"""
                SELECT id, company_name, company_name_en, address, phone, email,
                       website, seal_image_url, default_language,
                       created_at, updated_at
                FROM {table} WHERE id = :id
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
        text(f"UPDATE {table} SET {set_sql} WHERE id = :id"),
        params,
    )

    await record_audit_log(
        db=db, tenant_id=tenant_id, user_id=current_user.id,
        action="update", table_name="tenant_profile",
        record_id=existing["id"], new_data=payload,
    )
    await db.commit()

    row = (await db.execute(
        text(f"""
            SELECT id, company_name, company_name_en, address, phone, email,
                   website, seal_image_url, default_language,
                   created_at, updated_at
            FROM {table} WHERE id = :id
        """),
        {"id": existing["id"]},
    )).mappings().first()
    return TenantProfileResponse(**dict(row))
