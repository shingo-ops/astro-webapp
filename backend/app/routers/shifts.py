from __future__ import annotations
"""シフト管理API。変更履歴: 2026-04-17 初版（Phase 5）"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, get_current_tenant, require_permission
from app.database import get_db
from app.models import User
from app.services.audit import record_audit_log

router = APIRouter()


class ShiftCreate(BaseModel):
    user_id: int = Field(ge=1)
    shift_date: str = Field(min_length=10, max_length=10)
    start_time: str = Field(min_length=5, max_length=8)
    end_time: str = Field(min_length=5, max_length=8)
    shift_type: str = Field(default="normal", max_length=20)
    notes: str | None = Field(default=None, max_length=5000)


class ShiftResponse(BaseModel):
    id: int
    user_id: int
    shift_date: str
    start_time: str
    end_time: str
    shift_type: str
    notes: str | None
    created_at: str
    model_config = {"from_attributes": True}


_COLS = "id, user_id, shift_date, start_time, end_time, shift_type, notes, created_at, updated_at"


@router.get("/shifts", response_model=list[ShiftResponse],
            dependencies=[Depends(require_permission("shifts.view"))])
async def list_shifts(
    user_id: int | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    conditions = []
    params: dict = {}
    if user_id:
        conditions.append("user_id = :uid"); params["uid"] = user_id
    if date_from:
        conditions.append("shift_date >= :df"); params["df"] = date_from
    if date_to:
        conditions.append("shift_date <= :dt"); params["dt"] = date_to
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    result = await db.execute(text(f"SELECT {_COLS} FROM shifts {where} ORDER BY shift_date, start_time"), params)
    return [ShiftResponse(**row) for row in result.mappings().all()]


@router.post("/shifts", response_model=ShiftResponse, status_code=201,
             dependencies=[Depends(require_permission("shifts.manage"))])
async def create_shift(data: ShiftCreate, db: AsyncSession = Depends(get_db),
                       tenant_id: int = Depends(get_current_tenant),
                       current_user: User = Depends(get_current_user)):
    try:
        result = await db.execute(
            text(f"""
                INSERT INTO shifts (tenant_id, user_id, shift_date, start_time, end_time, shift_type, notes)
                VALUES (:tid, :uid, :date, :start, :end, :type, :notes)
                RETURNING {_COLS}
            """),
            {"tid": tenant_id, "uid": data.user_id, "date": data.shift_date,
             "start": data.start_time, "end": data.end_time,
             "type": data.shift_type, "notes": data.notes},
        )
        row = result.mappings().first()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="同日同ユーザーのシフトが既に存在します")
    await record_audit_log(db=db, tenant_id=tenant_id, user_id=current_user.id,
                           action="create", table_name="shifts", record_id=row["id"],
                           new_data=data.model_dump())
    await db.commit()
    return ShiftResponse(**dict(row))


@router.delete("/shifts/{shift_id}", status_code=204,
               dependencies=[Depends(require_permission("shifts.manage"))])
async def delete_shift(shift_id: int, db: AsyncSession = Depends(get_db),
                       tenant_id: int = Depends(get_current_tenant),
                       current_user: User = Depends(get_current_user)):
    r = await db.execute(text("DELETE FROM shifts WHERE id = :id RETURNING id"), {"id": shift_id})
    if not r.first():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="シフトが見つかりません")
    await record_audit_log(db=db, tenant_id=tenant_id, user_id=current_user.id,
                           action="delete", table_name="shifts", record_id=shift_id)
    await db.commit()
