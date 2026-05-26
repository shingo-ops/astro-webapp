from __future__ import annotations

"""Buddy/コーチングシステムAPI。変更履歴: 2026-04-17 初版（Phase 5）"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
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


class PairCreate(BaseModel):
    coach_user_id: int = Field(ge=1)
    mentee_user_id: int = Field(ge=1)
    notes: str | None = Field(default=None, max_length=5000)


class PairResponse(BaseModel):
    id: int
    coach_user_id: int
    mentee_user_id: int
    is_active: bool
    started_at: str
    ended_at: str | None
    notes: str | None
    model_config = {"from_attributes": True}


class FeedbackCreate(BaseModel):
    pair_id: int = Field(ge=1)
    feedback_type: str = Field(min_length=1, max_length=10, description="Good or Bad")
    reason: str | None = Field(default=None, max_length=5000)
    context: str | None = Field(default=None, max_length=5000)


class FeedbackResponse(BaseModel):
    id: int
    pair_id: int
    feedback_type: str
    reason: str | None
    context: str | None
    created_by: int
    created_at: str
    model_config = {"from_attributes": True}


@router.get("/buddy/pairs", response_model=list[PairResponse],
            dependencies=[Depends(require_permission("buddy.view_own", "buddy.manage"))])
async def list_pairs(active_only: bool = Query(default=True),
                     db: AsyncSession = Depends(get_db),
                     tenant_id: int = Depends(get_current_tenant),
                     current_user: User = Depends(get_current_user)):
    where = "WHERE is_active = TRUE" if active_only else ""
    result = await db.execute(
        text(f"SELECT id, coach_user_id, mentee_user_id, is_active, started_at, ended_at, notes FROM buddy_pairs {where} ORDER BY started_at DESC"))
    return [PairResponse(**row) for row in result.mappings().all()]


@router.post("/buddy/pairs", response_model=PairResponse, status_code=201,
             dependencies=[Depends(require_permission("buddy.manage"))])
async def create_pair(data: PairCreate, db: AsyncSession = Depends(get_db),
                      tenant_id: int = Depends(get_current_tenant),
                      current_user: User = Depends(get_current_user)):
    if data.coach_user_id == data.mentee_user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="コーチとメンティーは同一ユーザーにできません")
    try:
        result = await db.execute(
            text("""
                INSERT INTO buddy_pairs (tenant_id, coach_user_id, mentee_user_id, notes)
                VALUES (:tid, :coach, :mentee, :notes)
                RETURNING id, coach_user_id, mentee_user_id, is_active, started_at, ended_at, notes
            """),
            {"tid": tenant_id, "coach": data.coach_user_id, "mentee": data.mentee_user_id, "notes": data.notes},
        )
        row = result.mappings().first()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="同じペアリングが既に存在します")
    await record_audit_log(db=db, tenant_id=tenant_id, user_id=current_user.id,
                           action="create", table_name="buddy_pairs", record_id=row["id"],
                           new_data=data.model_dump())
    await db.commit()
    await reset_tenant_context(db, tenant_id)  # ADR-072 Phase 2.5
    return PairResponse(**dict(row))


@router.post("/buddy/pairs/{pair_id}/end", response_model=PairResponse,
             dependencies=[Depends(require_permission("buddy.manage"))])
async def end_pair(pair_id: int, db: AsyncSession = Depends(get_db),
                   tenant_id: int = Depends(get_current_tenant),
                   current_user: User = Depends(get_current_user)):
    result = await db.execute(
        text("UPDATE buddy_pairs SET is_active = FALSE, ended_at = NOW() WHERE id = :id AND is_active = TRUE RETURNING id, coach_user_id, mentee_user_id, is_active, started_at, ended_at, notes"),
        {"id": pair_id},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="アクティブなペアが見つかりません")
    await record_audit_log(db=db, tenant_id=tenant_id, user_id=current_user.id,
                           action="end", table_name="buddy_pairs", record_id=pair_id)
    await db.commit()
    await reset_tenant_context(db, tenant_id)  # ADR-072 Phase 2.5
    return PairResponse(**dict(row))


@router.get("/buddy/feedbacks", response_model=list[FeedbackResponse],
            dependencies=[Depends(require_permission("buddy.view_own", "buddy.review"))])
async def list_feedbacks(pair_id: int | None = Query(default=None),
                         db: AsyncSession = Depends(get_db),
                         tenant_id: int = Depends(get_current_tenant),
                         current_user: User = Depends(get_current_user)):
    conditions = []
    params: dict = {}
    if pair_id:
        conditions.append("pair_id = :pid"); params["pid"] = pair_id
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    result = await db.execute(
        text(f"SELECT id, pair_id, feedback_type, reason, context, created_by, created_at FROM buddy_feedbacks {where} ORDER BY created_at DESC"),
        params,
    )
    return [FeedbackResponse(**row) for row in result.mappings().all()]


@router.post("/buddy/feedbacks", response_model=FeedbackResponse, status_code=201,
             dependencies=[Depends(require_permission("buddy.view_own"))])
async def create_feedback(data: FeedbackCreate, db: AsyncSession = Depends(get_db),
                          tenant_id: int = Depends(get_current_tenant),
                          current_user: User = Depends(get_current_user)):
    result = await db.execute(
        text("""
            INSERT INTO buddy_feedbacks (tenant_id, pair_id, feedback_type, reason, context, created_by)
            VALUES (:tid, :pid, :ftype, :reason, :ctx, :by)
            RETURNING id, pair_id, feedback_type, reason, context, created_by, created_at
        """),
        {"tid": tenant_id, "pid": data.pair_id, "ftype": data.feedback_type,
         "reason": data.reason, "ctx": data.context, "by": current_user.id},
    )
    row = result.mappings().first()
    await record_audit_log(db=db, tenant_id=tenant_id, user_id=current_user.id,
                           action="create", table_name="buddy_feedbacks", record_id=row["id"],
                           new_data=data.model_dump())
    await db.commit()
    await reset_tenant_context(db, tenant_id)  # ADR-072 Phase 2.5
    return FeedbackResponse(**dict(row))
