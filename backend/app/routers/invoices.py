from __future__ import annotations

"""
請求書管理API。

見積もりからの変換 or 直接作成。多通貨対応（為替レート記録）。
枝番（branch_number）で修正版を追跡。void/revision フロー。

変更履歴:
  2026-04-17: 初版作成（Phase 2）
  2026-04-27: Phase 1-B-2 Step 5d — 旧 customer_id 系統撤去
    （customer 経路廃止、company_id + contact_id を唯一の正に）
"""

import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import (
    get_current_tenant,
    get_current_user,
    require_permission,
    reset_tenant_context,
)
from app.cache import invalidate_dashboard_cache
from app.database import get_db
from app.models import User
from app.schemas.invoice import (
    InvoiceCreate,
    InvoiceDetailResponse,
    InvoiceItemResponse,
    InvoiceResponse,
    InvoiceUpdate,
    VoidRequest,
)
from app.services.audit import record_audit_log

router = APIRouter()

_INVOICE_COLUMNS = """
    id, invoice_number, quote_id, company_id, contact_id, currency,
    subtotal, shipping_fee, tax_amount, total_amount,
    exchange_rate_jpy, exchange_rate_usd, amount_jpy, amount_usd,
    payment_method, status, branch_number,
    pdf_url, erp_key,
    issued_at, due_date, paid_at, voided_at, void_reason,
    notes, created_by, created_at, updated_at
"""

_UPDATABLE_COLUMNS = {"payment_method", "due_date", "exchange_rate_jpy", "exchange_rate_usd", "notes"}


async def _get_invoice_items(db: AsyncSession, invoice_id: int) -> list[dict]:
    result = await db.execute(
        text("""
            SELECT id, product_id, product_name, quantity, unit_price,
                   weight, subtotal, sort_order
            FROM invoice_items WHERE invoice_id = :iid ORDER BY sort_order, id
        """),
        {"iid": invoice_id},
    )
    return [dict(row) for row in result.mappings().all()]


def _calc_currency_amounts(total: Decimal, currency: str,
                           rate_jpy: Decimal | None, rate_usd: Decimal | None) -> tuple[Decimal | None, Decimal | None]:
    """通貨換算額を算出。"""
    amount_jpy = None
    amount_usd = None
    if currency == "JPY":
        amount_jpy = total
        if rate_usd and rate_usd > 0:
            amount_usd = round(total / rate_usd, 2)
    elif currency == "USD":
        amount_usd = total
        if rate_jpy:
            amount_jpy = round(total * rate_jpy, 2)
    elif currency == "EUR":
        if rate_jpy:
            amount_jpy = round(total * rate_jpy, 2)
        if rate_usd:
            amount_usd = round(total * rate_usd, 2)
    return amount_jpy, amount_usd


