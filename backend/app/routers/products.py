from __future__ import annotations

"""
商品・在庫管理API（CRUD + 在庫チェック）。

変更履歴:
  2026-04-17: 初版作成（Phase 2）
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, get_current_tenant, require_permission
from app.cache import invalidate_dashboard_cache
from app.database import get_db
from app.models import User
from app.schemas.product import (
    InventoryCheckResponse,
    ProductCreate,
    ProductResponse,
    ProductUpdate,
)
from app.services.audit import record_audit_log

router = APIRouter()

_PRODUCT_COLUMNS = """
    id, product_code, name_ja, name_en, category, mark,
    status, condition, unit_price, quantity, weight,
    notes, release_date, created_at, updated_at
"""

_UPDATABLE_COLUMNS = {
    "name_ja", "name_en", "category", "mark", "status", "condition",
    "unit_price", "quantity", "weight", "notes", "release_date",
}


@router.get(
    "/products",
    response_model=list[ProductResponse],
    dependencies=[Depends(require_permission("products.view"))],
)
async def list_products(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None, max_length=255),
    category: str | None = Query(default=None, max_length=100),
    status_filter: str | None = Query(default=None, alias="status"),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    offset = (page - 1) * per_page
    conditions = []
    params: dict = {"limit": per_page, "offset": offset}

    if search:
        conditions.append(
            "(name_ja ILIKE :search OR name_en ILIKE :search OR product_code ILIKE :search OR mark ILIKE :search)"
        )
        params["search"] = f"%{search}%"
    if category:
        conditions.append("category = :category")
        params["category"] = category
    if status_filter:
        conditions.append("status = :status")
        params["status"] = status_filter

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    result = await db.execute(
        text(f"SELECT {_PRODUCT_COLUMNS} FROM products {where} ORDER BY updated_at DESC LIMIT :limit OFFSET :offset"),
        params,
    )
    return [ProductResponse(**row) for row in result.mappings().all()]


@router.get(
    "/products/{product_id}",
    response_model=ProductResponse,
    dependencies=[Depends(require_permission("products.view"))],
)
async def get_product(
    product_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        text(f"SELECT {_PRODUCT_COLUMNS} FROM products WHERE id = :id"),
        {"id": product_id},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="商品が見つかりません")
    return ProductResponse(**row)


@router.post(
    "/products",
    response_model=ProductResponse,
    status_code=201,
    dependencies=[Depends(require_permission("products.create"))],
)
async def create_product(
    data: ProductCreate,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    payload = data.model_dump()
    if payload.get("status") is not None:
        payload["status"] = payload["status"].value if hasattr(payload["status"], "value") else payload["status"]
    payload["tenant_id"] = tenant_id

    result = await db.execute(
        text("""
            INSERT INTO products (
                tenant_id, name_ja, name_en, category, mark,
                status, condition, unit_price, quantity, weight,
                notes, release_date
            ) VALUES (
                :tenant_id, :name_ja, :name_en, :category, :mark,
                :status, :condition, :unit_price, :quantity, :weight,
                :notes, :release_date
            ) RETURNING id
        """),
        payload,
    )
    new_id = result.scalar_one()

    await db.execute(
        text("UPDATE products SET product_code = :code WHERE id = :id"),
        {"code": f"PD-{new_id:05d}", "id": new_id},
    )

    fetched = await db.execute(
        text(f"SELECT {_PRODUCT_COLUMNS} FROM products WHERE id = :id"),
        {"id": new_id},
    )
    row = fetched.mappings().first()

    await record_audit_log(
        db=db, tenant_id=tenant_id, user_id=current_user.id,
        action="create", table_name="products", record_id=new_id,
        new_data=data.model_dump(exclude_none=True, mode="json"),
    )
    await db.commit()
    await invalidate_dashboard_cache(tenant_id)

    return ProductResponse(**row)


@router.patch(
    "/products/{product_id}",
    response_model=ProductResponse,
    dependencies=[Depends(require_permission("products.update"))],
)
async def update_product(
    product_id: int,
    data: ProductUpdate,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    old_result = await db.execute(
        text(f"SELECT {_PRODUCT_COLUMNS} FROM products WHERE id = :id"),
        {"id": product_id},
    )
    old_row = old_result.mappings().first()
    if not old_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="商品が見つかりません")

    update_data = data.model_dump(exclude_unset=True)
    update_data = {k: v for k, v in update_data.items() if k in _UPDATABLE_COLUMNS}
    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="更新するフィールドを指定してください")

    if "status" in update_data and update_data["status"] is not None:
        update_data["status"] = update_data["status"].value if hasattr(update_data["status"], "value") else update_data["status"]

    set_clauses = ", ".join(f"{k} = :{k}" for k in update_data)
    update_data["id"] = product_id

    result = await db.execute(
        text(f"""
            UPDATE products SET {set_clauses}, updated_at = NOW()
            WHERE id = :id
            RETURNING {_PRODUCT_COLUMNS}
        """),
        update_data,
    )
    row = result.mappings().first()

    await record_audit_log(
        db=db, tenant_id=tenant_id, user_id=current_user.id,
        action="update", table_name="products", record_id=product_id,
        old_data=dict(old_row), new_data=update_data,
    )
    await db.commit()
    await invalidate_dashboard_cache(tenant_id)

    return ProductResponse(**row)


@router.delete(
    "/products/{product_id}",
    status_code=204,
    dependencies=[Depends(require_permission("products.delete"))],
)
async def delete_product(
    product_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    old_result = await db.execute(
        text(f"SELECT {_PRODUCT_COLUMNS} FROM products WHERE id = :id"),
        {"id": product_id},
    )
    old_row = old_result.mappings().first()
    if not old_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="商品が見つかりません")

    await db.execute(text("DELETE FROM products WHERE id = :id"), {"id": product_id})
    await record_audit_log(
        db=db, tenant_id=tenant_id, user_id=current_user.id,
        action="delete", table_name="products", record_id=product_id,
        old_data=dict(old_row),
    )
    await db.commit()
    await invalidate_dashboard_cache(tenant_id)


@router.get(
    "/products/{product_id}/check-inventory",
    response_model=InventoryCheckResponse,
    dependencies=[Depends(require_permission("products.view"))],
)
async def check_inventory(
    product_id: int,
    quantity: int = Query(ge=1),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """指定商品の在庫が要求数量を満たすか確認する"""
    result = await db.execute(
        text("SELECT id, name_ja, quantity FROM products WHERE id = :id"),
        {"id": product_id},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="商品が見つかりません")

    return InventoryCheckResponse(
        product_id=row["id"],
        product_name=row["name_ja"],
        available=row["quantity"] >= quantity,
        current_quantity=row["quantity"],
        requested_quantity=quantity,
    )
