from __future__ import annotations

"""
案件管理API（CRUD）。

テナントスキーマの deals テーブルに対する操作を提供する。

変更履歴:
  2026-04-16: Phase 1拡張（deal_code, lead_id, stage, probability,
    currency, assigned_to, lost_reason 追加、require_permission統合）
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, get_current_tenant, require_permission
from app.cache import invalidate_dashboard_cache
from app.database import get_db
from app.models import User
from app.schemas.deal import DealCreate, DealUpdate, DealResponse
from app.services.audit import record_audit_log

router = APIRouter()

_DEAL_COLUMNS = """
    id, deal_code, customer_id, lead_id, title, amount, currency,
    status, stage, probability, lost_reason, assigned_to,
    expected_close_date, notes, created_at, updated_at
"""


@router.get(
    "/deals",
    response_model=list[DealResponse],
    dependencies=[Depends(require_permission("deals.view"))],
)
async def list_deals(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    status_filter: str | None = Query(default=None, alias="status"),
    stage: str | None = Query(default=None),
    customer_id: int | None = Query(default=None),
    assigned_to: int | None = Query(default=None),
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
    if stage:
        conditions.append("stage = :stage")
        params["stage"] = stage
    if customer_id:
        conditions.append("customer_id = :customer_id")
        params["customer_id"] = customer_id
    if assigned_to:
        conditions.append("assigned_to = :assigned_to")
        params["assigned_to"] = assigned_to

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    result = await db.execute(
        text(f"""
            SELECT {_DEAL_COLUMNS}
            FROM deals
            {where_clause}
            ORDER BY updated_at DESC
            LIMIT :limit OFFSET :offset
        """),
        params,
    )
    rows = result.mappings().all()
    return [DealResponse(**row) for row in rows]


@router.get(
    "/deals/{deal_id}",
    response_model=DealResponse,
    dependencies=[Depends(require_permission("deals.view"))],
)
async def get_deal(
    deal_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """商談詳細を取得する"""
    result = await db.execute(
        text(f"SELECT {_DEAL_COLUMNS} FROM deals WHERE id = :id"),
        {"id": deal_id},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="商談が見つかりません")
    return DealResponse(**row)


@router.post(
    "/deals",
    response_model=DealResponse,
    status_code=201,
    dependencies=[Depends(require_permission("deals.create"))],
)
async def create_deal(
    data: DealCreate,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """商談を登録する（deal_codeは自動採番）"""
    # 顧客の存在確認
    cust = await db.execute(text("SELECT id FROM customers WHERE id = :id"), {"id": data.customer_id})
    if not cust.first():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="指定された顧客が存在しません")

    # リード存在確認（指定時のみ）
    if data.lead_id is not None:
        lead_check = await db.execute(text("SELECT id FROM leads WHERE id = :id"), {"id": data.lead_id})
        if not lead_check.first():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="指定されたリードが存在しません")

    result = await db.execute(
        text("""
            INSERT INTO deals (
                tenant_id, customer_id, lead_id, title, amount, currency,
                status, stage, probability, lost_reason, assigned_to,
                expected_close_date, notes
            )
            VALUES (
                :tenant_id, :customer_id, :lead_id, :title, :amount, :currency,
                :status, :stage, :probability, :lost_reason, :assigned_to,
                :expected_close_date, :notes
            )
            RETURNING id
        """),
        {
            "tenant_id": tenant_id,
            "customer_id": data.customer_id,
            "lead_id": data.lead_id,
            "title": data.title,
            "amount": data.amount,
            "currency": data.currency.value,
            "status": data.status.value,
            "stage": data.stage.value,
            "probability": data.probability,
            "lost_reason": data.lost_reason,
            "assigned_to": data.assigned_to,
            "expected_close_date": data.expected_close_date,
            "notes": data.notes,
        },
    )
    new_id = result.scalar_one()

    # deal_code = DL-00001 形式で自動採番（Python側で生成してDB非依存）
    await db.execute(
        text("UPDATE deals SET deal_code = :code WHERE id = :id"),
        {"code": f"DL-{new_id:05d}", "id": new_id},
    )

    fetched = await db.execute(
        text(f"SELECT {_DEAL_COLUMNS} FROM deals WHERE id = :id"),
        {"id": new_id},
    )
    row = fetched.mappings().first()

    await record_audit_log(
        db=db, tenant_id=tenant_id, user_id=current_user.id,
        action="create", table_name="deals", record_id=new_id,
        new_data=data.model_dump(exclude_none=True, mode="json"),
    )
    await db.commit()
    await invalidate_dashboard_cache(tenant_id)

    return DealResponse(**row)


@router.patch(
    "/deals/{deal_id}",
    response_model=DealResponse,
    dependencies=[Depends(require_permission("deals.update"))],
)
async def update_deal(
    deal_id: int,
    data: DealUpdate,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """商談情報を更新する（部分更新）"""
    old_result = await db.execute(
        text(f"SELECT {_DEAL_COLUMNS} FROM deals WHERE id = :id"),
        {"id": deal_id},
    )
    old_row = old_result.mappings().first()
    if not old_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="商談が見つかりません")

    update_data = data.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="更新するフィールドを指定してください")

    # Enum型の値を文字列に変換
    for key in ("status", "stage", "currency"):
        if key in update_data and update_data[key] is not None:
            update_data[key] = update_data[key].value

    set_clauses = ", ".join(f"{k} = :{k}" for k in update_data)
    update_data["id"] = deal_id

    result = await db.execute(
        text(f"""
            UPDATE deals SET {set_clauses}, updated_at = NOW()
            WHERE id = :id
            RETURNING {_DEAL_COLUMNS}
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


@router.delete(
    "/deals/{deal_id}",
    status_code=204,
    dependencies=[Depends(require_permission("deals.delete"))],
)
async def delete_deal(
    deal_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """商談を削除する"""
    old_result = await db.execute(
        text(f"SELECT {_DEAL_COLUMNS} FROM deals WHERE id = :id"),
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