@router.get(
    "/invoices",
    response_model=list[InvoiceResponse],
    dependencies=[Depends(require_permission("invoices.view"))],
)
async def list_invoices(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    status_filter: str | None = Query(default=None, alias="status"),
    company_id: int | None = Query(default=None),
    contact_id: int | None = Query(default=None),
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
    if company_id:
        conditions.append("company_id = :company_id")
        params["company_id"] = company_id
    if contact_id:
        conditions.append("contact_id = :contact_id")
        params["contact_id"] = contact_id
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    result = await db.execute(
        text(f"SELECT {_INVOICE_COLUMNS} FROM invoices {where} ORDER BY updated_at DESC LIMIT :limit OFFSET :offset"),
        params,
    )
    return [InvoiceResponse(**row) for row in result.mappings().all()]


@router.get(
    "/invoices/{invoice_id}",
    response_model=InvoiceDetailResponse,
    dependencies=[Depends(require_permission("invoices.view"))],
)
async def get_invoice(
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(text(f"SELECT {_INVOICE_COLUMNS} FROM invoices WHERE id = :id"), {"id": invoice_id})
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="請求書が見つかりません")
    items = await _get_invoice_items(db, invoice_id)
    return InvoiceDetailResponse(**dict(row), items=[InvoiceItemResponse(**i) for i in items])


@router.post(
    "/invoices/from-quote/{quote_id}",
    response_model=InvoiceDetailResponse,
    status_code=201,
    dependencies=[Depends(require_permission("invoices.create"))],
)
async def create_invoice_from_quote(
    quote_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """承認済み見積もりから請求書を作成する（atomic変換）"""
    # アトミック性: 見積もりステータスをSELECT FOR UPDATEで排他ロックし、
    # 並行変換を防止。全操作が同一トランザクション内で完結する。
    quote = await db.execute(
        text("SELECT * FROM quotes WHERE id = :id FOR UPDATE"),
        {"id": quote_id},
    )
    q = quote.mappings().first()
    if not q:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="見積もりが見つかりません")
    if q["status"] != "approved":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="承認済みの見積もりのみ請求書に変換できます")

    # 請求番号生成
    max_result = await db.execute(text("SELECT COALESCE(MAX(id), 0) + 1 AS next_id FROM invoices"))
    next_id = max_result.scalar()
    invoice_number = f"IN-{next_id:04d}-01"
    erp_key = str(uuid.uuid4())[:8].upper()

    # 請求書ヘッダー作成（Step 5d: quote から company_id/contact_id を継承）
    inv_result = await db.execute(
        text("""
            INSERT INTO invoices (
                tenant_id, invoice_number, quote_id, company_id, contact_id, currency,
                subtotal, shipping_fee, tax_amount, total_amount,
                payment_method, status, branch_number, erp_key, notes, created_by
            ) VALUES (
                :tid, :inv_num, :qid, :company_id, :contact_id, :currency,
                :subtotal, :shipping, :tax, :total,
                NULL, 'draft', 1, :erp_key, :notes, :created_by
            ) RETURNING id
        """),
        {
            "tid": tenant_id, "inv_num": invoice_number, "qid": quote_id,
            "company_id": q.get("company_id"), "contact_id": q.get("contact_id"),
            "currency": q["currency"],
            "subtotal": q["subtotal"], "shipping": q["shipping_fee"],
            "tax": q["tax_amount"], "total": q["total_amount"],
            "erp_key": erp_key, "notes": q["notes"], "created_by": current_user.id,
        },
    )
    invoice_id = inv_result.scalar_one()

    # 見積明細をコピー
    quote_items = await db.execute(
        text("SELECT product_id, product_name, quantity, unit_price, weight, subtotal, sort_order FROM quote_items WHERE quote_id = :qid ORDER BY sort_order"),
        {"qid": quote_id},
    )
    for item in quote_items.mappings().all():
        await db.execute(
            text("""
                INSERT INTO invoice_items (invoice_id, product_id, product_name, quantity, unit_price, weight, subtotal, sort_order)
                VALUES (:iid, :pid, :pname, :qty, :price, :weight, :sub, :sort)
            """),
            {"iid": invoice_id, **dict(item)},
        )

    await record_audit_log(
        db=db, tenant_id=tenant_id, user_id=current_user.id,
        action="create_from_quote", table_name="invoices", record_id=invoice_id,
        new_data={"quote_id": quote_id, "invoice_number": invoice_number},
    )
    await db.commit()
    await reset_tenant_context(db, tenant_id)  # ADR-072 Phase 2.5
    await invalidate_dashboard_cache(tenant_id)

    fetched = await db.execute(text(f"SELECT {_INVOICE_COLUMNS} FROM invoices WHERE id = :id"), {"id": invoice_id})
    row = fetched.mappings().first()
    items = await _get_invoice_items(db, invoice_id)
    return InvoiceDetailResponse(**dict(row), items=[InvoiceItemResponse(**i) for i in items])


