"""
中央 admin 用 public.pokemon_dex / public.trainer_dex CRUD ルーター。

spec.md v1.1 F2 (Sprint 2) / AC2.4:
  - dex_kind = 'pokemon' or 'trainer' でテーブル切替
  - pokemon_dex(generation, region), trainer_dex(era)

API:
  GET    /api/v1/super-admin/dex/{dex_kind}
  POST   /api/v1/super-admin/dex/{dex_kind}
  PATCH  /api/v1/super-admin/dex/{dex_kind}/{id}
  DELETE /api/v1/super-admin/dex/{dex_kind}/{id}
"""
from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_super_admin
from app.database import get_db
from app.schemas.central_masters import (
    DexImportApplyRequest,
    DexImportApplyResponse,
    DexImportEntry,
    DexImportPreviewResponse,
    PokemonDexCreate,
    PokemonDexResponse,
    PokemonDexUpdate,
    TrainerDexCreate,
    TrainerDexResponse,
    TrainerDexUpdate,
)
from app.services import pokeapi_dex

router = APIRouter()

_POKEMON_COLS = "id, dex_number, name_ja, name_en, generation, region"
_TRAINER_COLS = "id, dex_number, name_ja, name_en, era"

_POKEMON_UPDATABLE = {"dex_number", "name_ja", "name_en", "generation", "region"}
_TRAINER_UPDATABLE = {"dex_number", "name_ja", "name_en", "era"}


def _table(dex_kind: str) -> tuple[str, str]:
    if dex_kind == "pokemon":
        return ("public.pokemon_dex", _POKEMON_COLS)
    if dex_kind == "trainer":
        return ("public.trainer_dex", _TRAINER_COLS)
    raise HTTPException(status_code=404, detail="dex_kind は pokemon または trainer のみ")


@router.get(
    "/super-admin/dex/{dex_kind}",
    dependencies=[Depends(require_super_admin)],
)
async def list_dex(
    dex_kind: str,
    q: str | None = Query(default=None, max_length=255),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=200, ge=1, le=2000),
    db: AsyncSession = Depends(get_db),
):
    table, cols = _table(dex_kind)
    offset = (page - 1) * per_page
    conditions: list[str] = []
    params: dict = {"limit": per_page, "offset": offset}
    if q:
        conditions.append("(name_ja ILIKE :q OR name_en ILIKE :q OR CAST(dex_number AS TEXT) = :exact)")
        params["q"] = f"%{q}%"
        params["exact"] = q
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    result = await db.execute(
        text(
            f"SELECT {cols} FROM {table} {where} "
            f"ORDER BY dex_number, id LIMIT :limit OFFSET :offset"
        ),
        params,
    )
    rows = [dict(row) for row in result.mappings().all()]
    return rows


@router.post(
    "/super-admin/dex/{dex_kind}",
    status_code=201,
    dependencies=[Depends(require_super_admin)],
)
async def create_dex(
    dex_kind: str,
    data: dict,  # 動的に PokemonDexCreate / TrainerDexCreate を分岐
    db: AsyncSession = Depends(get_db),
):
    table, cols = _table(dex_kind)
    if dex_kind == "pokemon":
        validated = PokemonDexCreate(**data).model_dump()
        sql = (
            f"INSERT INTO {table} (dex_number, name_ja, name_en, generation, region) "
            f"VALUES (:dex_number, :name_ja, :name_en, :generation, :region) "
            f"RETURNING {cols}"
        )
    else:
        validated = TrainerDexCreate(**data).model_dump()
        sql = (
            f"INSERT INTO {table} (dex_number, name_ja, name_en, era) "
            f"VALUES (:dex_number, :name_ja, :name_en, :era) "
            f"RETURNING {cols}"
        )
    try:
        result = await db.execute(text(sql), validated)
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"重複: {exc.orig}")
    row = result.mappings().first()
    await db.commit()
    if dex_kind == "pokemon":
        return PokemonDexResponse(**dict(row)).model_dump()
    return TrainerDexResponse(**dict(row)).model_dump()


