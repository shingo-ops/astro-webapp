"""
顧客管理API（CRUD）。

テナントスキーマの customers テーブルに対する操作を提供する。
search_path は get_current_tenant dependency で自動切り替え済み。
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, get_current_tenant
from app.database import get_db
from app.models import User
from app.schemas.customer import CustomerCreate, CustomerUpdate, CustomerResponse
from app.services.audit import record_audit_log

router = APIRouter()


@router.get("/customers", response_model=list[CustomerResponse])
async def list_customers(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None, max_length=255),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """顧客一覧を取得する"""
    offset = (page - 1) * per_page

    if search:
        result = await db.execute(
            text("""
                SELECT id, name, email, phone, company, notes, created_at, updated_at
                FROM customers
                WHERE name ILIKE :search OR email ILIKE :search OR company ILIKE :search
                ORDER BY updated_at DESC
                LIMIT :limit OFFSET :offset
            """),
            {"search": f"%{search}%", "limit": per_page, "offset": offset},
        )
    else:
        result = await db.execute(
            text("""
                SELECT id, name, email, phone, company, notes, created_at, updated_at
                FROM customers
                ORDER BY updated_at DESC
                LIMIT :limit OFFSET :offset
            """),
            {"limit": per_page, "offset": offset},
        )

    rows = result.mappings().all()
    return [CustomerResponse(**row) for row in rows]


@router.get("/customers/{customer_id}", response_model=CustomerResponse)
async def get_customer(
    customer_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """顧客詳細を取得する"""
    result = await db.execute(
        text("SELECT id, name, email, phone, company, notes, created_at, updated_at FROM customers WHERE id = :id"),
        {"id": customer_id},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="顧客が見つかりません")
    return CustomerResponse(**row)


@router.post("/customers", response_model=CustomerResponse, status_code=201)
async def create_customer(
    data: CustomerCreate,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """顧客を登録する"""
    result = await db.execute(
        text("""
            INSERT INTO customers (tenant_id, name, email, phone, company, notes)
            VALUES (:tenant_id, :name, :email, :phone, :company, :notes)
            RETURNING id, name, email, phone, company, notes, created_at, updated_at
        """),
        {
            "tenant_id": tenant_id,
            "name": data.name,
            "email": data.email,
            "phone": data.phone,
            "company": data.company,
            "notes": data.notes,
        },
    )
    row = result.mappings().first()

    await record_audit_log(
        db=db, tenant_id=tenant_id, user_id=current_user.id,
        action="create", table_name="customers", record_id=row["id"],
        new_data=data.model_dump(exclude_none=True),
    )
    await db.commit()

    return CustomerResponse(**row)


@router.patch("/customers/{customer_id}", response_model=CustomerResponse)
async def update_customer(
    customer_id: int,
    data: CustomerUpdate,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """顧客情報を更新する（部分更新）"""
    # 更新前のデータを取得
    old_result = await db.execute(
        text("SELECT id, name, email, phone, company, notes, created_at, updated_at FROM customers WHERE id = :id"),
        {"id": customer_id},
    )
    old_row = old_result.mappings().first()
    if not old_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="顧客が見つかりません")

    # 指定されたフィールドのみ更新
    update_data = data.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="更新するフィールドを指定してください")

    set_clauses = ", ".join(f"{k} = :{k}" for k in update_data)
    update_data["id"] = customer_id

    result = await db.execute(
        text(f"""
            UPDATE customers SET {set_clauses}, updated_at = NOW()
            WHERE id = :id
            RETURNING id, name, email, phone, company, notes, created_at, updated_at
        """),
        update_data,
    )
    row = result.mappings().first()

    await record_audit_log(
        db=db, tenant_id=tenant_id, user_id=current_user.id,
        action="update", table_name="customers", record_id=customer_id,
        old_data=dict(old_row), new_data=update_data,
    )
    await db.commit()

    return CustomerResponse(**row)


@router.delete("/customers/{customer_id}", status_code=204)
async def delete_customer(
    customer_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """顧客を削除する"""
    old_result = await db.execute(
        text("SELECT id, name, email, phone, company, notes, created_at, updated_at FROM customers WHERE id = :id"),
        {"id": customer_id},
    )
    old_row = old_result.mappings().first()
    if not old_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="顧客が見つかりません")

    await db.execute(text("DELETE FROM customers WHERE id = :id"), {"id": customer_id})

    await record_audit_log(
        db=db, tenant_id=tenant_id, user_id=current_user.id,
        action="delete", table_name="customers", record_id=customer_id,
        old_data=dict(old_row),
    )
    await db.commit()
