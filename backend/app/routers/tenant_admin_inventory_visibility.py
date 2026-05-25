"""
テナント admin 用 inventory.visibility.* 権限マトリクス管理ルーター。

spec.md v1.1 F2 (Sprint 2) / AC2.8 / AC7.9:
  - require_permission("tenant.inventory_visibility.edit") で保護
  - 自テナント内のロールに対し inventory.visibility.{full,staff,viewer} を ON/OFF
  - search_path 切替により他テナントの role_permissions には書込不可

API:
  GET    /api/v1/admin/inventory-visibility/matrix
         自テナントのロール × visibility 権限マトリクスを返す
  PUT    /api/v1/admin/inventory-visibility/roles/{role_id}
         指定ロールの visibility キー集合を上書き
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import (
    get_current_tenant,
    get_current_user,
    require_permission,
    reset_tenant_context,
)
from app.cache import invalidate_tenant_permissions
from app.database import get_db
from app.models import User
from app.schemas.central_masters import (
    RoleVisibilityAssign,
    RoleVisibilityMatrixResponse,
    RoleVisibilityPermission,
)

router = APIRouter()

_VISIBILITY_KEYS = (
    "inventory.visibility.full",
    "inventory.visibility.staff",
    "inventory.visibility.viewer",
)


@router.get(
    "/admin/inventory-visibility/matrix",
    response_model=RoleVisibilityMatrixResponse,
    dependencies=[Depends(require_permission("tenant.inventory_visibility.edit"))],
)
async def get_matrix(
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
):
    """自テナントのロール × inventory.visibility.* 権限マトリクスを返す。

    AC2.8 前提: マスク表示の挙動は F7 (Sprint 7) で実装されるが、本 API は
    その権限切替 UI のためのデータソース。
    """
    # search_path は get_current_tenant で自テナントに固定済み
    # → roles / role_permissions は自テナント schema を見る
    result = await db.execute(
        text("""
            SELECT
                r.id AS role_id,
                r.name AS role_name,
                p.key AS permission_key,
                CASE WHEN rp.role_id IS NULL THEN FALSE ELSE TRUE END AS is_granted
            FROM roles r
            CROSS JOIN public.permissions p
            LEFT JOIN role_permissions rp
                   ON rp.role_id = r.id AND rp.permission_id = p.id
            WHERE p.key = ANY(:keys)
            ORDER BY r.priority DESC, r.name, p.key
        """),
        {"keys": list(_VISIBILITY_KEYS)},
    )
    rows = [
        RoleVisibilityPermission(
            role_id=row["role_id"],
            role_name=row["role_name"],
            permission_key=row["permission_key"],
            is_granted=bool(row["is_granted"]),
        )
        for row in result.mappings().all()
    ]
    return RoleVisibilityMatrixResponse(
        visibility_keys=list(_VISIBILITY_KEYS),
        rows=rows,
    )


@router.put(
    "/admin/inventory-visibility/roles/{role_id}",
    dependencies=[Depends(require_permission("tenant.inventory_visibility.edit"))],
)
async def set_role_visibility(
    role_id: int,
    data: RoleVisibilityAssign,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """
    指定ロールに割り当てる visibility_keys を上書きする（差分計算）。

    テナント分離:
      search_path が自テナントに固定されているため、roles / role_permissions の
      INSERT / DELETE は自テナント schema 内のみ。
      role_id が他テナントの場合は roles テーブルから引けないため 404。
    """
    if data.role_id != role_id:
        raise HTTPException(
            status_code=400,
            detail="URL の role_id と body の role_id が一致しません",
        )
    # role が自テナントに存在するかチェック（テナント分離保証、IDOR 防止）
    role_check = await db.execute(
        text("SELECT id, is_system FROM roles WHERE id = :rid"),
        {"rid": role_id},
    )
    role_row = role_check.first()
    if not role_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="指定ロールが自テナント内に見つかりません",
        )

    # Sprint 2 Reviewer Minor F2 (PR #510) fix:
    #   is_system=TRUE のロール（owner / system / member 等）の visibility 編集を禁止。
    #   テナント admin が誤って owner ロールから inventory.visibility.full を外すと、
    #   オーナー自身が在庫マスクされた状態になる事故を防ぐ。
    #   既存の roles.update / roles.delete (backend/app/routers/roles.py) と同じ
    #   ガード方針で揃える。
    if role_row[1]:  # is_system
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="システムロールの visibility は編集できません",
        )

    # 受け取った keys が有効な visibility キーかチェック
    invalid_keys = set(data.visibility_keys) - set(_VISIBILITY_KEYS)
    if invalid_keys:
        raise HTTPException(
            status_code=400,
            detail=f"無効な visibility キー: {sorted(invalid_keys)}",
        )

    # visibility 系 permission の id を取得
    perms = await db.execute(
        text("SELECT id, key FROM public.permissions WHERE key = ANY(:keys)"),
        {"keys": list(_VISIBILITY_KEYS)},
    )
    key_to_id = {row["key"]: row["id"] for row in perms.mappings().all()}
    target_ids = [key_to_id[k] for k in data.visibility_keys if k in key_to_id]

    # 既存の visibility 系割当を一旦削除（差分計算のシンプル化）
    await db.execute(
        text("""
            DELETE FROM role_permissions
            WHERE role_id = :rid
              AND permission_id IN (
                SELECT id FROM public.permissions WHERE key = ANY(:keys)
              )
        """),
        {"rid": role_id, "keys": list(_VISIBILITY_KEYS)},
    )
    for pid in target_ids:
        await db.execute(
            text("INSERT INTO role_permissions (role_id, permission_id) VALUES (:rid, :pid)"),
            {"rid": role_id, "pid": pid},
        )

    await db.commit()
    await reset_tenant_context(db, tenant_id)  # ADR-072 Phase 2.5
    # ロール所持者全員の権限キャッシュをパージ
    await invalidate_tenant_permissions(tenant_id)
    return {
        "role_id": role_id,
        "applied_keys": list(data.visibility_keys),
    }
