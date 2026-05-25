from __future__ import annotations

"""
日報・週報・月報管理API。

変更履歴:
  2026-04-17: 初版作成（Phase 4）
"""

from enum import Enum

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


class ReportType(str, Enum):
    daily = "daily"
    weekly = "weekly"
    monthly = "monthly"


class StaffReportCreate(BaseModel):
    report_type: ReportType
    period: str = Field(min_length=1, max_length=20, description="例: 2026-04-17 / 2026-W16 / 2026-04")
    review: str = Field(min_length=1, max_length=10000)
    goals: str | None = Field(default=None, max_length=5000)
    challenges: str | None = Field(default=None, max_length=5000)
    self_evaluation: str | None = Field(default=None, max_length=5000)


class StaffReportReview(BaseModel):
    comment: str = Field(min_length=1, max_length=5000)


class StaffReportResponse(BaseModel):
    id: int
    report_code: str | None
    report_type: str
    user_id: int
    period: str
    review: str | None
    goals: str | None
    challenges: str | None
    self_evaluation: str | None
    ai_feedback: str | None
    reviewer_id: int | None
    reviewer_comment: str | None
    reviewed_at: str | None
    submitted_at: str | None
    created_at: str
    model_config = {"from_attributes": True}


_COLS = """
    id, report_code, report_type, user_id, period,
    review, goals, challenges, self_evaluation, ai_feedback,
    reviewer_id, reviewer_comment, reviewed_at, submitted_at, created_at
"""


@router.get("/staff-reports", response_model=list[StaffReportResponse],
            dependencies=[Depends(require_permission("staff_reports.view_own", "staff_reports.view_team"))])
async def list_reports(
    report_type: str | None = Query(default=None),
    user_id: int | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    offset = (page - 1) * per_page
    conditions = []
    params: dict = {"limit": per_page, "offset": offset}
    if report_type:
        conditions.append("report_type = :rtype")
        params["rtype"] = report_type
    if user_id:
        conditions.append("user_id = :uid")
        params["uid"] = user_id
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    result = await db.execute(
        text(f"SELECT {_COLS} FROM staff_reports {where} ORDER BY submitted_at DESC LIMIT :limit OFFSET :offset"),
        params,
    )
    return [StaffReportResponse(**row) for row in result.mappings().all()]


@router.post("/staff-reports", response_model=StaffReportResponse, status_code=201,
             dependencies=[Depends(require_permission("staff_reports.create"))])
async def create_report(
    data: StaffReportCreate,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    prefix = {"daily": "DR", "weekly": "WR", "monthly": "MR"}.get(data.report_type.value, "SR")

    result = await db.execute(
        text(f"""
            INSERT INTO staff_reports (tenant_id, report_type, user_id, period, review, goals, challenges, self_evaluation)
            VALUES (:tid, :rtype, :uid, :period, :review, :goals, :challenges, :self_eval)
            RETURNING id
        """),
        {"tid": tenant_id, "rtype": data.report_type.value, "uid": current_user.id,
         "period": data.period, "review": data.review, "goals": data.goals,
         "challenges": data.challenges, "self_eval": data.self_evaluation},
    )
    new_id = result.scalar_one()
    await db.execute(text("UPDATE staff_reports SET report_code = :code WHERE id = :id"),
                     {"code": f"{prefix}-{new_id:05d}", "id": new_id})

    fetched = await db.execute(text(f"SELECT {_COLS} FROM staff_reports WHERE id = :id"), {"id": new_id})
    row = fetched.mappings().first()

    await record_audit_log(db=db, tenant_id=tenant_id, user_id=current_user.id,
                           action="create", table_name="staff_reports", record_id=new_id,
                           new_data={"report_type": data.report_type.value, "period": data.period})
    await db.commit()
    await reset_tenant_context(db, tenant_id)  # ADR-072 Phase 2.5
    return StaffReportResponse(**row)


@router.post("/staff-reports/{report_id}/review", response_model=StaffReportResponse,
             dependencies=[Depends(require_permission("staff_reports.review"))])
async def review_report(
    report_id: int,
    data: StaffReportReview,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        text(f"""
            UPDATE staff_reports
            SET reviewer_id = :rid, reviewer_comment = :comment, reviewed_at = NOW(), updated_at = NOW()
            WHERE id = :id
            RETURNING {_COLS}
        """),
        {"rid": current_user.id, "comment": data.comment, "id": report_id},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="レポートが見つかりません")

    await record_audit_log(db=db, tenant_id=tenant_id, user_id=current_user.id,
                           action="review", table_name="staff_reports", record_id=report_id,
                           new_data={"reviewer_comment": data.comment})
    await db.commit()
    await reset_tenant_context(db, tenant_id)  # ADR-072 Phase 2.5
    return StaffReportResponse(**dict(row))
