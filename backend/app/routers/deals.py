from __future__ import annotations

"""
案件管理API（CRUD）。

テナントスキーマの deals テーブルに対する操作を提供する。
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, get_current_tenant
from app.cache import invalidate_dashboard_cache
from app.database import get_db
from app.models import User
from app.schemas.deal import DealCreate, DealUpdate, DealResponse
from app.services.audit import record_audit_log

router = APIRouter()


@router.get("/deals", response_model=list[DealResponse])
async def list_deals(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    status_filter: str | None = Query(default=None, alias="status"),
    customer_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """商談一覧を取得する"""
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
            SELECT id, customer_id, title, amount, status, expected_close_date,
                   notes, created_at, updated_at
            FROM deals
            {where_clause}
            ORDER BY updated_at DESC
            LIMIT :limit OFFSET :offset
        """),
        params,
    )
    rows = result.mappings().all()
    return [DealResponse(**row) for row in rows]


@router.get("/deals/{deal_id}", response_model=DealResponse)
async def get_deal(
    deal_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """商談詳細を取得する"""
    result = await db.execute(
        text("""
            SELECT id, customer_id, title, amount, status, expected_close_date,
                   notes, created_at, updated_at
            FROM deals WHERE id = :id
        """),
        {"id": deal_id},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="商談が見つかりません")
    return DealResponse(**row)


@router.post("/deals", response_model=DealResponse, status_code=201)
async def create_deal(
    data: DealCreate,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """商談を登録する"""
    # 顧客の存在確認
    cust = await db.execute(text("SELECT id FROM customers WHERE id = :id"), {"id": data.customer_id})
    if not cust.first():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="指定された顧客が存在しません")

    result = await db.execute(
        text("""
            INSERT INTO deals (tenant_id, customer_id, title, amount, status, expected_close_date, notes)
            VALUES (:tenant_id, :customer_id, :title, :amount, :status, :expected_close_date, :notes)
            RETURNING id, customer_id, title, amount, status, expected_close_date, notes, created_at, updated_at
        """),
        {
            "tenant_id": tenant_id,
            "customer_id": data.customer_id,
            "title": data.title,
            "amount": data.amount,
            "status": data.status.value,
            "expected_close_date": data.expected_close_date,
            "notes": data.notes,
        },
    )
    row = result.mappings().first()

    await record_audit_log(
        db=db, tenant_id=tenant_id, user_id=current_user.id,
        action="create", table_name="deals", record_id=row["id"],
        new_data=data.model_dump(exclude_none=True, mode="json"),
    )
    await db.commit()
    await invalidate_dashboard_cache(tenant_id)

    return DealResponse(**row)


@router.patch("/deals/{deal_id}", response_model=DealResponse)
async def update_deal(
    deal_id: int,
    data: DealUpdate,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """商談情報を更新する（部分更新）"""
    old_result = await db.execute(
        text("""
            SELECT id, customer_id, title, amount, status, expected_close_date,
                   notes, created_at, updated_at
            FROM deals WHERE id = :id
        """),
        {"id": deal_id},
    )
    old_row = old_result.mappings().first()
    if not old_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="商談が見つかりません")

    update_data = data.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="更新するフィールドを指定してください")

    if "status" in update_data and update_data["status"] is not None:
        update_data["status"] = update_data["status"].value

    set_clauses = ", ".join(f"{k} = :{k}" for k in update_data)
    update_data["id"] = deal_id

    result = await db.execute(
        text(f"""
            UPDATE deals SET {set_clauses}, updated_at = NOW()
            WHERE id = :id
            RETURNING id, customer_id, title, amount, status, expected_close_date, notes, created_at, updated_at
        """),
        update_data,
    )
    row = result.mappings().first()

    await record_audit_log(
        db=db, tenant_id=tenant_id, user_id=current_user.id,
        action="update", table_name="deals", record_id=deal_id,
        old_data=dict(old_row), new_data=update_data,
    )
    await db.commit()
    await invalidate_dashboard_cache(tenant_id)

    return DealResponse(**row)


@router.delete("/deals/{deal_id}", status_code=204)
async def delete_deal(
    deal_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """商談を削除する"""
    old_result = await db.execute(
        text("""
            SELECT id, customer_id, title, amount, status, expected_close_date,
                   notes, created_at, updated_at
            FROM deals WHERE id = :id
        """),
        {"id": deal_id},
    )
    old_row = old_result.mappings().first()
    if not old_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="商談が見つかりません")

    try:
        await db.execute(text("DELETE FROM deals WHERE id = :id"), {"id": deal_id})
        await record_audit_log(
            db=db, tenant_id=tenant_id, user_id=current_user.id,
            action="delete", table_name="deals", record_id=deal_id,
            old_data=dict(old_row),
        )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="この商談には関連する注文があるため削除できません。先に注文を削除してください。",
        )
    await invalidate_dashboard_cache(tenant_id)