@router.post(
    "/invoices",
    response_model=InvoiceDetailResponse,
    status_code=201,
    dependencies=[Depends(require_permission("invoices.create"))],
)
async def create_invoice(
    data: InvoiceCreate,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """請求書を直接作成する（見積もりを経由しない場合）"""
    # Step 5d: contact / company の存在 + 所属一致確認のみ
    contact_check = await db.execute(
        text("SELECT company_id FROM contacts WHERE id = :id"),
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

    subtotal = sum(item.quantity * item.unit_price for item in data.items)
    shipping = data.shipping_fee or Decimal(0)
    tax = data.tax_amount or Decimal(0)
    total = subtotal + shipping + tax
    amount_jpy, amount_usd = _calc_currency_amounts(total, data.currency, data.exchange_rate_jpy, data.exchange_rate_usd)

    max_result = await db.execute(text("SELECT COALESCE(MAX(id), 0) + 1 AS next_id FROM invoices"))
    next_id = max_result.scalar()
    invoice_number = f"IN-{next_id:04d}-01"
    erp_key = str(uuid.uuid4())[:8].upper()

    inv_result = await db.execute(
        text("""
            INSERT INTO invoices (
                tenant_id, invoice_number, company_id, contact_id, currency,
                subtotal, shipping_fee, tax_amount, total_amount,
                exchange_rate_jpy, exchange_rate_usd, amount_jpy, amount_usd,
                payment_method, status, branch_number, erp_key,
                due_date, notes, created_by
            ) VALUES (
                :tid, :inv_num, :company_id, :contact_id, :currency,
                :subtotal, :shipping, :tax, :total,
                :rate_jpy, :rate_usd, :amt_jpy, :amt_usd,
                :payment, 'draft', 1, :erp_key,
                :due_date, :notes, :created_by
            ) RETURNING id
        """),
        {
            "tid": tenant_id, "inv_num": invoice_number,
            "company_id": data.company_id, "contact_id": data.contact_id,
            "currency": data.currency, "subtotal": subtotal, "shipping": shipping,
            "tax": tax, "total": total, "rate_jpy": data.exchange_rate_jpy,
            "rate_usd": data.exchange_rate_usd, "amt_jpy": amount_jpy, "amt_usd": amount_usd,
            "payment": data.payment_method, "erp_key": erp_key,
            "due_date": data.due_date, "notes": data.notes, "created_by": current_user.id,
        },
    )
    invoice_id = inv_result.scalar_one()

    for i, item in enumerate(data.items):
        line_subtotal = item.quantity * item.unit_price
        await db.execute(
            text("""
                INSERT INTO invoice_items (invoice_id, product_id, product_name, quantity, unit_price, weight, subtotal, sort_order)
                VALUES (:iid, :pid, :pname, :qty, :price, :weight, :sub, :sort)
            """),
            {
                "iid": invoice_id, "pid": item.product_id, "pname": item.product_name,
                "qty": item.quantity, "price": item.unit_price, "weight": item.weight,
                "sub": line_subtotal, "sort": i,
            },
        )

    await record_audit_log(
        db=db, tenant_id=tenant_id, user_id=current_user.id,
        action="create", table_name="invoices", record_id=invoice_id,
        new_data={
            "company_id": data.company_id,
            "contact_id": data.contact_id,
            "invoice_number": invoice_number,
            "total": str(total),
        },
    )
    await db.commit()
    await reset_tenant_context(db, tenant_id)  # ADR-072 Phase 2.5
    await invalidate_dashboard_cache(tenant_id)

    fetched = await db.execute(text(f"SELECT {_INVOICE_COLUMNS} FROM invoices WHERE id = :id"), {"id": invoice_id})
    row = fetched.mappings().first()
    items = await _get_invoice_items(db, invoice_id)
    return InvoiceDetailResponse(**dict(row), items=[InvoiceItemResponse(**i) for i in items])


@router.patch(
    "/invoices/{invoice_id}",
    response_model=InvoiceResponse,
    dependencies=[Depends(require_permission("invoices.update"))],
)
async def update_invoice(
    invoice_id: int,
    data: InvoiceUpdate,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """請求書ヘッダーを更新する（draft のみ編集可）"""
    old = await db.execute(text(f"SELECT {_INVOICE_COLUMNS} FROM invoices WHERE id = :id"), {"id": invoice_id})
    old_row = old.mappings().first()
    if not old_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="請求書が見つかりません")
    if old_row["status"] != "draft":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="draft状態の請求書のみ編集できます")

    update_data = data.model_dump(exclude_unset=True)
    update_data = {k: v for k, v in update_data.items() if k in _UPDATABLE_COLUMNS}
    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="更新するフィールドを指定してください")

    set_clauses = ", ".join(f"{k} = :{k}" for k in update_data)
    update_data["id"] = invoice_id

    result = await db.execute(
        text(f"UPDATE invoices SET {set_clauses}, updated_at = NOW() WHERE id = :id RETURNING {_INVOICE_COLUMNS}"),
        update_data,
    )
    row = result.mappings().first()

    await record_audit_log(db=db, tenant_id=tenant_id, user_id=current_user.id,
                           action="update", table_name="invoices", record_id=invoice_id,
                           old_data=dict(old_row), new_data=update_data)
    await db.commit()
    await reset_tenant_context(db, tenant_id)  # ADR-072 Phase 2.5
    return InvoiceResponse(**dict(row))


