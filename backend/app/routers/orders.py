from __future__ import annotations

"""
注文管理API（CRUD）。

テナントスキーマの orders テーブルに対する操作を提供する。
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, get_current_tenant
from app.database import get_db
from app.models import User
from app.schemas.order import OrderCreate, OrderUpdate, OrderResponse
from app.services.audit import record_audit_log

router = APIRouter()

_SELECT_COLS = "id, customer_id, deal_id, order_number, total_amount, status, notes, created_at, updated_at"


@router.get("/orders", response_model=list[OrderResponse])
async def list_orders(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    status_filter: str | None = Query(default=None, alias="status"),
    customer_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """注文一覧を取得する"""
    offset = (page - 1) * per_page
    conditions = []
    params: dict = {"limit": per_page, "offset": offset}

    if status_filter:
        conditions.append("status = :status")
        params["status"] = status_filter
    if customer_id:
        conditions.append("customer_id = :customer_id")
        params["customer_id"] = customer_id

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    result = await db.execute(
        text(f"""
            SELECT {_SELECT_COLS}
            FROM orders
            {where_clause}
            ORDER BY updated_at DESC
            LIMIT :limit OFFSET :offset
        """),
        params,
    )
    rows = result.mappings().all()
    return [OrderResponse(**row) for row in rows]


@router.get("/orders/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """注文詳細を取得する"""
    result = await db.execute(
        text(f"SELECT {_SELECT_COLS} FROM orders WHERE id = :id"),
        {"id": order_id},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="注文が見つかりません")
    return OrderResponse(**row)


@router.post("/orders", response_model=OrderResponse, status_code=201)
async def create_order(
    data: OrderCreate,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """注文を登録する"""
    # 顧客の存在確認
    cust = await db.execute(text("SELECT id FROM customers WHERE id = :id"), {"id": data.customer_id})
    if not cust.first():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="指定された顧客が存在しません")

    # 商談の存在確認（指定された場合）
    if data.deal_id:
        deal = await db.execute(text("SELECT id FROM deals WHERE id = :id"), {"id": data.deal_id})
        if not deal.first():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="指定された商談が存在しません")

    # 注文番号の重複チェック
    dup = await db.execute(
        text("SELECT id FROM orders WHERE order_number = :order_number"),
        {"order_number": data.order_number},
    )
    if dup.first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="この注文番号は既に使用されています")

    result = await db.execute(
        text(f"""
            INSERT INTO orders (tenant_id, customer_id, deal_id, order_number, total_amount, status, notes)
            VALUES (:tenant_id, :customer_id, :deal_id, :order_number, :total_amount, :status, :notes)
            RETURNING {_SELECT_COLS}
        """),
        {
            "tenant_id": tenant_id,
            "customer_id": data.customer_id,
            "deal_id": data.deal_id,
            "order_number": data.order_number,
            "total_amount": data.total_amount,
            "status": data.status.value,
            "notes": data.notes,
        },
    )
    row = result.mappings().first()

    await record_audit_log(
        db=db, tenant_id=tenant_id, user_id=current_user.id,
        action="create", table_name="orders", record_id=row["id"],
        new_data=data.model_dump(exclude_none=True, mode="json"),
    )
    await db.commit()

    return OrderResponse(**row)


@router.patch("/orders/{order_id}", response_model=OrderResponse)
async def update_order(
    order_id: int,
    data: OrderUpdate,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """注文情報を更新する（部分更新）"""
    old_result = await db.execute(
        text(f"SELECT {_SELECT_COLS} FROM orders WHERE id = :id"),
        {"id": order_id},
    )
    old_row = old_result.mappings().first()
    if not old_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="注文が見つかりません")

    update_data = data.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="更新するフィールドを指定してください")

    if "status" in update_data and update_data["status"] is not None:
        update_data["status"] = update_data["status"].value

    set_clauses = ", ".join(f"{k} = :{k}" for k in update_data)
    update_data["id"] = order_id

    result = await db.execute(
        text(f"""
            UPDATE orders SET {set_clauses}, updated_at = NOW()
            WHERE id = :id
            RETURNING {_SELECT_COLS}
        """),
        update_data,
    )
    row = result.mappings().first()

    await record_audit_log(
        db=db, tenant_id=tenant_id, user_id=current_user.id,
        action="update", table_name="orders", record_id=order_id,
        old_data=dict(old_row), new_data=update_data,
    )
    await db.commit()

    return OrderResponse(**row)


@router.delete("/orders/{order_id}", status_code=204)
async def delete_order(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """注文を削除する"""
    old_result = await db.execute(
        text(f"SELECT {_SELECT_COLS} FROM orders WHERE id = :id"),
        {"id": order_id},
    )
    old_row = old_result.mappings().first()
    if not old_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="注文が見つかりません")

    await db.execute(text("DELETE FROM orders WHERE id = :id"), {"id": order_id})

    await record_audit_log(
        db=db, tenant_id=tenant_id, user_id=current_user.id,
        action="delete", table_name="orders", record_id=order_id,
        old_data=dict(old_row),
    )
    await db.commit()
