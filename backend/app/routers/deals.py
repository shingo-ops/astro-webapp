from __future__ import annotations

"""
案件管理API（CRUD）。

テナントスキーマの deals テーブルに対する操作を提供する。

変更履歴:
  2026-04-16: Phase 1拡張（deal_code, lead_id, stage, probability,
    currency, assigned_to, lost_reason 追加、require_permission統合）
  2026-04-27: Phase 1-B-2 Step 5d — 旧 customer_id 系統撤去
    （resolver / customer 経路廃止、company_id + contact_id を唯一の正に）
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


def _is_postgresql(db: AsyncSession) -> bool:
    """db の dialect が PostgreSQL 系か判定する (Issue #565)。

    pytest は SQLite (aiosqlite) で実行されるため、schema prefix を入れると
    "no such table: tenant_NNN.deals" で失敗する。本判定で SQLite 系を
    検出して prefix なしに倒す。
    """
    bind = db.get_bind() if hasattr(db, "get_bind") else None
    if bind is None:
        bind = getattr(db, "bind", None)
    name = getattr(getattr(bind, "dialect", None), "name", "") or ""
    return name.startswith("postgresql")


def _t(db: AsyncSession, tenant_id: int, name: str) -> str:
    """tenant スキーマ修飾テーブル参照を返す (Issue #565)。

    - PostgreSQL: `tenant_{id:03d}.{name}` (schema prefix 明示)
    - SQLite (pytest): `{name}` (schema 概念なし)

    AsyncSession の commit 後は新コネクションが払い出されて session-level
    の search_path が失われる可能性があるため、raw text() を使う箇所では
    schema prefix を明示するのが安全 (Issue #563 / #565)。
    """
    if _is_postgresql(db):
        safe_id = int(tenant_id)
        return f"tenant_{safe_id:03d}.{name}"
    return name


_DEAL_COLUMNS = """
    id, deal_code, company_id, contact_id, lead_id,
    title, amount, currency,
    status, stage, probability, lost_reason, assigned_to,
    expected_close_date, notes, created_at, updated_at
"""

_UPDATABLE_COLUMNS = {
    "company_id", "contact_id", "lead_id",
    "title", "amount", "currency",
    "status", "stage", "probability", "lost_reason", "assigned_to",
    "expected_close_date", "notes",
}


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
    company_id: int | None = Query(default=None),
    contact_id: int | None = Query(default=None),
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
    if company_id:
        conditions.append("company_id = :company_id")
        params["company_id"] = company_id
    if contact_id:
        conditions.append("contact_id = :contact_id")
        params["contact_id"] = contact_id
    if assigned_to:
        conditions.append("assigned_to = :assigned_to")
        params["assigned_to"] = assigned_to

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    deals_t = _t(db, tenant_id, "deals")
    result = await db.execute(
        text(f"""
            SELECT {_DEAL_COLUMNS}
            FROM {deals_t}
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
    deals_t = _t(db, tenant_id, "deals")
    result = await db.execute(
        text(f"SELECT {_DEAL_COLUMNS} FROM {deals_t} WHERE id = :id"),
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
    deals_t = _t(db, tenant_id, "deals")
    contacts_t = _t(db, tenant_id, "contacts")
    leads_t = _t(db, tenant_id, "leads")
    # Step 5d: contact / company の存在 + 所属一致確認のみ
    contact_check = await db.execute(
        text(f"SELECT company_id FROM {contacts_t} WHERE id = :id"),
        {"id": data.contact_id},
    )
    contact_row = contact_check.first()
    if not contact_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="指定された担当者が見つかりません")
    if contact_row[0] != data.company_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="指定された担当者は指定会社に所属していません",
        )

    # リード存在確認（指定時のみ）
    if data.lead_id is not None:
        lead_check = await db.execute(text(f"SELECT id FROM {leads_t} WHERE id = :id"), {"id": data.lead_id})
        if not lead_check.first():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="指定されたリードが見つかりません")

    result = await db.execute(
        text(f"""
            INSERT INTO {deals_t} (
                tenant_id, company_id, contact_id, lead_id,
                title, amount, currency,
                status, stage, probability, lost_reason, assigned_to,
                expected_close_date, notes
            )
            VALUES (
                :tenant_id, :company_id, :contact_id, :lead_id,
                :title, :amount, :currency,
                :status, :stage, :probability, :lost_reason, :assigned_to,
                :expected_close_date, :notes
            )
            RETURNING id
        """),
        {
            "tenant_id": tenant_id,
            "company_id": data.company_id,
            "contact_id": data.contact_id,
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
        text(f"UPDATE {deals_t} SET deal_code = :code WHERE id = :id"),
        {"code": f"DL-{new_id:05d}", "id": new_id},
    )

    fetched = await db.execute(
        text(f"SELECT {_DEAL_COLUMNS} FROM {deals_t} WHERE id = :id"),
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
    deals_t = _t(db, tenant_id, "deals")
    contacts_t = _t(db, tenant_id, "contacts")
    companies_t = _t(db, tenant_id, "companies")
    leads_t = _t(db, tenant_id, "leads")
    old_result = await db.execute(
        text(f"SELECT {_DEAL_COLUMNS} FROM {deals_t} WHERE id = :id"),
        {"id": deal_id},
    )
    old_row = old_result.mappings().first()
    if not old_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="商談が見つかりません")

    raw_update = data.model_dump(exclude_unset=True)
    update_data = {k: v for k, v in raw_update.items() if k in _UPDATABLE_COLUMNS}
    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="更新するフィールドを指定してください")

    # company_id / contact_id の整合性検証（Step 5d 以降）
    has_company_update = "company_id" in raw_update
    has_contact_update = "contact_id" in raw_update

    if has_company_update or has_contact_update:
        target_company_id = raw_update["company_id"] if has_company_update else old_row["company_id"]
        target_contact_id = raw_update["contact_id"] if has_contact_update else old_row["contact_id"]

        if target_contact_id is not None:
            contact_check = await db.execute(
                text(f"SELECT company_id FROM {contacts_t} WHERE id = :id"),
                {"id": target_contact_id},
            )
            contact_row = contact_check.first()
            if not contact_row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="指定された担当者が見つかりません",
                )
            if target_company_id is not None and contact_row[0] != target_company_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="指定された担当者は指定会社に所属していません",
                )
            # company_id を明示更新せず contact のみ更新 → contact 側の company_id を採用
            if target_company_id is None and contact_row[0] is not None:
                update_data["company_id"] = contact_row[0]

        elif target_company_id is not None and has_company_update:
            company_check = await db.execute(
                text(f"SELECT id FROM {companies_t} WHERE id = :id"),
                {"id": target_company_id},
            )
            if not company_check.first():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="指定された会社が見つかりません",
                )

    # lead_id を更新する場合は存在確認（指定された場合のみ、NULL クリアは許容）
    if "lead_id" in raw_update and raw_update["lead_id"] is not None:
        lead_check = await db.execute(
            text(f"SELECT id FROM {leads_t} WHERE id = :id"),
            {"id": raw_update["lead_id"]},
        )
        if not lead_check.first():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="指定されたリードが見つかりません",
            )

    # Enum型の値を文字列に変換
    for key in ("status", "stage", "currency"):
        if key in update_data and update_data[key] is not None:
            update_data[key] = update_data[key].value

    set_clauses = ", ".join(f"{k} = :{k}" for k in update_data)
    update_data["id"] = deal_id

    result = await db.execute(
        text(f"""
            UPDATE {deals_t} SET {set_clauses}, updated_at = NOW()
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
    deals_t = _t(db, tenant_id, "deals")
    old_result = await db.execute(
        text(f"SELECT {_DEAL_COLUMNS} FROM {deals_t} WHERE id = :id"),
        {"id": deal_id},
    )
    old_row = old_result.mappings().first()
    if not old_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="商談が見つかりません")

    try:
        await db.execute(text(f"DELETE FROM {deals_t} WHERE id = :id"), {"id": deal_id})
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