@router.patch(
    "/super-admin/dex/{dex_kind}/{entry_id}",
    dependencies=[Depends(require_super_admin)],
)
async def update_dex(
    dex_kind: str,
    entry_id: int,
    data: dict,
    db: AsyncSession = Depends(get_db),
):
    table, cols = _table(dex_kind)
    if dex_kind == "pokemon":
        validated = PokemonDexUpdate(**data).model_dump(exclude_unset=True)
        updatable = _POKEMON_UPDATABLE
    else:
        validated = TrainerDexUpdate(**data).model_dump(exclude_unset=True)
        updatable = _TRAINER_UPDATABLE
    validated = {k: v for k, v in validated.items() if k in updatable}
    if not validated:
        raise HTTPException(status_code=400, detail="更新するフィールドを指定してください")
    set_clauses = ", ".join(f"{k} = :{k}" for k in validated)
    validated["id"] = entry_id
    result = await db.execute(
        text(f"UPDATE {table} SET {set_clauses} WHERE id = :id RETURNING {cols}"),
        validated,
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="図鑑エントリが見つかりません")
    await db.commit()
    return dict(row)


@router.delete(
    "/super-admin/dex/{dex_kind}/{entry_id}",
    status_code=204,
    dependencies=[Depends(require_super_admin)],
)
async def delete_dex(
    dex_kind: str,
    entry_id: int,
    db: AsyncSession = Depends(get_db),
):
    table, _ = _table(dex_kind)
    result = await db.execute(
        text(f"DELETE FROM {table} WHERE id = :id"), {"id": entry_id}
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="図鑑エントリが見つかりません")
    await db.commit()


# ============================================================================
# ADR-084: PokeAPI 取込 (ポケモン図鑑のみ・手動トリガ)
#   preview = 外部取得 + 既存突合 (DB書込なし) → 新規分を返す
#   apply   = preview で得た新規分を INSERT (既存は ON CONFLICT DO NOTHING で不変)
# ============================================================================
_IMPORT_MAX_FETCH = 500


@router.post(
    "/super-admin/dex/pokemon/import/preview",
    response_model=DexImportPreviewResponse,
    dependencies=[Depends(require_super_admin)],
)
async def import_pokemon_preview(db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(text("SELECT dex_number FROM public.pokemon_dex"))
    ).scalars().all()
    existing = {int(n) for n in rows}
    try:
        result = await pokeapi_dex.fetch_new_species(
            existing, max_fetch=_IMPORT_MAX_FETCH
        )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"PokeAPI への接続に失敗しました: {exc}",
        )
    return DexImportPreviewResponse(
        source="pokeapi",
        source_count=result["source_count"],
        db_count=len(existing),
        added=[DexImportEntry(**e) for e in result["added"]],
        added_count=result["added_count"],
        truncated=result["truncated"],
    )


@router.post(
    "/super-admin/dex/pokemon/import/apply",
    response_model=DexImportApplyResponse,
    dependencies=[Depends(require_super_admin)],
)
async def import_pokemon_apply(
    payload: DexImportApplyRequest,
    db: AsyncSession = Depends(get_db),
):
    inserted = 0
    for entry in payload.entries:
        result = await db.execute(
            text(
                "INSERT INTO public.pokemon_dex "
                "(dex_number, name_ja, name_en, generation) "
                "VALUES (:dex_number, :name_ja, :name_en, :generation) "
                "ON CONFLICT (dex_number) DO NOTHING"
            ),
            {
                "dex_number": entry.dex_number,
                "name_ja": entry.name_ja,
                "name_en": entry.name_en,
                "generation": entry.generation,
            },
        )
        inserted += result.rowcount or 0
    await db.commit()
    return DexImportApplyResponse(inserted_count=inserted)
