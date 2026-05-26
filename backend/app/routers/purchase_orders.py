from __future__ import annotations

"""
仕入注文管理API（CRUD + 入荷処理 → 在庫自動加算）。

ステータス遷移: draft → ordered → received / cancelled

変更履歴:
  2026-04-17: 初版作成（Phase 3）
"""


from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
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
from app.schemas.purchase_order import (
    POCreate,
    PODetailResponse,
    POItemResponse,
    POResponse,
)
from app.services.audit import record_audit_log
from app.services.po_mailer import send_po_email_sync
from app.services.po_renderer import (
    build_email_subject_and_body,
    render_po_pdf_for,
)

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
        text("""
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
    await reset_tenant_context(db, tenant_id)  # ADR-072 Phase 2.5
    await invalidate_dashboard_cache(tenant_id)

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
    await reset_tenant_context(db, tenant_id)  # ADR-072 Phase 2.5
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
    await reset_tenant_context(db, tenant_id)  # ADR-072 Phase 2.5
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
    await reset_tenant_context(db, tenant_id)  # ADR-072 Phase 2.5
    return POResponse(**dict(row))


# ──────────────────────────────────────────────────────────────────
# Sprint 8 / F8: PDF ダウンロード + メール送信 + 再送
# ──────────────────────────────────────────────────────────────────

async def _get_tenant_schema(db: AsyncSession, tenant_id: int) -> str:
    """tenant_id から schema 名 (tenant_NNN) を取得。"""
    row = (await db.execute(
        text("SELECT id FROM public.tenants WHERE id = :id"),
        {"id": tenant_id},
    )).first()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="tenant not found",
        )
    return f"tenant_{tenant_id:03d}"


@router.get(
    "/purchase-orders/{po_id}/pdf",
    dependencies=[Depends(require_permission("purchase_orders.view"))],
)
async def download_po_pdf(
    po_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),  # noqa: ARG001
):
    """PO PDF を生成して Response として返す (AC8.1)。

    alias 置換 + 敬称分岐 + テナント名義差出人を含む。
    """
    tenant_schema = await _get_tenant_schema(db, tenant_id)
    try:
        pdf_bytes, data = await render_po_pdf_for(db, po_id, tenant_schema)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    filename = f"{data.po_number}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-PO-Number": data.po_number,
        },
    )


@router.post(
    "/purchase-orders/{po_id}/send-email",
    response_model=POResponse,
    dependencies=[Depends(require_permission("purchase_orders.update"))],
)
async def send_po_email(
    po_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """PO メールを送信 (AC8.2 / AC8.5)。

    失敗時は PO.status='error' に更新し、再送ボタンの対象とする。
    成功時はステータス変更しない (発注済 (ordered) のまま、複数回送信 OK)。
    """
    tenant_schema = await _get_tenant_schema(db, tenant_id)
    try:
        pdf_bytes, data = await render_po_pdf_for(db, po_id, tenant_schema)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    to_addr = data.supplier.email
    if not to_addr:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="送信先メールアドレスが supplier に未登録です",
        )

    subject, body = build_email_subject_and_body(data)
    # SMTP テスト時のため override を環境変数 PO_MAILER_TEST_PORT で渡せるようにする
    overrides = None
    if test_port := __import__("os").environ.get("PO_MAILER_TEST_PORT"):
        overrides = {
            "smtp_host": "localhost",
            "smtp_port": test_port,
            "mail_from": "noreply@test.salesanchor.jp",
            "use_tls": False,
        }
    result = send_po_email_sync(
        to_addr=to_addr,
        subject=subject,
        body_text=body,
        pdf_bytes=pdf_bytes,
        pdf_filename=f"{data.po_number}.pdf",
        smtp_overrides=overrides,
    )

    if result.success:
        # 成功時 status は変更しない (ordered のまま、再送 OK)
        # ただし error 状態だった場合は ordered に戻す
        await db.execute(
            text(
                "UPDATE purchase_orders "
                "SET status = CASE WHEN status = 'error' THEN 'ordered' ELSE status END, "
                "    updated_at = NOW() "
                "WHERE id = :id"
            ),
            {"id": po_id},
        )
        await record_audit_log(
            db=db, tenant_id=tenant_id, user_id=current_user.id,
            action="send_email", table_name="purchase_orders", record_id=po_id,
            new_data={"to": to_addr, "subject": subject},
        )
    elif result.skipped:
        # SMTP 未設定 → 開発環境 / idle、status 変更なし
        await record_audit_log(
            db=db, tenant_id=tenant_id, user_id=current_user.id,
            action="send_email_skipped", table_name="purchase_orders", record_id=po_id,
            new_data={"reason": "SMTP not configured"},
        )
    else:
        # 送信失敗 (AC8.5): status='error'
        await db.execute(
            text("UPDATE purchase_orders SET status = 'error', updated_at = NOW() WHERE id = :id"),
            {"id": po_id},
        )
        await record_audit_log(
            db=db, tenant_id=tenant_id, user_id=current_user.id,
            action="send_email_failed", table_name="purchase_orders", record_id=po_id,
            new_data={"to": to_addr, "error": result.error},
        )

    await db.commit()
    await reset_tenant_context(db, tenant_id)  # ADR-072 Phase 2.5

    fetched = await db.execute(
        text(f"SELECT {_PO_COLS} FROM purchase_orders WHERE id = :id"),
        {"id": po_id},
    )
    row = fetched.mappings().first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PO not found")

    if not result.success and not result.skipped:
        # 失敗時は 502 を返すが、レスポンス body には更新後の PO を含めて
        # フロントで「error」 status の取り扱いができるようにする
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "message": "メール送信に失敗しました。再送ボタンから再試行してください。",
                "error": result.error,
                "po": {**dict(row), "total_amount": str(row["total_amount"]) if row["total_amount"] else None},
            },
        )
    return POResponse(**dict(row))


@router.post(
    "/purchase-orders/{po_id}/resend-email",
    response_model=POResponse,
    dependencies=[Depends(require_permission("purchase_orders.update"))],
)
async def resend_po_email(
    po_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """error 状態の PO を再送 (AC8.5)。

    error → 送信試行 → 成功なら ordered、失敗なら error 継続。
    送信ロジックは send_po_email と共通だが、status='error' のみが対象。
    """
    pre = (await db.execute(
        text("SELECT status FROM purchase_orders WHERE id = :id"),
        {"id": po_id},
    )).first()
    if not pre:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PO not found")
    if pre[0] != "error":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="error 状態の注文のみ再送できます",
        )
    # send_po_email と同じ処理を再利用
    return await send_po_email(
        po_id=po_id, db=db, tenant_id=tenant_id, current_user=current_user,
    )
