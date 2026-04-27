from __future__ import annotations
"""
ERP連携API（Phase 5）。

請求書データのエクスポート + 同期ログ管理。
旧GAS版の15_ERPSync.gsに相当。外部ERP仕様確定後に詳細実装予定。

変更履歴:
  2026-04-17: 初版作成（Phase 5 — 同期ログ管理 + エクスポート基盤）
  2026-04-27: Phase 1-B-2 Step 5d — invoices→customers JOIN を invoices→companies JOIN に置換
"""

import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, get_current_tenant, require_permission
from app.database import get_db
from app.models import User
from app.services.audit import record_audit_log

router = APIRouter()


class SyncLogResponse(BaseModel):
    id: int
    sync_type: str
    direction: str
    record_count: int
    status: str
    error_message: str | None
    started_at: str
    completed_at: str | None
    created_by: int | None
    model_config = {"from_attributes": True}


@router.get("/erp/sync-logs", response_model=list[SyncLogResponse],
            dependencies=[Depends(require_permission("erp.view"))])
async def list_sync_logs(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    offset = (page - 1) * per_page
    result = await db.execute(
        text("""
            SELECT id, sync_type, direction, record_count, status, error_message,
                   started_at, completed_at, created_by
            FROM erp_sync_logs ORDER BY started_at DESC LIMIT :limit OFFSET :offset
        """),
        {"limit": per_page, "offset": offset},
    )
    return [SyncLogResponse(**row) for row in result.mappings().all()]


@router.post("/erp/export-invoices",
             dependencies=[Depends(require_permission("erp.sync"))])
async def export_invoices_for_erp(
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """請求書データをERP用28カラムCSV形式でエクスポートする"""
    # 同期ログ作成
    log_result = await db.execute(
        text("""
            INSERT INTO erp_sync_logs (tenant_id, sync_type, direction, status, created_by)
            VALUES (:tid, 'invoices', 'export', 'started', :by)
            RETURNING id
        """),
        {"tid": tenant_id, "by": current_user.id},
    )
    log_id = log_result.scalar_one()

    try:
        # 請求書 + 明細をフラット化（Step 5d: companies JOIN ベース）
        # 顧客名は company.billing_display_name → company_addresses.name → company.name の優先順位
        result = await db.execute(text("""
            SELECT i.invoice_number, i.currency, i.status,
                   i.issued_at, i.due_date, i.paid_at,
                   i.payment_method, i.total_amount, i.amount_jpy,
                   COALESCE(co.billing_display_name, ba.name, co.name) AS customer_name,
                   co.name AS company,
                   ii.product_name, ii.quantity, ii.unit_price, ii.subtotal
            FROM invoices i
            JOIN companies co ON co.id = i.company_id
            LEFT JOIN company_addresses ba
                   ON ba.company_id = co.id AND ba.address_type = 'billing'
            JOIN invoice_items ii ON ii.invoice_id = i.id
            WHERE i.status != 'voided'
            ORDER BY i.id, ii.sort_order
        """))
        rows = result.mappings().all()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "請求番号", "通貨", "ステータス", "発行日", "支払期限", "入金日",
            "支払方法", "合計金額", "JPY換算額",
            "顧客名", "会社名",
            "商品名", "数量", "単価", "行小計",
        ])
        for row in rows:
            writer.writerow([str(v) if v is not None else "" for v in dict(row).values()])

        # 同期ログ更新
        await db.execute(
            text("UPDATE erp_sync_logs SET status = 'completed', record_count = :cnt, completed_at = NOW() WHERE id = :id"),
            {"cnt": len(rows), "id": log_id},
        )
        await record_audit_log(db=db, tenant_id=tenant_id, user_id=current_user.id,
                               action="erp_export", table_name="invoices", record_id=log_id,
                               new_data={"record_count": len(rows)})
        await db.commit()

        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=erp_invoices_{tenant_id}.csv"},
        )

    except Exception as e:
        await db.execute(
            text("UPDATE erp_sync_logs SET status = 'failed', error_message = :err, completed_at = NOW() WHERE id = :id"),
            {"err": str(e)[:500], "id": log_id},
        )
        await db.commit()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"ERP エクスポート失敗: {e}")
