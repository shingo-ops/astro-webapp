from __future__ import annotations

"""
見積もり管理API。

見積ヘッダー + 明細（quote_items）の一括管理。
ステータス遷移: draft → sent → approved/rejected → expired
承認済み見積もりは POST /invoices/from-quote/{id} で請求書に変換可能。

変更履歴:
  2026-04-17: 初版作成（Phase 2）
"""

from datetime import date, timedelta
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
from app.schemas.quote import (
    QuoteCreate,
    QuoteDetailResponse,
    QuoteItemResponse,
    QuoteResponse,
    QuoteUpdate,
)
from app.services.audit import record_audit_log

router = APIRouter()

_QUOTE_COLUMNS = """
    id, quote_code, deal_id, customer_id, company_id, contact_id, currency,
    subtotal, shipping_fee, tax_amount, total_amount,
    status, validity_date, shipping_country, shipping_carrier,
    delivery_info, pdf_url, notes, created_by,
    created_at, updated_at
"""

_UPDATABLE_COLUMNS = {
    "currency", "shipping_fee", "tax_amount",
    "shipping_country", "shipping_carrier", "delivery_info", "notes",
}


async def _get_quote_items(db: AsyncSession, quote_id: int) -> list[dict]:
    result = await db.execute(
        text("""
            SELECT id, product_id, product_name, quantity, unit_price,
                   weight, subtotal, sort_order
            FROM quote_items WHERE quote_id = :qid ORDER BY sort_order, id
        """),
        {"qid": quote_id},
    )
    return [dict(row) for row in result.mappings().all()]


