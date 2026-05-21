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
)

router = APIRouter()

_COLS = "id, tcg_type, series_code, name_ja, name_en, release_date, category"
_UPDATABLE = {"tcg_type", "series_code", "name_ja", "name_en", "release_date", "category"}


@router.get(
    "/super-admin/tcg/series",
    response_model=list[TcgSeriesResponse],
    dependencies=[Depends(require_super_admin)],
)
async def list_series(
    tcg_type: str | None = Query(default=None, max_length=30),
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
