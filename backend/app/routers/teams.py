from __future__ import annotations

"""
チーム管理API。

テナントスキーマの teams, team_members テーブルを操作する。

変更履歴:
  2026-04-16: 初版作成（Phase 1）
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import (
    get_current_user,
    get_current_tenant,
    require_permission,
    reset_tenant_context,
)
from app.database import get_db
from app.models import User
from app.schemas.team import (
    TeamCreate,
    TeamMemberAdd,
    TeamMemberResponse,
    TeamResponse,
    TeamUpdate,
)
from app.services.audit import record_audit_log

router = APIRouter()

_UPDATABLE_COLUMNS = {"name", "leader_id", "description", "is_active"}


async def _load_team(db: AsyncSession, team_id: int) -> dict | None:
    result = await db.execute(
        text("""
            SELECT t.id, t.name, t.leader_id, t.description, t.is_active,
                   t.created_at, t.updated_at,
                   (SELECT COUNT(*) FROM team_members tm WHERE tm.team_id = t.id)::INT AS member_count
            FROM teams t
            WHERE t.id = :id
        """),
        {"id": team_id},
    )
    row = result.mappings().first()
    return dict(row) if row else None


@router.get(
    "/teams",
    response_model=list[TeamResponse],
    dependencies=[Depends(require_permission("teams.view"))],
)
async def list_teams(
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """チーム一覧を取得する"""
    result = await db.execute(
        text("""
            SELECT t.id, t.name, t.leader_id, t.description, t.is_active,
                   t.created_at, t.updated_at,
                   (SELECT COUNT(*) FROM team_members tm WHERE tm.team_id = t.id)::INT AS member_count
            FROM teams t
            ORDER BY t.name
        """)
    )
    rows = result.mappings().all()
    return [TeamResponse(**row) for row in rows]


@router.get(
    "/teams/{team_id}",
    response_model=TeamResponse,
    dependencies=[Depends(require_permission("teams.view"))],
)
async def get_team(
    team_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """チーム詳細を取得する"""
    team = await _load_team(db, team_id)
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="チームが見つかりません")
    return TeamResponse(**team)


@router.post(
    "/teams",
    response_model=TeamResponse,
    status_code=201,
    dependencies=[Depends(require_permission("teams.create"))],
)
async def create_team(
    data: TeamCreate,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """チームを作成する"""
    try:
        result = await db.execute(
            text("""
                INSERT INTO teams (tenant_id, name, leader_id, description)
                VALUES (:tenant_id, :name, :leader_id, :description)
                RETURNING id
            """),
            {
                "tenant_id": tenant_id,
                "name": data.name,
                "leader_id": data.leader_id,
                "description": data.description,
            },
        )
        new_id = result.scalar_one()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="同じ名前のチームが既に存在します",
        )

    await record_audit_log(
        db=db, tenant_id=tenant_id, user_id=current_user.id,
        action="create", table_name="teams", record_id=new_id,
        new_data=data.model_dump(exclude_none=True),
    )
    await db.commit()
    # commit後のクエリはsearch_pathが失われている可能性があるため再設定
    await reset_tenant_context(db, tenant_id)
    team = await _load_team(db, new_id)
    return TeamResponse(**team)


@router.patch(
    "/teams/{team_id}",
    response_model=TeamResponse,
    dependencies=[Depends(require_permission("teams.update"))],
)
async def update_team(
    team_id: int,
    data: TeamUpdate,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """チーム情報を更新する（部分更新）"""
    old = await _load_team(db, team_id)
    if not old:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="チームが見つかりません")

    update_data = data.model_dump(exclude_unset=True)
    update_data = {k: v for k, v in update_data.items() if k in _UPDATABLE_COLUMNS}
    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="更新するフィールドを指定してください")

    set_clauses = ", ".join(f"{k} = :{k}" for k in update_data)
    update_data["id"] = team_id

    try:
        await db.execute(
            text(f"UPDATE teams SET {set_clauses}, updated_at = NOW() WHERE id = :id"),
            update_data,
        )
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="同じ名前のチームが既に存在します",
        )

    await record_audit_log(
        db=db, tenant_id=tenant_id, user_id=current_user.id,
        action="update", table_name="teams", record_id=team_id,
        old_data=old, new_data=update_data,
    )
    await db.commit()
    await reset_tenant_context(db, tenant_id)
    team = await _load_team(db, team_id)
    return TeamResponse(**team)


@router.delete(
    "/teams/{team_id}",
    status_code=204,
    dependencies=[Depends(require_permission("teams.delete"))],
)
async def delete_team(
    team_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """チームを削除する（メンバーはCASCADE削除）"""
    old = await _load_team(db, team_id)
    if not old:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="チームが見つかりません")

    await db.execute(text("DELETE FROM teams WHERE id = :id"), {"id": team_id})
    await record_audit_log(
        db=db, tenant_id=tenant_id, user_id=current_user.id,
        action="delete", table_name="teams", record_id=team_id,
        old_data=old,
    )
    await db.commit()


@router.get(
    "/teams/{team_id}/members",
    response_model=list[TeamMemberResponse],
    dependencies=[Depends(require_permission("teams.view"))],
)
async def list_team_members(
    team_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """チームのメンバー一覧を取得する"""
    team = await _load_team(db, team_id)
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="チームが見つかりません")

    result = await db.execute(
        text("""
            SELECT tm.user_id, u.username, u.email, tm.joined_at
            FROM team_members tm
            LEFT JOIN public.users u ON u.id = tm.user_id
            WHERE tm.team_id = :team_id
            ORDER BY tm.joined_at
        """),
        {"team_id": team_id},
    )
    rows = result.mappings().all()
    return [TeamMemberResponse(**row) for row in rows]


@router.post(
    "/teams/{team_id}/members",
    response_model=TeamMemberResponse,
    status_code=201,
    dependencies=[Depends(require_permission("teams.manage_members"))],
)
async def add_team_member(
    team_id: int,
    data: TeamMemberAdd,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """チームにメンバーを追加する"""
    team = await _load_team(db, team_id)
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="チームが見つかりません")

    # 対象ユーザーが同テナントに属するか確認
    user_check = await db.execute(
        text("SELECT id FROM public.users WHERE id = :uid AND tenant_id = :tid AND is_active = TRUE"),
        {"uid": data.user_id, "tid": tenant_id},
    )
    if not user_check.first():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="指定されたユーザーが存在しません")

    try:
        await db.execute(
            text("INSERT INTO team_members (team_id, user_id) VALUES (:tid, :uid)"),
            {"tid": team_id, "uid": data.user_id},
        )
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="このユーザーは既にチームメンバーです",
        )

    await record_audit_log(
        db=db, tenant_id=tenant_id, user_id=current_user.id,
        action="add_member", table_name="team_members", record_id=team_id,
        new_data={"team_id": team_id, "user_id": data.user_id},
    )
    await db.commit()
    # commit後のクエリはsearch_pathが失われている可能性があるため再設定
    await reset_tenant_context(db, tenant_id)

    # 追加したレコードを取得
    fetched = await db.execute(
        text("""
            SELECT tm.user_id, u.username, u.email, tm.joined_at
            FROM team_members tm
            LEFT JOIN public.users u ON u.id = tm.user_id
            WHERE tm.team_id = :team_id AND tm.user_id = :uid
        """),
        {"team_id": team_id, "uid": data.user_id},
    )
    row = fetched.mappings().first()
    return TeamMemberResponse(**row)


@router.delete(
    "/teams/{team_id}/members/{user_id}",
    status_code=204,
    dependencies=[Depends(require_permission("teams.manage_members"))],
)
async def remove_team_member(
    team_id: int,
    user_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """チームからメンバーを削除する"""
    result = await db.execute(
        text("DELETE FROM team_members WHERE team_id = :tid AND user_id = :uid RETURNING id"),
        {"tid": team_id, "uid": user_id},
    )
    if not result.first():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="メンバーが見つかりません")

    await record_audit_log(
        db=db, tenant_id=tenant_id, user_id=current_user.id,
        action="remove_member", table_name="team_members", record_id=team_id,
        old_data={"team_id": team_id, "user_id": user_id},
    )
    await db.commit()
