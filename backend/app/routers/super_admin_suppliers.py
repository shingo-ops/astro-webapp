"""
中央 admin 用 public.suppliers + public.supplier_discord_routing CRUD ルーター。

spec.md v1.1 F2 (Sprint 2) / AC2.5:
  - supplier_type ('individual' / 'corporate') 切替
  - default_language ('ja' / 'en' / 'ko' / 'zh')
  - Discord routing 紐付け（1 supplier に対し複数 guild × channel 可）

API:
  GET    /api/v1/super-admin/suppliers
  POST   /api/v1/super-admin/suppliers
  PATCH  /api/v1/super-admin/suppliers/{id}
  DELETE /api/v1/super-admin/suppliers/{id}                    (soft delete)
  GET    /api/v1/super-admin/suppliers/{id}/discord-routing
  POST   /api/v1/super-admin/suppliers/{id}/discord-routing
  DELETE /api/v1/super-admin/suppliers/discord-routing/{routing_id}
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_super_admin
from app.database import get_db
from app.models import User
from app.schemas.central_masters import (
    CentralSupplierCreate,
    CentralSupplierResponse,
    CentralSupplierUpdate,
    SupplierDiscordRoutingCreate,
    SupplierDiscordRoutingResponse,
)

router = APIRouter()

_SUPPLIER_COLS = (
    "id, supplier_code, name, supplier_type, default_language, "
    "contact_name, email, phone, address, notes, is_active, created_at, updated_at"
)
_SUPPLIER_UPDATABLE = {
    "name", "supplier_type", "default_language",
    "contact_name", "email", "phone", "address", "notes", "is_active",
}

_ROUTING_COLS = "id, supplier_id, discord_guild_id, discord_channel_id, is_active"


@router.get(
    "/super-admin/suppliers",
    response_model=list[CentralSupplierResponse],
    dependencies=[Depends(require_super_admin)],
)
async def list_suppliers(
    q: str | None = Query(default=None, max_length=255),
    supplier_type: str | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    offset = (page - 1) * per_page
    conditions: list[str] = []
    params: dict = {"limit": per_page, "offset": offset}
    if q:
        conditions.append("(name ILIKE :q OR contact_name ILIKE :q OR supplier_code ILIKE :q)")
        params["q"] = f"%{q}%"
    if supplier_type:
        conditions.append("supplier_type = :supplier_type")
        params["supplier_type"] = supplier_type
    if is_active is not None:
        conditions.append("is_active = :is_active")
        params["is_active"] = is_active
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    result = await db.execute(
        text(
            f"SELECT {_SUPPLIER_COLS} FROM public.suppliers {where} "
            f"ORDER BY name LIMIT :limit OFFSET :offset"
        ),
        params,
    )
    return [CentralSupplierResponse(**dict(row)) for row in result.mappings().all()]


@router.post(
    "/super-admin/suppliers",
    response_model=CentralSupplierResponse,
    status_code=201,
    dependencies=[Depends(require_super_admin)],
)
async def create_supplier(
    data: CentralSupplierCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_super_admin),
):
    try:
        result = await db.execute(
            text(
                f"INSERT INTO public.suppliers "
                f"(name, supplier_type, default_language, contact_name, email, phone, "
                f" address, notes, is_active, created_by) "
                f"VALUES (:name, :supplier_type, :default_language, :contact_name, :email, "
                f"        :phone, :address, :notes, :is_active, :uid) "
                f"RETURNING {_SUPPLIER_COLS}"
            ),
            {**data.model_dump(), "uid": current_user.id},
        )
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"重複または制約違反: {exc.orig}",
        )
    row = result.mappings().first()
    new_id = row["id"]
    # supplier_code を自動採番（既存 {tenant}.suppliers パターン踏襲）
    await db.execute(
        text("UPDATE public.suppliers SET supplier_code = :code WHERE id = :id AND supplier_code IS NULL"),
        {"code": f"SP-{new_id:05d}", "id": new_id},
    )
    fetched = await db.execute(
        text(f"SELECT {_SUPPLIER_COLS} FROM public.suppliers WHERE id = :id"),
        {"id": new_id},
    )
    row = fetched.mappings().first()
    await db.commit()
    return CentralSupplierResponse(**dict(row))


@router.patch(
    "/super-admin/suppliers/{supplier_id}",
    response_model=CentralSupplierResponse,
    dependencies=[Depends(require_super_admin)],
)
async def update_supplier(
    supplier_id: int,
    data: CentralSupplierUpdate,
    db: AsyncSession = Depends(get_db),
):
    update_data = data.model_dump(exclude_unset=True)
    update_data = {k: v for k, v in update_data.items() if k in _SUPPLIER_UPDATABLE}
    if not update_data:
        raise HTTPException(status_code=400, detail="更新するフィールドを指定してください")
    set_clauses = ", ".join(f"{k} = :{k}" for k in update_data)
    update_data["id"] = supplier_id
    try:
        result = await db.execute(
            text(
                f"UPDATE public.suppliers SET {set_clauses}, updated_at = NOW() "
                f"WHERE id = :id RETURNING {_SUPPLIER_COLS}"
            ),
            update_data,
        )
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=f"制約違反: {exc.orig}")
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="仕入元が見つかりません")
    await db.commit()
    return CentralSupplierResponse(**dict(row))


@router.delete(
    "/super-admin/suppliers/{supplier_id}",
    status_code=204,
    dependencies=[Depends(require_super_admin)],
)
async def delete_supplier(
    supplier_id: int,
    db: AsyncSession = Depends(get_db),
):
    """soft delete (is_active=false)。public schema の supplier は他テーブルから
    FK 参照されるため hard delete はしない。"""
    result = await db.execute(
        text(
            "UPDATE public.suppliers SET is_active = FALSE, updated_at = NOW() "
            "WHERE id = :id"
        ),
        {"id": supplier_id},
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="仕入元が見つかりません")
    await db.commit()


# ----------------------------------------------------------------------------
# supplier_discord_routing
# ----------------------------------------------------------------------------


@router.get(
    "/super-admin/suppliers/{supplier_id}/discord-routing",
    response_model=list[SupplierDiscordRoutingResponse],
    dependencies=[Depends(require_super_admin)],
)
async def list_routing(supplier_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        text(
            f"SELECT {_ROUTING_COLS} FROM public.supplier_discord_routing "
            f"WHERE supplier_id = :sid ORDER BY id"
        ),
        {"sid": supplier_id},
    )
    return [SupplierDiscordRoutingResponse(**dict(row)) for row in result.mappings().all()]


@router.post(
    "/super-admin/suppliers/{supplier_id}/discord-routing",
    response_model=SupplierDiscordRoutingResponse,
    status_code=201,
    dependencies=[Depends(require_super_admin)],
)
async def create_routing(
    supplier_id: int,
    data: SupplierDiscordRoutingCreate,
    db: AsyncSession = Depends(get_db),
):
    if data.supplier_id != supplier_id:
        raise HTTPException(
            status_code=400,
            detail="URL の supplier_id と body の supplier_id が一致しません",
        )
    try:
        result = await db.execute(
            text(
                f"INSERT INTO public.supplier_discord_routing "
                f"(supplier_id, discord_guild_id, discord_channel_id, is_active) "
                f"VALUES (:supplier_id, :discord_guild_id, :discord_channel_id, :is_active) "
                f"RETURNING {_ROUTING_COLS}"
            ),
            data.model_dump(),
        )
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"重複または FK 違反: {exc.orig}",
        )
    row = result.mappings().first()
    await db.commit()
    return SupplierDiscordRoutingResponse(**dict(row))


@router.delete(
    "/super-admin/suppliers/discord-routing/{routing_id}",
    status_code=204,
    dependencies=[Depends(require_super_admin)],
)
async def delete_routing(routing_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        text("DELETE FROM public.supplier_discord_routing WHERE id = :id"),
        {"id": routing_id},
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="routing が見つかりません")
    await db.commit()