@router.get(
    "/quotes",
    response_model=list[QuoteResponse],
    dependencies=[Depends(require_permission("quotes.view"))],
)
async def list_quotes(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    status_filter: str | None = Query(default=None, alias="status"),
    customer_id: int | None = Query(default=None),
    company_id: int | None = Query(default=None),
    contact_id: int | None = Query(default=None),
    deal_id: int | None = Query(default=None),
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
    if customer_id:
        conditions.append("customer_id = :cid")
        params["cid"] = customer_id
    # Phase 1-B-2 Step 5b-2: 新モデル filter
    if company_id:
        conditions.append("company_id = :company_id")
        params["company_id"] = company_id
    if contact_id:
        conditions.append("contact_id = :contact_id")
        params["contact_id"] = contact_id
    if deal_id:
        conditions.append("deal_id = :did")
        params["did"] = deal_id

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    result = await db.execute(
        text(f"SELECT {_QUOTE_COLUMNS} FROM quotes {where} ORDER BY updated_at DESC LIMIT :limit OFFSET :offset"),
        params,
    )
    return [QuoteResponse(**row) for row in result.mappings().all()]


@router.get(
    "/quotes/{quote_id}",
    response_model=QuoteDetailResponse,
    dependencies=[Depends(require_permission("quotes.view"))],
)
async def get_quote(
    quote_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        text(f"SELECT {_QUOTE_COLUMNS} FROM quotes WHERE id = :id"),
        {"id": quote_id},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="見積もりが見つかりません")

    items = await _get_quote_items(db, quote_id)
    return QuoteDetailResponse(**dict(row), items=[QuoteItemResponse(**i) for i in items])


@router.post(
    "/quotes",
    response_model=QuoteDetailResponse,
    status_code=201,
    dependencies=[Depends(require_permission("quotes.create"))],
)
async def create_quote(
    data: QuoteCreate,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """見積もりを作成する（明細を含む一括登録）"""
    # 顧客存在確認
    cust = await db.execute(text("SELECT id FROM customers WHERE id = :id"), {"id": data.customer_id})
    if not cust.first():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="指定された顧客が見つかりません")

    # Phase 1-B-2 Step 5b-2: company_id/contact_id 指定時の存在確認
    # 両方指定時は contact が company に所属しているかも検証（reviewer Major 1 対応）
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

    # 案件存在確認（指定時のみ）
    if data.deal_id:
        deal = await db.execute(text("SELECT id FROM deals WHERE id = :id"), {"id": data.deal_id})
        if not deal.first():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="指定された案件が見つかりません")

    # 小計計算
    subtotal = sum(item.quantity * item.unit_price for item in data.items)
    shipping = data.shipping_fee or Decimal(0)
    tax = data.tax_amount or Decimal(0)
    total = subtotal + shipping + tax
    validity = date.today() + timedelta(days=data.validity_days)

    # ヘッダー作成
    header_result = await db.execute(
        text("""
            INSERT INTO quotes (
                tenant_id, deal_id, customer_id, company_id, contact_id, currency,
                subtotal, shipping_fee, tax_amount, total_amount,
                status, validity_date, shipping_country, shipping_carrier,
                delivery_info, notes, created_by
            ) VALUES (
                :tid, :did, :cid, :company_id, :contact_id, :currency,
                :subtotal, :shipping, :tax, :total,
                'draft', :validity, :country, :carrier,
                :delivery, :notes, :created_by
            ) RETURNING id
        """),
        {
            "tid": tenant_id, "did": data.deal_id, "cid": data.customer_id,
            "company_id": data.company_id, "contact_id": data.contact_id,
            "currency": data.currency, "subtotal": subtotal, "shipping": shipping,
            "tax": tax, "total": total, "validity": validity,
            "country": data.shipping_country, "carrier": data.shipping_carrier,
            "delivery": data.delivery_info, "notes": data.notes,
            "created_by": current_user.id,
        },
    )
    quote_id = header_result.scalar_one()

    # quote_code 自動採番
    await db.execute(
        text("UPDATE quotes SET quote_code = :code WHERE id = :id"),
        {"code": f"QT-{quote_id:05d}", "id": quote_id},
    )

    # 明細行の作成
    for i, item in enumerate(data.items):
        line_subtotal = item.quantity * item.unit_price
        await db.execute(
            text("""
                INSERT INTO quote_items (quote_id, product_id, product_name, quantity, unit_price, weight, subtotal, sort_order)
                VALUES (:qid, :pid, :pname, :qty, :price, :weight, :sub, :sort)
            """),
            {
                "qid": quote_id, "pid": item.product_id, "pname": item.product_name,
                "qty": item.quantity, "price": item.unit_price, "weight": item.weight,
                "sub": line_subtotal, "sort": i,
            },
        )

    await record_audit_log(
        db=db, tenant_id=tenant_id, user_id=current_user.id,
        action="create", table_name="quotes", record_id=quote_id,
        new_data={"customer_id": data.customer_id, "items_count": len(data.items), "total": str(total)},
    )
    await db.commit()
    await invalidate_dashboard_cache(tenant_id)

    # commit後にsearch_path再設定
    await reset_tenant_context(db, tenant_id)

    # 結果取得
    fetched = await db.execute(text(f"SELECT {_QUOTE_COLUMNS} FROM quotes WHERE id = :id"), {"id": quote_id})
    row = fetched.mappings().first()
    items = await _get_quote_items(db, quote_id)
    return QuoteDetailResponse(**dict(row), items=[QuoteItemResponse(**i) for i in items])


@router.patch(
    "/quotes/{quote_id}",
    response_model=QuoteResponse,
    dependencies=[Depends(require_permission("quotes.update"))],
)
async def update_quote(
    quote_id: int,
    data: QuoteUpdate,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """見積もりヘッダーを更新する（draft/sent のみ編集可）"""
    old_result = await db.execute(text(f"SELECT {_QUOTE_COLUMNS} FROM quotes WHERE id = :id"), {"id": quote_id})
    old_row = old_result.mappings().first()
    if not old_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="見積もりが見つかりません")
    if old_row["status"] in ("approved", "rejected", "expired"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"ステータス「{old_row['status']}」の見積もりは編集できません")

    update_data = data.model_dump(exclude_unset=True)
    update_data = {k: v for k, v in update_data.items() if k in _UPDATABLE_COLUMNS}
    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="更新するフィールドを指定してください")

    # shipping_fee/tax_amount が変わった場合は total を再計算
    new_shipping = update_data.get("shipping_fee", old_row["shipping_fee"]) or Decimal(0)
    new_tax = update_data.get("tax_amount", old_row["tax_amount"]) or Decimal(0)
    update_data["total_amount"] = (old_row["subtotal"] or Decimal(0)) + new_shipping + new_tax

    set_clauses = ", ".join(f"{k} = :{k}" for k in update_data)
    update_data["id"] = quote_id

    result = await db.execute(
        text(f"UPDATE quotes SET {set_clauses}, updated_at = NOW() WHERE id = :id RETURNING {_QUOTE_COLUMNS}"),
        update_data,
    )
    row = result.mappings().first()

    await record_audit_log(
        db=db, tenant_id=tenant_id, user_id=current_user.id,
        action="update", table_name="quotes", record_id=quote_id,
        old_data=dict(old_row), new_data=update_data,
    )
    await db.commit()
    await invalidate_dashboard_cache(tenant_id)
    return QuoteResponse(**dict(row))


