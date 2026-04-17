from __future__ import annotations

"""
仕入注文管理API（CRUD + 入荷処理 → 在庫自動加算）。

ステータス遷移: draft → ordered → received / cancelled

変更履歴:
  2026-04-17: 初版作成（Phase 3）
"""

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import (
    get_current_user,
    get_current_tenant,
    require_permission,
    reset_tenant_context,
)
from app.cache import invalidate_dashboard_cache
from app.database import get_db
from app.models import User
from app.schemas.purchase_order import (
    POCreate,
    PODetailResponse,
    POItemResponse,
    POResponse,
    POUpdate,
)
from app.services.audit import record_audit_log

router = APIRouter()

_PO_COLS = """
    id, po_number, supplier_id, status, total_amount,
    ordered_at, received_at, notes, created_by,
    created_at, updated_at
"""


async def _get_po_items(db: AsyncSession, po_id: int) -> list[dict]:
    result = await db.execute(
        text("SELECT id, product_id, quantity, unit_cost, subtotal, sort_order FROM purchase_order_items WHERE purchase_order_id = :pid ORDER BY sort_order, id"),
        {"pid": po_id},
    )
    return [dict(row) for row in result.mappings().all()]


@router.get("/purchase-orders", response_model=list[POResponse],
            dependencies=[Depends(require_permission("purchase_orders.view"))])
async def list_pos(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    status_filter: str | None = Query(default=None, alias="status"),
    supplier_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    offset = (page - 1) * per_page
    conditions = []
    params: dict = {"limit": per_page, "offset": offset}
    if status_filter:
        conditions.append("status = :status")
        params["status"] = status_filter
    if supplier_id:
        conditions.append("supplier_id = :sid")
        params["sid"] = supplier_id
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    result = await db.execute(
        text(f"SELECT {_PO_COLS} FROM purchase_orders {where} ORDER BY updated_at DESC LIMIT :limit OFFSET :offset"),
        params,
    )
    return [POResponse(**row) for row in result.mappings().all()]


@router.get("/purchase-orders/{po_id}", response_model=PODetailResponse,
            dependencies=[Depends(require_permission("purchase_orders.view"))])
async def get_po(po_id: int, db: AsyncSession = Depends(get_db),
                 tenant_id: int = Depends(get_current_tenant),
                 current_user: User = Depends(get_current_user)):
    result = await db.execute(text(f"SELECT {_PO_COLS} FROM purchase_orders WHERE id = :id"), {"id": po_id})
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="仕入注文が見つかりません")
    items = await _get_po_items(db, po_id)
    return PODetailResponse(**dict(row), items=[POItemResponse(**i) for i in items])


@router.post("/purchase-orders", response_model=PODetailResponse, status_code=201,
             dependencies=[Depends(require_permission("purchase_orders.create"))])
async def create_po(
    data: POCreate,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """仕入注文を作成する（draft状態、明細含む）"""
    # 仕入先存在確認
    sup = await db.execute(text("SELECT id FROM suppliers WHERE id = :id AND is_active = TRUE"), {"id": data.supplier_id})
    if not sup.first():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="指定された仕入先が見つかりません")

    total = sum(item.quantity * item.unit_cost for item in data.items)

    header = await db.execute(
        text(f"""
            INSERT INTO purchase_orders (tenant_id, supplier_id, status, total_amount, notes, created_by)
            VALUES (:tid, :sid, 'draft', :total, :notes, :by)
            RETURNING id
        """),
        {"tid": tenant_id, "sid": data.supplier_id, "total": total, "notes": data.notes, "by": current_user.id},
    )
    po_id = header.scalar_one()
    await db.execute(text("UPDATE purchase_orders SET po_number = :code WHERE id = :id"),
                     {"code": f"PO-{po_id:05d}", "id": po_id})

    for i, item in enumerate(data.items):
        await db.execute(
            text("""
                INSERT INTO purchase_order_items (purchase_order_id, product_id, quantity, unit_cost, subtotal, sort_order)
                VALUES (:pid, :prod, :qty, :cost, :sub, :sort)
            """),
            {"pid": po_id, "prod": item.product_id, "qty": item.quantity,
             "cost": item.unit_cost, "sub": item.quantity * item.unit_cost, "sort": i},
        )

    await record_audit_log(db=db, tenant_id=tenant_id, user_id=current_user.id,
                           action="create", table_name="purchase_orders", record_id=po_id,
                           new_data={"supplier_id": data.supplier_id, "items_count": len(data.items), "total": str(total)})
    await db.commit()
    await invalidate_dashboard_cache(tenant_id)
    await reset_tenant_context(db, tenant_id)

    fetched = await db.execute(text(f"SELECT {_PO_COLS} FROM purchase_orders WHERE id = :id"), {"id": po_id})
    row = fetched.mappings().first()
    items = await _get_po_items(db, po_id)
    return PODetailResponse(**dict(row), items=[POItemResponse(**i) for i in items])


