from __future__ import annotations

"""
ロール・権限管理API（Discord式カスタムロール）。

主なルール:
  - 1ユーザー＝複数ロール、権限は和集合
  - priority（優先順位）で管理権限を階層化: 自分の最大priorityより低いロールのみ管理可能
  - is_system=True のロール（オーナー/メンバー）は編集/削除不可
  - 権限割り当ての変更後はテナント内の全ユーザー権限キャッシュをパージ

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
    load_user_permissions,
    require_permission,
)
from app.cache import invalidate_tenant_permissions, invalidate_user_permissions
from app.database import get_db
from app.models import User
from app.schemas.role import (
    PermissionResponse,
    RoleCreate,
    RolePermissionAssign,
    RoleResponse,
    RoleUpdate,
    UserRoleAssign,
    UserRoleResponse,
)
from app.services.audit import record_audit_log

router = APIRouter()


async def _get_role(db: AsyncSession, role_id: int) -> dict | None:
    result = await db.execute(
        text("""
            SELECT id, tenant_id, name, color, priority, is_system, description,
                   created_at, updated_at
            FROM roles WHERE id = :id
        """),
        {"id": role_id},
    )
    row = result.mappings().first()
    return dict(row) if row else None


async def _max_priority_for_user(db: AsyncSession, user_id: int) -> int:
    """
    該当ユーザーが保持しているロールの最大 priority を返す。
    ロール未割当ユーザーは -1（何も管理できない）。
    adminロール保持者は 1000（オーナーと同等扱い、後方互換）。
    """
    result = await db.execute(
        text("""
            SELECT COALESCE(MAX(r.priority), -1) AS max_prio
            FROM user_roles ur
            JOIN roles r ON r.id = ur.role_id
            WHERE ur.user_id = :uid
        """),
        {"uid": user_id},
    )
    row = result.first()
    max_prio = int(row.max_prio) if row and row.max_prio is not None else -1

    if max_prio < 0:
        # ロール未割当: 後方互換で public.users.role を確認
        user_result = await db.execute(
            text("SELECT role FROM public.users WHERE id = :uid"),
            {"uid": user_id},
        )
        user_row = user_result.fetchone()
        if user_row and user_row[0] == "admin":
            return 1000
    return max_prio


# =========================================================================
# パーミッションマスター
# =========================================================================

@router.get("/permissions", response_model=list[PermissionResponse])
async def list_permissions(
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """全パーミッションマスタを取得する（認証済みユーザー全員がアクセス可能）"""
    result = await db.execute(
        text("SELECT id, key, resource, action, description, category FROM public.permissions ORDER BY category, key")
    )
    rows = result.mappings().all()
    return [PermissionResponse(**row) for row in rows]


# =========================================================================
# 自分の権限取得（フロントUIのゲーティング用）
# =========================================================================

@router.get("/me/permissions")
async def get_my_permissions(
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """現在のユーザーの有効権限キー集合を返す（フロントUIのメニュー制御に使用）"""
    keys = await load_user_permissions(db, tenant_id, current_user.id)
    return {"permissions": sorted(keys)}


# =========================================================================
# ロール管理
# =========================================================================

@router.get(
    "/roles",
    response_model=list[RoleResponse],
    dependencies=[Depends(require_permission("roles.view"))],
)
async def list_roles(
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """ロール一覧を取得する（priority降順）"""
    result = await db.execute(
        text("""
            SELECT id, tenant_id, name, color, priority, is_system, description,
                   created_at, updated_at
            FROM roles ORDER BY priority DESC, name
        """)
    )
    rows = result.mappings().all()
    return [RoleResponse(**row) for row in rows]


@router.post(
    "/roles",
    response_model=RoleResponse,
    status_code=201,
    dependencies=[Depends(require_permission("roles.create"))],
)
async def create_role(
    data: RoleCreate,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """ロールを作成する。自分より高い priority のロールは作成不可。"""
    my_max = await _max_priority_for_user(db, current_user.id)
    if data.priority >= my_max:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="自分の最大priority以上のロールは作成できません",
        )

    try:
        result = await db.execute(
            text("""
                INSERT INTO roles (tenant_id, name, color, priority, is_system, description)
                VALUES (:tenant_id, :name, :color, :priority, FALSE, :description)
                RETURNING id
            """),
            {
                "tenant_id": tenant_id,
                "name": data.name,
                "color": data.color,
                "priority": data.priority,
                "description": data.description,
            },
        )
        new_id = result.scalar_one()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="同じ名前のロールが既に存在します",
        )

    await record_audit_log(
        db=db, tenant_id=tenant_id, user_id=current_user.id,
        action="create", table_name="roles", record_id=new_id,
        new_data=data.model_dump(exclude_none=True),
    )
    await db.commit()

    role = await _get_role(db, new_id)
    return RoleResponse(**role)


@router.patch(
    "/roles/{role_id}",
    response_model=RoleResponse,
    dependencies=[Depends(require_permission("roles.update"))],
)
async def update_role(
    role_id: int,
    data: RoleUpdate,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """ロール情報を更新する（部分更新）。システムロール不可、priority制限あり。"""
    old = await _get_role(db, role_id)
    if not old:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ロールが見つかりません")
    if old["is_system"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="システムロールは編集できません")

    my_max = await _max_priority_for_user(db, current_user.id)
    if old["priority"] >= my_max:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="自分と同等以上のpriorityを持つロールは編集できません",
        )

    update_data = data.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="更新するフィールドを指定してください")

    if "priority" in update_data and update_data["priority"] >= my_max:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="priorityを自分の最大priority以上に設定できません",
        )

    set_clauses = ", ".join(f"{k} = :{k}" for k in update_data)
    update_data["id"] = role_id

    try:
        await db.execute(
            text(f"UPDATE roles SET {set_clauses}, updated_at = NOW() WHERE id = :id"),
            update_data,
        )
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="同じ名前のロールが既に存在します",
        )

    await record_audit_log(
        db=db, tenant_id=tenant_id, user_id=current_user.id,
        action="update", table_name="roles", record_id=role_id,
        old_data=old, new_data=update_data,
    )
    await db.commit()

    # ロール所持者全員の権限キャッシュをパージ
    await invalidate_tenant_permissions(tenant_id)

    role = await _get_role(db, role_id)
    return RoleResponse(**role)


@router.delete(
    "/roles/{role_id}",
    status_code=204,
    dependencies=[Depends(require_permission("roles.delete"))],
)
async def delete_role(
    role_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """ロールを削除する（システムロール不可、priority制限あり）"""
    old = await _get_role(db, role_id)
    if not old:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ロールが見つかりません")
    if old["is_system"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="システムロールは削除できません")

    my_max = await _max_priority_for_user(db, current_user.id)
    if old["priority"] >= my_max:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="自分と同等以上のpriorityを持つロールは削除できません",
        )

    await db.execute(text("DELETE FROM roles WHERE id = :id"), {"id": role_id})
    await record_audit_log(
        db=db, tenant_id=tenant_id, user_id=current_user.id,
        action="delete", table_name="roles", record_id=role_id,
        old_data=old,
    )
    await db.commit()

    await invalidate_tenant_permissions(tenant_id)


# =========================================================================
# ロール権限の割り当て
# =========================================================================

@router.get(
    "/roles/{role_id}/permissions",
    response_model=list[PermissionResponse],
    dependencies=[Depends(require_permission("roles.view"))],
)
async def get_role_permissions(
    role_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """ロールに割り当てられている権限一覧を取得する"""
    role = await _get_role(db, role_id)
    if not role:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ロールが見つかりません")

    result = await db.execute(
        text("""
            SELECT p.id, p.key, p.resource, p.action, p.description, p.category
            FROM role_permissions rp
            JOIN public.permissions p ON p.id = rp.permission_id
            WHERE rp.role_id = :rid
            ORDER BY p.category, p.key
        """),
        {"rid": role_id},
    )
    rows = result.mappings().all()
    return [PermissionResponse(**row) for row in rows]


@router.put(
    "/roles/{role_id}/permissions",
    dependencies=[Depends(require_permission("roles.update"))],
)
async def set_role_permissions(
    role_id: int,
    data: RolePermissionAssign,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """ロールに割り当てる権限を一括更新する（既存の割り当てを置き換える）"""
    role = await _get_role(db, role_id)
    if not role:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ロールが見つかりません")
    if role["is_system"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="システムロールの権限は変更できません",
        )

    my_max = await _max_priority_for_user(db, current_user.id)
    if role["priority"] >= my_max:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="自分と同等以上のpriorityを持つロールは編集できません",
        )

    # 権限IDの妥当性確認
    if data.permission_ids:
        check_result = await db.execute(
            text("SELECT id FROM public.permissions WHERE id = ANY(:ids)"),
            {"ids": data.permission_ids},
        )
        found_ids = {row[0] for row in check_result.fetchall()}
        missing = set(data.permission_ids) - found_ids
        if missing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"存在しない権限ID: {sorted(missing)}",
            )

    # 既存割り当てを全削除してから挿入
    await db.execute(
        text("DELETE FROM role_permissions WHERE role_id = :rid"),
        {"rid": role_id},
    )
    for pid in data.permission_ids:
        await db.execute(
            text("INSERT INTO role_permissions (role_id, permission_id) VALUES (:rid, :pid)"),
            {"rid": role_id, "pid": pid},
        )

    await record_audit_log(
        db=db, tenant_id=tenant_id, user_id=current_user.id,
        action="set_permissions", table_name="role_permissions", record_id=role_id,
        new_data={"permission_ids": data.permission_ids},
    )
    await db.commit()

    # ロール所持者全員の権限キャッシュをパージ
    await invalidate_tenant_permissions(tenant_id)

    return {"role_id": role_id, "permission_count": len(data.permission_ids)}


# =========================================================================
# ユーザー×ロールの割り当て
# =========================================================================

@router.get(
    "/users/{user_id}/roles",
    response_model=list[UserRoleResponse],
    dependencies=[Depends(require_permission("roles.view"))],
)
async def get_user_roles(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """指定ユーザーに付与されているロール一覧を取得する"""
    result = await db.execute(
        text("""
            SELECT ur.role_id, r.name AS role_name, r.color, r.priority, ur.assigned_at
            FROM user_roles ur
            JOIN roles r ON r.id = ur.role_id
            WHERE ur.user_id = :uid
            ORDER BY r.priority DESC
        """),
        {"uid": user_id},
    )
    rows = result.mappings().all()
    return [UserRoleResponse(**row) for row in rows]


@router.put(
    "/users/{user_id}/roles",
    dependencies=[Depends(require_permission("roles.assign"))],
)
async def set_user_roles(
    user_id: int,
    data: UserRoleAssign,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """ユーザーに付与するロールを一括更新する（自分の最大priorityより高いロールは付与不可）"""
    # 対象ユーザーが同テナントに属するか確認
    user_check = await db.execute(
        text("SELECT id FROM public.users WHERE id = :uid AND tenant_id = :tid"),
        {"uid": user_id, "tid": tenant_id},
    )
    if not user_check.first():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="指定されたユーザーが存在しません")

    # 指定ロールの妥当性確認＋priority制限
    my_max = await _max_priority_for_user(db, current_user.id)
    role_check = await db.execute(
        text("SELECT id, priority FROM roles WHERE id = ANY(:ids)"),
        {"ids": data.role_ids},
    )
    role_rows = role_check.fetchall()
    found_ids = {row.id for row in role_rows}
    missing = set(data.role_ids) - found_ids
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"存在しないロールID: {sorted(missing)}",
        )
    for row in role_rows:
        if row.priority >= my_max:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"自分の最大priority以上のロール（id={row.id}）は付与できません",
            )

    # 既存割り当てを全削除してから挿入
    await db.execute(
        text("DELETE FROM user_roles WHERE user_id = :uid"),
        {"uid": user_id},
    )
    for rid in data.role_ids:
        await db.execute(
            text("""
                INSERT INTO user_roles (user_id, role_id, assigned_by)
                VALUES (:uid, :rid, :assigned_by)
            """),
            {"uid": user_id, "rid": rid, "assigned_by": current_user.id},
        )

    await record_audit_log(
        db=db, tenant_id=tenant_id, user_id=current_user.id,
        action="assign_roles", table_name="user_roles", record_id=user_id,
        new_data={"role_ids": data.role_ids},
    )
    await db.commit()

    # 対象ユーザーの権限キャッシュをパージ
    await invalidate_user_permissions(tenant_id, user_id)

    return {"user_id": user_id, "role_count": len(data.role_ids)}