@router.post(
    "/invoices/{invoice_id}/issue",
    response_model=InvoiceResponse,
    dependencies=[Depends(require_permission("invoices.create"))],
)
async def issue_invoice(
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """請求書を発行する（draft → issued）"""
    result = await db.execute(
        text(f"UPDATE invoices SET status = 'issued', issued_at = NOW(), updated_at = NOW() WHERE id = :id AND status = 'draft' RETURNING {_INVOICE_COLUMNS}"),
        {"id": invoice_id},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="draft状態の請求書のみ発行できます")

    await record_audit_log(db=db, tenant_id=tenant_id, user_id=current_user.id,
                           action="issue", table_name="invoices", record_id=invoice_id,
                           new_data={"status": "issued"})
    await db.commit()
    await reset_tenant_context(db, tenant_id)  # ADR-072 Phase 2.5
    await invalidate_dashboard_cache(tenant_id)
    return InvoiceResponse(**dict(row))


@router.post(
    "/invoices/{invoice_id}/pay",
    response_model=InvoiceResponse,
    dependencies=[Depends(require_permission("invoices.update"))],
)
async def pay_invoice(
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """入金を登録する（issued/overdue → paid）"""
    result = await db.execute(
        text(f"UPDATE invoices SET status = 'paid', paid_at = NOW(), updated_at = NOW() WHERE id = :id AND status IN ('issued', 'overdue') RETURNING {_INVOICE_COLUMNS}"),
        {"id": invoice_id},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="issued/overdue状態の請求書のみ入金登録できます")

    await record_audit_log(db=db, tenant_id=tenant_id, user_id=current_user.id,
                           action="pay", table_name="invoices", record_id=invoice_id,
                           new_data={"status": "paid"})
    await db.commit()
    await reset_tenant_context(db, tenant_id)  # ADR-072 Phase 2.5
    await invalidate_dashboard_cache(tenant_id)
    return InvoiceResponse(**dict(row))


@router.post(
    "/invoices/{invoice_id}/void",
    response_model=InvoiceResponse,
    dependencies=[Depends(require_permission("invoices.void"))],
)
async def void_invoice(
    invoice_id: int,
    data: VoidRequest,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """請求書を無効化する"""
    old = await db.execute(text(f"SELECT {_INVOICE_COLUMNS} FROM invoices WHERE id = :id"), {"id": invoice_id})
    old_row = old.mappings().first()
    if not old_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="請求書が見つかりません")
    if old_row["status"] == "voided":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="既に無効化されています")
    if old_row["status"] == "paid":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="入金済みの請求書は無効化できません")

    voided_number = f"[VOID]{old_row['invoice_number']}"
    result = await db.execute(
        text(f"""
            UPDATE invoices
            SET status = 'voided', invoice_number = :vnum, voided_at = NOW(),
                void_reason = :reason, updated_at = NOW()
            WHERE id = :id
            RETURNING {_INVOICE_COLUMNS}
        """),
        {"id": invoice_id, "vnum": voided_number, "reason": data.reason},
    )
    row = result.mappings().first()

    await record_audit_log(db=db, tenant_id=tenant_id, user_id=current_user.id,
                           action="void", table_name="invoices", record_id=invoice_id,
                           old_data=dict(old_row), new_data={"status": "voided", "reason": data.reason})
    await db.commit()
    await reset_tenant_context(db, tenant_id)  # ADR-072 Phase 2.5
    await invalidate_dashboard_cache(tenant_id)
    return InvoiceResponse(**dict(row))