@router.post("/purchase-orders/{po_id}/order", response_model=POResponse,
             dependencies=[Depends(require_permission("purchase_orders.update"))])
async def mark_ordered(po_id: int, db: AsyncSession = Depends(get_db),
                       tenant_id: int = Depends(get_current_tenant),
                       current_user: User = Depends(get_current_user)):
    """draft → ordered に遷移"""
    result = await db.execute(
        text(f"UPDATE purchase_orders SET status = 'ordered', ordered_at = NOW(), updated_at = NOW() WHERE id = :id AND status = 'draft' RETURNING {_PO_COLS}"),
        {"id": po_id},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="draft状態の注文のみ発注できます")
    await record_audit_log(db=db, tenant_id=tenant_id, user_id=current_user.id,
                           action="order", table_name="purchase_orders", record_id=po_id,
                           new_data={"status": "ordered"})
    await db.commit()
    return POResponse(**dict(row))


@router.post("/purchase-orders/{po_id}/receive", response_model=POResponse,
             dependencies=[Depends(require_permission("purchase_orders.receive"))])
async def mark_received(po_id: int, db: AsyncSession = Depends(get_db),
                        tenant_id: int = Depends(get_current_tenant),
                        current_user: User = Depends(get_current_user)):
    """
    ordered → received に遷移し、在庫を自動加算する。

    各明細の quantity 分だけ products.quantity を加算。
    """
    result = await db.execute(
        text(f"UPDATE purchase_orders SET status = 'received', received_at = NOW(), updated_at = NOW() WHERE id = :id AND status = 'ordered' RETURNING {_PO_COLS}"),
        {"id": po_id},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ordered状態の注文のみ入荷処理できます")

    # 在庫自動加算
    items = await _get_po_items(db, po_id)
    for item in items:
        await db.execute(
            text("UPDATE products SET quantity = quantity + :qty, updated_at = NOW() WHERE id = :pid"),
            {"qty": item["quantity"], "pid": item["product_id"]},
        )

    await record_audit_log(db=db, tenant_id=tenant_id, user_id=current_user.id,
                           action="receive", table_name="purchase_orders", record_id=po_id,
                           new_data={"status": "received", "items_received": len(items)})
    await db.commit()
    await invalidate_dashboard_cache(tenant_id)
    return POResponse(**dict(row))


@router.post("/purchase-orders/{po_id}/cancel", response_model=POResponse,
             dependencies=[Depends(require_permission("purchase_orders.update"))])
async def cancel_po(po_id: int, db: AsyncSession = Depends(get_db),
                    tenant_id: int = Depends(get_current_tenant),
                    current_user: User = Depends(get_current_user)):
    """draft/ordered → cancelled に遷移"""
    result = await db.execute(
        text(f"UPDATE purchase_orders SET status = 'cancelled', updated_at = NOW() WHERE id = :id AND status IN ('draft', 'ordered') RETURNING {_PO_COLS}"),
        {"id": po_id},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="draft/ordered状態の注文のみキャンセルできます")
    await record_audit_log(db=db, tenant_id=tenant_id, user_id=current_user.id,
                           action="cancel", table_name="purchase_orders", record_id=po_id,
                           new_data={"status": "cancelled"})
    await db.commit()
    return POResponse(**dict(row))
