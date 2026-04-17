from __future__ import annotations
"""バッジ・ゲーミフィケーションAPI。変更履歴: 2026-04-17 初版（Phase 5）"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, get_current_tenant, require_permission
from app.database import get_db
from app.models import User
from app.services.audit import record_audit_log

router = APIRouter()


class BadgeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    icon: str | None = Field(default=None, max_length=10)
    criteria: str | None = Field(default=None, max_length=500)
    points: int = Field(default=0, ge=0)


class BadgeResponse(BaseModel):
    id: int; name: str; description: str | None; icon: str | None
    criteria: str | None; points: int; is_active: bool; created_at: str
    model_config = {"from_attributes": True}


class UserBadgeResponse(BaseModel):
    id: int; user_id: int; badge_id: int; badge_name: str
    badge_icon: str | None; earned_at: str
    model_config = {"from_attributes": True}


class AwardRequest(BaseModel):
    user_id: int = Field(ge=1)
    badge_id: int = Field(ge=1)


@router.get("/badges", response_model=list[BadgeResponse],
            dependencies=[Depends(require_permission("badges.view"))])
async def list_badges(db: AsyncSession = Depends(get_db),
                      tenant_id: int = Depends(get_current_tenant),
                      current_user: User = Depends(get_current_user)):
    result = await db.execute(text("SELECT id, name, description, icon, criteria, points, is_active, created_at FROM badge_definitions WHERE is_active = TRUE ORDER BY name"))
    return [BadgeResponse(**row) for row in result.mappings().all()]


@router.post("/badges", response_model=BadgeResponse, status_code=201,
             dependencies=[Depends(require_permission("badges.manage"))])
async def create_badge(data: BadgeCreate, db: AsyncSession = Depends(get_db),
                       tenant_id: int = Depends(get_current_tenant),
                       current_user: User = Depends(get_current_user)):
    result = await db.execute(
        text("""
            INSERT INTO badge_definitions (tenant_id, name, description, icon, criteria, points)
            VALUES (:tid, :name, :desc, :icon, :criteria, :points)
            RETURNING id, name, description, icon, criteria, points, is_active, created_at
        """),
        {"tid": tenant_id, "name": data.name, "desc": data.description,
         "icon": data.icon, "criteria": data.criteria, "points": data.points},
    )
    row = result.mappings().first()
    await record_audit_log(db=db, tenant_id=tenant_id, user_id=current_user.id,
                           action="create", table_name="badge_definitions", record_id=row["id"],
                           new_data=data.model_dump())
    await db.commit()
    return BadgeResponse(**dict(row))


@router.get("/badges/leaderboard", response_model=list[dict],
            dependencies=[Depends(require_permission("badges.view"))])
async def leaderboard(db: AsyncSession = Depends(get_db),
                      tenant_id: int = Depends(get_current_tenant),
                      current_user: User = Depends(get_current_user)):
    result = await db.execute(text("""
        SELECT ub.user_id, u.username, COUNT(*) AS badge_count,
               COALESCE(SUM(bd.points), 0) AS total_points
        FROM user_badges ub
        JOIN badge_definitions bd ON bd.id = ub.badge_id
        LEFT JOIN public.users u ON u.id = ub.user_id
        GROUP BY ub.user_id, u.username
        ORDER BY total_points DESC, badge_count DESC
    """))
    return [dict(row) for row in result.mappings().all()]


@router.post("/badges/award", response_model=UserBadgeResponse, status_code=201,
             dependencies=[Depends(require_permission("badges.manage"))])
async def award_badge(data: AwardRequest, db: AsyncSession = Depends(get_db),
                      tenant_id: int = Depends(get_current_tenant),
                      current_user: User = Depends(get_current_user)):
    badge = await db.execute(text("SELECT id, name FROM badge_definitions WHERE id = :id AND is_active = TRUE"), {"id": data.badge_id})
    if not badge.first():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="バッジが見つかりません")
    try:
        result = await db.execute(
            text("""
                INSERT INTO user_badges (tenant_id, user_id, badge_id)
                VALUES (:tid, :uid, :bid)
                RETURNING id, user_id, badge_id, earned_at
            """),
            {"tid": tenant_id, "uid": data.user_id, "bid": data.badge_id},
        )
        row = result.mappings().first()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="既にこのバッジを獲得しています")
    badge_info = await db.execute(text("SELECT name, icon FROM badge_definitions WHERE id = :id"), {"id": data.badge_id})
    b = badge_info.mappings().first()
    await record_audit_log(db=db, tenant_id=tenant_id, user_id=current_user.id,
                           action="award", table_name="user_badges", record_id=row["id"],
                           new_data={"user_id": data.user_id, "badge_id": data.badge_id})
    await db.commit()
    return UserBadgeResponse(id=row["id"], user_id=row["user_id"], badge_id=row["badge_id"],
                             badge_name=b["name"] if b else "", badge_icon=b["icon"] if b else None,
                             earned_at=str(row["earned_at"]))


@router.get("/badges/users/{user_id}", response_model=list[UserBadgeResponse],
            dependencies=[Depends(require_permission("badges.view"))])
async def user_badges(user_id: int, db: AsyncSession = Depends(get_db),
                      tenant_id: int = Depends(get_current_tenant),
                      current_user: User = Depends(get_current_user)):
    result = await db.execute(text("""
        SELECT ub.id, ub.user_id, ub.badge_id, bd.name AS badge_name, bd.icon AS badge_icon, ub.earned_at
        FROM user_badges ub
        JOIN badge_definitions bd ON bd.id = ub.badge_id
        WHERE ub.user_id = :uid
        ORDER BY ub.earned_at DESC
    """), {"uid": user_id})
    return [UserBadgeResponse(**row) for row in result.mappings().all()]
