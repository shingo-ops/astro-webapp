from __future__ import annotations

"""
仕入先管理API（CRUD）。

変更履歴:
  2026-04-17: 初版作成（Phase 3）
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import (
    get_current_tenant,
    get_current_user,
    require_permission,
    reset_tenant_context,
)
from app.database import get_db
from app.models import User
from app.schemas.supplier import SupplierCreate, SupplierResponse, SupplierUpdate
from app.services.audit import record_audit_log

router = APIRouter()

_COLS = """
    id, supplier_code, name, contact_name, email, phone, address,
    notes, is_active, created_at, updated_at
"""
_UPDATABLE = {"name", "contact_name", "email", "phone", "address", "notes", "is_active"}


@router.get("/suppliers", response_model=list[SupplierResponse],
            dependencies=[Depends(require_permission("suppliers.view"))])
async def list_suppliers(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None, max_length=255),
    active_only: bool = Query(default=True),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    offset = (page - 1) * per_page
    conditions = []
    params: dict = {"limit": per_page, "offset": offset}
    if active_only:
        conditions.append("is_active = TRUE")
    if search:
        conditions.append("(name ILIKE :search OR contact_name ILIKE :search OR supplier_code ILIKE :search)")
        params["search"] = f"%{search}%"
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    result = await db.execute(
        text(f"SELECT {_COLS} FROM suppliers {where} ORDER BY name LIMIT :limit OFFSET :offset"), params)
    return [SupplierResponse(**row) for row in result.mappings().all()]


@router.get("/suppliers/{supplier_id}", response_model=SupplierResponse,
            dependencies=[Depends(require_permission("suppliers.view"))])
async def get_supplier(supplier_id: int, db: AsyncSession = Depends(get_db),
                       tenant_id: int = Depends(get_current_tenant),
                       current_user: User = Depends(get_current_user)):
    result = await db.execute(text(f"SELECT {_COLS} FROM suppliers WHERE id = :id"), {"id": supplier_id})
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="仕入先が見つかりません")
    return SupplierResponse(**row)


@router.post("/suppliers", response_model=SupplierResponse, status_code=201,
             dependencies=[Depends(require_permission("suppliers.create"))])
async def create_supplier(data: SupplierCreate, db: AsyncSession = Depends(get_db),
                          tenant_id: int = Depends(get_current_tenant),
                          current_user: User = Depends(get_current_user)):
    result = await db.execute(
        text("""
            INSERT INTO suppliers (tenant_id, name, contact_name, email, phone, address, notes)
            VALUES (:tid, :name, :contact, :email, :phone, :addr, :notes)
            RETURNING id
        """),
        {"tid": tenant_id, "name": data.name, "contact": data.contact_name,
         "email": data.email, "phone": data.phone, "addr": data.address, "notes": data.notes},
    )
    new_id = result.scalar_one()
    await db.execute(text("UPDATE suppliers SET supplier_code = :code WHERE id = :id"),
                     {"code": f"SP-{new_id:05d}", "id": new_id})
    fetched = await db.execute(text(f"SELECT {_COLS} FROM suppliers WHERE id = :id"), {"id": new_id})
    row = fetched.mappings().first()
    await record_audit_log(db=db, tenant_id=tenant_id, user_id=current_user.id,
                           action="create", table_name="suppliers", record_id=new_id,
                           new_data=data.model_dump(exclude_none=True))
    await db.commit()
    await reset_tenant_context(db, tenant_id)  # ADR-072 Phase 2
    return SupplierResponse(**row)


@router.patch("/suppliers/{supplier_id}", response_model=SupplierResponse,
              dependencies=[Depends(require_permission("suppliers.update"))])
async def update_supplier(supplier_id: int, data: SupplierUpdate,
                          db: AsyncSession = Depends(get_db),
                          tenant_id: int = Depends(get_current_tenant),
                          current_user: User = Depends(get_current_user)):
    old = await db.execute(text(f"SELECT {_COLS} FROM suppliers WHERE id = :id"), {"id": supplier_id})
    old_row = old.mappings().first()
    if not old_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="仕入先が見つかりません")
    update_data = data.model_dump(exclude_unset=True)
    update_data = {k: v for k, v in update_data.items() if k in _UPDATABLE}
    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="更新するフィールドを指定してください")
    set_clauses = ", ".join(f"{k} = :{k}" for k in update_data)
    update_data["id"] = supplier_id
    result = await db.execute(
        text(f"UPDATE suppliers SET {set_clauses}, updated_at = NOW() WHERE id = :id RETURNING {_COLS}"),
        update_data)
    row = result.mappings().first()
    await record_audit_log(db=db, tenant_id=tenant_id, user_id=current_user.id,
                           action="update", table_name="suppliers", record_id=supplier_id,
                           old_data=dict(old_row), new_data=update_data)
    await db.commit()
    await reset_tenant_context(db, tenant_id)  # ADR-072 Phase 2
    return SupplierResponse(**dict(row))


@router.delete("/suppliers/{supplier_id}", status_code=204,
               dependencies=[Depends(require_permission("suppliers.delete"))])
async def delete_supplier(supplier_id: int, db: AsyncSession = Depends(get_db),
                          tenant_id: int = Depends(get_current_tenant),
                          current_user: User = Depends(get_current_user)):
    old = await db.execute(text(f"SELECT {_COLS} FROM suppliers WHERE id = :id"), {"id": supplier_id})
    old_row = old.mappings().first()
    if not old_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="仕入先が見つかりません")
    await db.execute(text("UPDATE suppliers SET is_active = FALSE, updated_at = NOW() WHERE id = :id"),
                     {"id": supplier_id})
    await record_audit_log(db=db, tenant_id=tenant_id, user_id=current_user.id,
                           action="soft_delete", table_name="suppliers", record_id=supplier_id,
                           old_data=dict(old_row))
    await db.commit()
    await reset_tenant_context(db, tenant_id)  # ADR-072 Phase 2
