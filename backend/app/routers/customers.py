from __future__ import annotations

"""
顧客管理API（CRUD）。

テナントスキーマの customers テーブルに対する操作を提供する。
search_path は get_current_tenant dependency で自動切り替え済み。

変更履歴:
  2026-04-16: Phase 1拡張（請求先/配送先、customer_code自動採番、
    require_permission権限チェック統合）
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, get_current_tenant, require_permission
from app.cache import invalidate_dashboard_cache
from app.database import get_db
from app.models import User
from app.schemas.customer import CustomerCreate, CustomerUpdate, CustomerResponse
from app.services.audit import record_audit_log

router = APIRouter()

# SELECT文で共通に使う列リスト
_CUSTOMER_COLUMNS = """
    id, customer_code, name, email, phone, company,
    registration_source, status,
    billing_name, billing_phone, billing_email, billing_address,
    delivery_name, delivery_phone, delivery_email, delivery_address, delivery_country,
    business_id, transaction_count, last_transaction_date,
    notes, created_at, updated_at
"""


@router.get(
    "/customers",
    response_model=list[CustomerResponse],
    dependencies=[Depends(require_permission("customers.view"))],
)
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
            text(f"""
                SELECT {_CUSTOMER_COLUMNS}
                FROM customers
                WHERE name ILIKE :search
                   OR email ILIKE :search
                   OR company ILIKE :search
                   OR customer_code ILIKE :search
                ORDER BY updated_at DESC
                LIMIT :limit OFFSET :offset
            """),
            {"search": f"%{search}%", "limit": per_page, "offset": offset},
        )
    else:
        result = await db.execute(
            text(f"""
                SELECT {_CUSTOMER_COLUMNS}
                FROM customers
                ORDER BY updated_at DESC
                LIMIT :limit OFFSET :offset
            """),
            {"limit": per_page, "offset": offset},
        )

    rows = result.mappings().all()
    return [CustomerResponse(**row) for row in rows]


@router.get(
    "/customers/{customer_id}",
    response_model=CustomerResponse,
    dependencies=[Depends(require_permission("customers.view"))],
)
async def get_customer(
    customer_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """顧客詳細を取得する"""
    result = await db.execute(
        text(f"SELECT {_CUSTOMER_COLUMNS} FROM customers WHERE id = :id"),
        {"id": customer_id},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="顧客が見つかりません")
    return CustomerResponse(**row)


@router.post(
    "/customers",
    response_model=CustomerResponse,
    status_code=201,
    dependencies=[Depends(require_permission("customers.create"))],
)
async def create_customer(
    data: CustomerCreate,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """顧客を登録する（customer_codeは自動採番）"""
    payload = data.model_dump()
    if payload.get("status") is None:
        payload["status"] = "active"
    payload["tenant_id"] = tenant_id

    result = await db.execute(
        text(f"""
            INSERT INTO customers (
                tenant_id, name, email, phone, company,
                registration_source, status,
                billing_name, billing_phone, billing_email, billing_address,
                delivery_name, delivery_phone, delivery_email, delivery_address, delivery_country,
                business_id, notes
            )
            VALUES (
                :tenant_id, :name, :email, :phone, :company,
                :registration_source, :status,
                :billing_name, :billing_phone, :billing_email, :billing_address,
                :delivery_name, :delivery_phone, :delivery_email, :delivery_address, :delivery_country,
                :business_id, :notes
            )
            RETURNING id
        """),
        payload,
    )
    new_id = result.scalar_one()

    # customer_code = CT-00001 形式で自動採番（idベース、Python側で生成してDB非依存）
    await db.execute(
        text("UPDATE customers SET customer_code = :code WHERE id = :id"),
        {"code": f"CT-{new_id:05d}", "id": new_id},
    )

    # 挿入後のレコードを再取得
    fetched = await db.execute(
        text(f"SELECT {_CUSTOMER_COLUMNS} FROM customers WHERE id = :id"),
        {"id": new_id},
    )
    row = fetched.mappings().first()

    await record_audit_log(
        db=db, tenant_id=tenant_id, user_id=current_user.id,
        action="create", table_name="customers", record_id=new_id,
        new_data=data.model_dump(exclude_none=True),
    )
    await db.commit()
    await invalidate_dashboard_cache(tenant_id)

    return CustomerResponse(**row)


@router.patch(
    "/customers/{customer_id}",
    response_model=CustomerResponse,
    dependencies=[Depends(require_permission("customers.update"))],
)
async def update_customer(
    customer_id: int,
    data: CustomerUpdate,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """顧客情報を更新する（部分更新）"""
    old_result = await db.execute(
        text(f"SELECT {_CUSTOMER_COLUMNS} FROM customers WHERE id = :id"),
        {"id": customer_id},
    )
    old_row = old_result.mappings().first()
    if not old_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="顧客が見つかりません")

    update_data = data.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="更新するフィールドを指定してください")

    set_clauses = ", ".join(f"{k} = :{k}" for k in update_data)
    update_data["id"] = customer_id

    result = await db.execute(
        text(f"""
            UPDATE customers SET {set_clauses}, updated_at = NOW()
            WHERE id = :id
            RETURNING {_CUSTOMER_COLUMNS}
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
    await invalidate_dashboard_cache(tenant_id)

    return CustomerResponse(**row)


@router.delete(
    "/customers/{customer_id}",
    status_code=204,
    dependencies=[Depends(require_permission("customers.delete"))],
)
async def delete_customer(
    customer_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """顧客を削除する"""
    old_result = await db.execute(
        text(f"SELECT {_CUSTOMER_COLUMNS} FROM customers WHERE id = :id"),
        {"id": customer_id},
    )
    old_row = old_result.mappings().first()
    if not old_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="顧客が見つかりません")

    try:
        await db.execute(text("DELETE FROM customers WHERE id = :id"), {"id": customer_id})
        await record_audit_log(
            db=db, tenant_id=tenant_id, user_id=current_user.id,
            action="delete", table_name="customers", record_id=customer_id,
            old_data=dict(old_row),
        )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="この顧客には関連する商談または注文があるため削除できません。先に関連データを削除してください。",
        )
    await invalidate_dashboard_cache(tenant_id)
