from __future__ import annotations

"""
アーカイブ・復元API。

顧客/案件/注文等の古いデータをアーカイブし、必要時に復元する。

変更履歴:
  2026-04-17: 初版作成（Phase 4）
"""

import json

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import (
    get_current_tenant,
    get_current_user,
    require_permission,
    reset_tenant_context,
)
from app.database import get_db
from app.models import User
from app.services.audit import record_audit_log

router = APIRouter()

ARCHIVABLE_TABLES = {"deals", "orders", "leads", "quotes", "invoices"}


class ArchiveRequest(BaseModel):
    source_table: str = Field(min_length=1, max_length=100)
    source_id: int = Field(ge=1)


class ArchiveResponse(BaseModel):
    id: int
    source_table: str
    source_id: int
    archived_by: int | None
    archived_at: str
    restored_at: str | None
    model_config = {"from_attributes": True}


@router.get("/archives", response_model=list[ArchiveResponse],
            dependencies=[Depends(require_permission("archive.view"))])
async def list_archives(
    source_table: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    offset = (page - 1) * per_page
    conditions = []
    params: dict = {"limit": per_page, "offset": offset}
    if source_table:
        conditions.append("source_table = :st")
        params["st"] = source_table
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    result = await db.execute(
        text(f"SELECT id, source_table, source_id, archived_by, archived_at, restored_at FROM archives {where} ORDER BY archived_at DESC LIMIT :limit OFFSET :offset"),
        params,
    )
    return [ArchiveResponse(**row) for row in result.mappings().all()]


@router.post("/archives", response_model=ArchiveResponse, status_code=201,
             dependencies=[Depends(require_permission("archive.manage"))])
async def archive_record(
    data: ArchiveRequest,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """レコードをアーカイブする（元データをJSONB保存後、元テーブルから削除）"""
    if data.source_table not in ARCHIVABLE_TABLES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"アーカイブ対象外のテーブルです。対象: {', '.join(sorted(ARCHIVABLE_TABLES))}")

    # 元データ取得
    result = await db.execute(
        text(f"SELECT * FROM {data.source_table} WHERE id = :id"),
        {"id": data.source_id},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="対象レコードが見つかりません")

    archived_data = json.dumps(dict(row), ensure_ascii=False, default=str)

    # アーカイブに保存
    arch_result = await db.execute(
        text("""
            INSERT INTO archives (tenant_id, source_table, source_id, archived_data, archived_by)
            VALUES (:tid, :table, :sid, CAST(:data AS JSONB), :by)
            RETURNING id, source_table, source_id, archived_by, archived_at, restored_at
        """),
        {"tid": tenant_id, "table": data.source_table, "sid": data.source_id,
         "data": archived_data, "by": current_user.id},
    )
    arch_row = arch_result.mappings().first()

    # 元テーブルから削除
    await db.execute(text(f"DELETE FROM {data.source_table} WHERE id = :id"), {"id": data.source_id})

    await record_audit_log(db=db, tenant_id=tenant_id, user_id=current_user.id,
                           action="archive", table_name=data.source_table, record_id=data.source_id,
                           old_data=dict(row))
    await db.commit()
    await reset_tenant_context(db, tenant_id)  # ADR-072 Phase 2.5
    return ArchiveResponse(**dict(arch_row))


@router.post("/archives/{archive_id}/restore", response_model=ArchiveResponse,
             dependencies=[Depends(require_permission("archive.manage"))])
async def restore_record(
    archive_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """アーカイブから元テーブルにレコードを復元する"""
    result = await db.execute(
        text("SELECT id, source_table, source_id, archived_data, restored_at FROM archives WHERE id = :id"),
        {"id": archive_id},
    )
    arch = result.mappings().first()
    if not arch:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="アーカイブが見つかりません")
    if arch["restored_at"] is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="既に復元済みです")

    table = arch["source_table"]
    data = json.loads(arch["archived_data"]) if isinstance(arch["archived_data"], str) else arch["archived_data"]

    # 元テーブルにINSERT（id含む）
    cols = [k for k in data.keys() if k != "id"]
    placeholders = ", ".join(f":{k}" for k in cols)
    col_names = ", ".join(cols)
    await db.execute(text(f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})"), data)

    # アーカイブに復元マーク
    updated = await db.execute(
        text("""
            UPDATE archives SET restored_at = NOW(), restored_by = :by
            WHERE id = :id
            RETURNING id, source_table, source_id, archived_by, archived_at, restored_at
        """),
        {"by": current_user.id, "id": archive_id},
    )
    row = updated.mappings().first()

    await record_audit_log(db=db, tenant_id=tenant_id, user_id=current_user.id,
                           action="restore", table_name=table, record_id=arch["source_id"],
                           new_data={"archive_id": archive_id})
    await db.commit()
    await reset_tenant_context(db, tenant_id)  # ADR-072 Phase 2.5
    return ArchiveResponse(**dict(row))
