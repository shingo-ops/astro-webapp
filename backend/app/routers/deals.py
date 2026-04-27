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
from app.services.customer_resolver import resolve_customer_id

router = APIRouter()

_DEAL_COLUMNS = """
    id, deal_code, customer_id, company_id, contact_id, lead_id,
    title, amount, currency,
    status, stage, probability, lost_reason, assigned_to,
    expected_close_date, notes, created_at, updated_at
"""

_UPDATABLE_COLUMNS = {
    "customer_id", "company_id", "contact_id", "lead_id",
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
    customer_id: int | None = Query(default=None),
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
    if customer_id:
        conditions.append("customer_id = :customer_id")
        params["customer_id"] = customer_id
    # Phase 1-B-2 Step 5b-2: 新モデルの filter
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
    # Phase 1-B-2 Step 5c-3: customer_id 未指定時は (contact_id) から逆引き。
    # 同時に contacts/companies の存在確認と所属一致検証も resolver 内で完了する。
    customer_id = data.customer_id
    if customer_id is None:
        customer_id = await resolve_customer_id(db, data.contact_id, data.company_id)  # type: ignore[arg-type]
    else:
        # 旧経路: customer_id 指定時の存在確認（別テナントは search_path で不可視 → 404）
        cust = await db.execute(text("SELECT id FROM customers WHERE id = :id"), {"id": customer_id})
        if not cust.first():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="指定された顧客が見つかりません")
        # company_id/contact_id を併送した場合は整合性確認（Step 5b-2 互換）
        if data.contact_id is not None:
            contact_check = await db.execute(
                text("SELECT company_id FROM contacts WHERE id = :id"),
                {"id": data.contact_id},
            )
            contact_row = contact_check.first()
            if not contact_row:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="指定された担当者が見つかりません")
            if data.company_id is not None and contact_row[0] != data.company_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="指定された担当者は指定会社に所属していません",
                )
        elif data.company_id is not None:
            company_check = await db.execute(text("SELECT id FROM companies WHERE id = :id"), {"id": data.company_id})
            if not company_check.first():
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="指定された会社が見つかりません")

    # リード存在確認（指定時のみ）
    if data.lead_id is not None:
        lead_check = await db.execute(text("SELECT id FROM leads WHERE id = :id"), {"id": data.lead_id})
        if not lead_check.first():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="指定されたリードが見つかりません")

    result = await db.execute(
        text("""
            INSERT INTO deals (
                tenant_id, customer_id, company_id, contact_id, lead_id,
                title, amount, currency,
                status, stage, probability, lost_reason, assigned_to,
                expected_close_date, notes
            )
            VALUES (
                :tenant_id, :customer_id, :company_id, :contact_id, :lead_id,
                :title, :amount, :currency,
                :status, :stage, :probability, :lost_reason, :assigned_to,
                :expected_close_date, :notes
            )
            RETURNING id
        """),
        {
            "tenant_id": tenant_id,
            "customer_id": customer_id,
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

    raw_update = data.model_dump(exclude_unset=True)
    update_data = {k: v for k, v in raw_update.items() if k in _UPDATABLE_COLUMNS}
    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="更新するフィールドを指定してください")

    # Phase 1-B-2 Step 5c-3 (PR #147 review F1):
    # PATCH 経路でも company_id / contact_id / customer_id の整合性を検証する。
    # create_deal と同等のチェックを行い、不整合な書き換えで customer_id ↔ company_id/contact_id
    # の食い違いを生まないようにする。Step 5d で customer_id 列が drop されると本ブロックは不要になる。
    has_company_update = "company_id" in raw_update
    has_contact_update = "contact_id" in raw_update
    has_customer_update = "customer_id" in raw_update

    if has_company_update or has_contact_update or has_customer_update:
        # 更新後に成立する想定の (company_id, contact_id, customer_id) を計算
        target_company_id = raw_update["company_id"] if has_company_update else old_row["company_id"]
        target_contact_id = raw_update["contact_id"] if has_contact_update else old_row["contact_id"]

        # contact_id が NULL でない場合: 存在 + 当該テナント + company 所属を確認
        if target_contact_id is not None:
            contact_check = await db.execute(
                text("SELECT company_id FROM contacts WHERE id = :id"),
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
            # 明示的に company_id を更新しなかったが、contact 側が別 company に紐付いていた場合は
            # contact.company_id を採用する（deal レベルでの不整合を避ける）
            if target_company_id is None and contact_row[0] is not None:
                update_data["company_id"] = contact_row[0]
                target_company_id = contact_row[0]

        # company_id のみ更新するケース（contact_id 未指定）でも会社の存在検証は行う
        elif target_company_id is not None and has_company_update:
            company_check = await db.execute(
                text("SELECT id FROM companies WHERE id = :id"),
                {"id": target_company_id},
            )
            if not company_check.first():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="指定された会社が見つかりません",
                )

        # customer_id を明示指定した場合は存在確認（テナント外は search_path で不可視 → 404）。
        # PR #147 review N4: ここで意図的に「customer_id ↔ company_id/contact_id」の整合性
        # 検証はスキップしている。理由は次の 2 つ:
        #   (a) Step 5c-3 時点では旧 API クライアント互換のため、明示送信された customer_id は
        #       「呼び出し元が責任を持って正しい値を送っている」前提で受け入れる（旧経路互換）。
        #   (b) 現在 frontend (DealsPage.handleSubmit) は edit 経路で customer_id を送信しない
        #       ため、本ブランチに到達するのは外部 API クライアント / プログラマティック PATCH 経由のみ。
        # Step 5d で customer_id 列が drop されればこのスキップ経路は永久に消える。
        # 厳密化したい場合は has_customer_update and has_contact_update のときだけ
        # resolver で逆引きして update_data["customer_id"] != resolved なら 400 にする手もある。
        if has_customer_update and update_data.get("customer_id") is not None:
            cust_check = await db.execute(
                text("SELECT id FROM customers WHERE id = :id"),
                {"id": update_data["customer_id"]},
            )
            if not cust_check.first():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="指定された顧客が見つかりません",
                )
        else:
            # customer_id が明示指定されていない & contact_id が変わる場合は resolver で再解決して書き戻す。
            # これにより Step 5d 直前まで customer_id が deal の company/contact と一貫した値を保つ。
            if has_contact_update and target_contact_id is not None and target_contact_id != old_row["contact_id"]:
                resolved = await resolve_customer_id(db, target_contact_id, target_company_id)
                update_data["customer_id"] = resolved

    # lead_id を更新する場合は存在確認（指定された場合のみ、NULL クリアは許容）
    if "lead_id" in raw_update and raw_update["lead_id"] is not None:
        lead_check = await db.execute(
            text("SELECT id FROM leads WHERE id = :id"),
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