@router.post(
    "/quotes/{quote_id}/send",
    response_model=QuoteResponse,
    dependencies=[Depends(require_permission("quotes.update"))],
)
async def send_quote(
    quote_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """見積もりを送付済みにする（draft → sent）"""
    result = await db.execute(
        text(f"UPDATE quotes SET status = 'sent', updated_at = NOW() WHERE id = :id AND status = 'draft' RETURNING {_QUOTE_COLUMNS}"),
        {"id": quote_id},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="draft状態の見積もりのみ送付できます")

    await record_audit_log(db=db, tenant_id=tenant_id, user_id=current_user.id,
                           action="send", table_name="quotes", record_id=quote_id,
                           new_data={"status": "sent"})
    await db.commit()
    return QuoteResponse(**dict(row))


@router.post(
    "/quotes/{quote_id}/approve",
    response_model=QuoteResponse,
    dependencies=[Depends(require_permission("quotes.approve"))],
)
async def approve_quote(
    quote_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """見積もりを承認する（sent → approved）"""
    result = await db.execute(
        text(f"UPDATE quotes SET status = 'approved', updated_at = NOW() WHERE id = :id AND status = 'sent' RETURNING {_QUOTE_COLUMNS}"),
        {"id": quote_id},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="sent状態の見積もりのみ承認できます")

    await record_audit_log(db=db, tenant_id=tenant_id, user_id=current_user.id,
                           action="approve", table_name="quotes", record_id=quote_id,
                           new_data={"status": "approved"})
    await db.commit()
    await invalidate_dashboard_cache(tenant_id)
    return QuoteResponse(**dict(row))


@router.post(
    "/quotes/{quote_id}/reject",
    response_model=QuoteResponse,
    dependencies=[Depends(require_permission("quotes.approve"))],
)
async def reject_quote(
    quote_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """見積もりを却下する（sent → rejected）"""
    result = await db.execute(
        text(f"UPDATE quotes SET status = 'rejected', updated_at = NOW() WHERE id = :id AND status = 'sent' RETURNING {_QUOTE_COLUMNS}"),
        {"id": quote_id},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="sent状態の見積もりのみ却下できます")

    await record_audit_log(db=db, tenant_id=tenant_id, user_id=current_user.id,
                           action="reject", table_name="quotes", record_id=quote_id,
                           new_data={"status": "rejected"})
    await db.commit()
    return QuoteResponse(**dict(row))


@router.delete(
    "/quotes/{quote_id}",
    status_code=204,
    dependencies=[Depends(require_permission("quotes.delete"))],
)
async def delete_quote(
    quote_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """見積もりを削除する（draft のみ削除可、それ以外は 400）"""
    old = await db.execute(text(f"SELECT {_QUOTE_COLUMNS} FROM quotes WHERE id = :id"), {"id": quote_id})
    old_row = old.mappings().first()
    if not old_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="見積もりが見つかりません")
    if old_row["status"] != "draft":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="draft状態の見積もりのみ削除できます")

    await db.execute(text("DELETE FROM quotes WHERE id = :id"), {"id": quote_id})
    await record_audit_log(db=db, tenant_id=tenant_id, user_id=current_user.id,
                           action="delete", table_name="quotes", record_id=quote_id,
                           old_data=dict(old_row))
    await db.commit()
    await invalidate_dashboard_cache(tenant_id)
