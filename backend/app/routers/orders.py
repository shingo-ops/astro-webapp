from __future__ import annotations

"""
注文管理API（CRUD）。

テナントスキーマの orders テーブルに対する操作を提供する。

変更履歴:
  2026-04-17: Phase 2拡張（配送情報、invoice_id、ステータス拡張）
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, get_current_tenant, require_permission
from app.cache import invalidate_dashboard_cache
from app.database import get_db
from app.models import User
from app.schemas.order import OrderCreate, OrderUpdate, OrderResponse
from app.services.audit import record_audit_log

router = APIRouter()

_SELECT_COLS = """
    id, customer_id, company_id, contact_id, deal_id, invoice_id, order_number,
    total_amount, currency, status,
    shipping_carrier, shipping_fee, tracking_number,
    shipped_at, delivered_at, shipping_country,
    notes, created_at, updated_at
"""

# customer_id / company_id / contact_id / deal_id / invoice_id は作成後の変更を禁止（FK整合性保護）
_UPDATABLE_COLUMNS = {
    "order_number", "total_amount", "currency", "status",
    "shipping_carrier", "shipping_fee", "tracking_number",
    "shipping_country", "notes",
}


@router.get("/orders", response_model=list[OrderResponse],
            dependencies=[Depends(require_permission("orders.view"))])
async def list_orders(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    status_filter: str | None = Query(default=None, alias="status"),
    customer_id: int | None = Query(default=None),
    company_id: int | None = Query(default=None),
    contact_id: int | None = Query(default=None),
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
    # Phase 1-B-2 Step 5b-2: 新モデル filter
    if company_id:
        conditions.append("company_id = :company_id")
        params["company_id"] = company_id
    if contact_id:
        conditions.append("contact_id = :contact_id")
        params["contact_id"] = contact_id

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


@router.get("/orders/{order_id}", response_model=OrderResponse,
            dependencies=[Depends(require_permission("orders.view"))])
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


@router.post("/orders", response_model=OrderResponse, status_code=201,
             dependencies=[Depends(require_permission("orders.create"))])
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

    # Phase 1-B-2 Step 5b-2: company_id/contact_id 指定時の存在確認
    # 両方指定時は contact が company に所属しているかも検証（reviewer Major 1 対応）
    if data.contact_id is not None:
        contact_check = await db.execute(
            text("SELECT company_id FROM contacts WHERE id = :id"),
            {"id": data.contact_id},
        )
        contact_row = contact_check.first()
        if not contact_row:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="指定された担当者が存在しません")
        if data.company_id is not None and contact_row[0] != data.company_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="指定された担当者は指定会社に所属していません",
            )
    elif data.company_id is not None:
        company_check = await db.execute(text("SELECT id FROM companies WHERE id = :id"), {"id": data.company_id})
        if not company_check.first():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="指定された会社が存在しません")

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
            INSERT INTO orders (
                tenant_id, customer_id, company_id, contact_id, deal_id, invoice_id, order_number,
                total_amount, currency, status,
                shipping_carrier, shipping_fee, shipping_country, notes
            )
            VALUES (
                :tenant_id, :customer_id, :company_id, :contact_id, :deal_id, :invoice_id, :order_number,
                :total_amount, :currency, :status,
                :shipping_carrier, :shipping_fee, :shipping_country, :notes
            )
            RETURNING {_SELECT_COLS}
        """),
        {
            "tenant_id": tenant_id,
            "customer_id": data.customer_id,
            "company_id": data.company_id,
            "contact_id": data.contact_id,
            "deal_id": data.deal_id,
            "invoice_id": data.invoice_id,
            "order_number": data.order_number,
            "total_amount": data.total_amount,
            "currency": data.currency,
            "status": data.status.value,
            "shipping_carrier": data.shipping_carrier,
            "shipping_fee": data.shipping_fee,
            "shipping_country": data.shipping_country,
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
    await invalidate_dashboard_cache(tenant_id)

    return OrderResponse(**row)


@router.patch("/orders/{order_id}", response_model=OrderResponse,
              dependencies=[Depends(require_permission("orders.update"))])
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
    update_data = {k: v for k, v in update_data.items() if k in _UPDATABLE_COLUMNS}
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
    await invalidate_dashboard_cache(tenant_id)

    return OrderResponse(**row)


@router.delete("/orders/{order_id}", status_code=204,
               dependencies=[Depends(require_permission("orders.delete"))])
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
    await invalidate_dashboard_cache(tenant_id)
