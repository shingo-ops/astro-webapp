"""
中央 admin 用 public.tcg_series_master CRUD ルーター。

spec.md v1.1 F2 (Sprint 2) / AC2.3:
  - 5 TCG タイプ: pokemon / one_piece / dragon_ball / union_arena / yugioh
  - tcg_type フィルタで一覧
  - ja/en 両方の name を保持（UI 側で `t()` 経由で切替）

API:
  GET    /api/v1/super-admin/tcg/series
  POST   /api/v1/super-admin/tcg/series
  PATCH  /api/v1/super-admin/tcg/series/{id}
  DELETE /api/v1/super-admin/tcg/series/{id}
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_super_admin
from app.database import get_db
from app.schemas.central_masters import (
    TcgSeriesCreate,
    TcgSeriesResponse,
    TcgSeriesUpdate,
    TcgTypeCreate,
    TcgTypeResponse,
    TcgTypeUpdate,
)

router = APIRouter()

_COLS = "id, tcg_type, series_code, name_ja, name_en, release_date, category"
_UPDATABLE = {"tcg_type", "series_code", "name_ja", "name_en", "release_date", "category"}

# ADR-083: TCG 種別マスタ (public.tcg_type_master)
_TYPE_COLS = "id, code, name_ja, name_en, sort_order, is_active"
_TYPE_UPDATABLE = {"name_ja", "name_en", "sort_order", "is_active"}


@router.get(
    "/super-admin/tcg/series",
    response_model=list[TcgSeriesResponse],
    dependencies=[Depends(require_super_admin)],
)
async def list_series(
    tcg_type: str | None = Query(default=None, max_length=50),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=200, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    offset = (page - 1) * per_page
    conditions: list[str] = []
    params: dict = {"limit": per_page, "offset": offset}
    if tcg_type:
        conditions.append("tcg_type = :tcg_type")
        params["tcg_type"] = tcg_type
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    result = await db.execute(
        text(
            f"SELECT {_COLS} FROM public.tcg_series_master {where} "
            f"ORDER BY tcg_type, COALESCE(release_date, '1900-01-01'::date) DESC, id "
            f"LIMIT :limit OFFSET :offset"
        ),
        params,
    )
    return [TcgSeriesResponse(**dict(row)) for row in result.mappings().all()]


@router.post(
    "/super-admin/tcg/series",
    response_model=TcgSeriesResponse,
    status_code=201,
    dependencies=[Depends(require_super_admin)],
)
async def create_series(
    data: TcgSeriesCreate,
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await db.execute(
            text(
                f"INSERT INTO public.tcg_series_master "
                f"(tcg_type, series_code, name_ja, name_en, release_date, category) "
                f"VALUES (:tcg_type, :series_code, :name_ja, :name_en, :release_date, :category) "
                f"RETURNING {_COLS}"
            ),
            data.model_dump(),
        )
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"重複: {exc.orig}",
        )
    row = result.mappings().first()
    await db.commit()
    return TcgSeriesResponse(**dict(row))


@router.patch(
    "/super-admin/tcg/series/{series_id}",
    response_model=TcgSeriesResponse,
    dependencies=[Depends(require_super_admin)],
)
async def update_series(
    series_id: int,
    data: TcgSeriesUpdate,
    db: AsyncSession = Depends(get_db),
):
    update_data = data.model_dump(exclude_unset=True)
    update_data = {k: v for k, v in update_data.items() if k in _UPDATABLE}
    if not update_data:
        raise HTTPException(status_code=400, detail="更新するフィールドを指定してください")
    set_clauses = ", ".join(f"{k} = :{k}" for k in update_data)
    update_data["id"] = series_id
    result = await db.execute(
        text(
            f"UPDATE public.tcg_series_master SET {set_clauses} "
            f"WHERE id = :id RETURNING {_COLS}"
        ),
        update_data,
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="シリーズが見つかりません")
    await db.commit()
    return TcgSeriesResponse(**dict(row))


@router.delete(
    "/super-admin/tcg/series/{series_id}",
    status_code=204,
    dependencies=[Depends(require_super_admin)],
)
async def delete_series(series_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        text("DELETE FROM public.tcg_series_master WHERE id = :id"),
        {"id": series_id},
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="シリーズが見つかりません")
    await db.commit()


# ============================================================================
# ADR-083: TCG 種別マスタ (public.tcg_type_master) CRUD
#   種別自体を UI から増減できるようにする。code は安定キー（不変）。
# ============================================================================
@router.get(
    "/super-admin/tcg/types",
    response_model=list[TcgTypeResponse],
    dependencies=[Depends(require_super_admin)],
)
async def list_types(
    include_inactive: bool = Query(default=True),
    db: AsyncSession = Depends(get_db),
):
    where = "" if include_inactive else "WHERE is_active = TRUE"
    result = await db.execute(
        text(
            f"SELECT {_TYPE_COLS} FROM public.tcg_type_master {where} "
            f"ORDER BY sort_order, id"
        )
    )
    return [TcgTypeResponse(**dict(row)) for row in result.mappings().all()]


@router.post(
    "/super-admin/tcg/types",
    response_model=TcgTypeResponse,
    status_code=201,
    dependencies=[Depends(require_super_admin)],
)
async def create_type(data: TcgTypeCreate, db: AsyncSession = Depends(get_db)):
    # QA 2026-05-31: code 未指定時は 'tcgtype_<連番>' を自動採番（UI からは入力させない）。
    # 連番は現在の MAX(id)+1。super-admin の単独操作前提・UNIQUE 制約で衝突時は 409。
    try:
        result = await db.execute(
            text(
                f"INSERT INTO public.tcg_type_master "
                f"(code, name_ja, name_en, sort_order, is_active) VALUES "
                f"(COALESCE(:code, 'tcgtype_' || "
                f"(SELECT COALESCE(MAX(id), 0) + 1 FROM public.tcg_type_master)), "
                f":name_ja, :name_en, :sort_order, :is_active) "
                f"RETURNING {_TYPE_COLS}"
            ),
            data.model_dump(),
        )
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"種別コードが重複しています: {exc.orig}",
        )
    row = result.mappings().first()
    await db.commit()
    return TcgTypeResponse(**dict(row))


@router.patch(
    "/super-admin/tcg/types/{type_id}",
    response_model=TcgTypeResponse,
    dependencies=[Depends(require_super_admin)],
)
async def update_type(
    type_id: int,
    data: TcgTypeUpdate,
    db: AsyncSession = Depends(get_db),
):
    update_data = data.model_dump(exclude_unset=True)
    update_data = {k: v for k, v in update_data.items() if k in _TYPE_UPDATABLE}
    if not update_data:
        raise HTTPException(status_code=400, detail="更新するフィールドを指定してください")
    set_clauses = ", ".join(f"{k} = :{k}" for k in update_data)
    update_data["id"] = type_id
    result = await db.execute(
        text(
            f"UPDATE public.tcg_type_master SET {set_clauses} "
            f"WHERE id = :id RETURNING {_TYPE_COLS}"
        ),
        update_data,
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="種別が見つかりません")
    await db.commit()
    return TcgTypeResponse(**dict(row))


@router.delete(
    "/super-admin/tcg/types/{type_id}",
    status_code=204,
    dependencies=[Depends(require_super_admin)],
)
async def delete_type(type_id: int, db: AsyncSession = Depends(get_db)):
    # 削除対象の code を取得
    type_row = (
        await db.execute(
            text("SELECT code FROM public.tcg_type_master WHERE id = :id"),
            {"id": type_id},
        )
    ).mappings().first()
    if not type_row:
        raise HTTPException(status_code=404, detail="種別が見つかりません")
    # 使用中（その種別のシリーズが存在）なら削除不可
    in_use = (
        await db.execute(
            text(
                "SELECT COUNT(*) AS c FROM public.tcg_series_master "
                "WHERE tcg_type = :code"
            ),
            {"code": type_row["code"]},
        )
    ).mappings().first()
    if in_use and in_use["c"] > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"この種別には {in_use['c']} 件のシリーズが紐付いているため削除できません。"
                "先にシリーズを削除するか、無効化(is_active=false)してください。"
            ),
        )
    await db.execute(
        text("DELETE FROM public.tcg_type_master WHERE id = :id"),
        {"id": type_id},
    )
    await db.commit()
