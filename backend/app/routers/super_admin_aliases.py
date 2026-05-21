"""
中央 admin 用 public.supplier_aliases CRUD + CSV import/export ルーター。

spec.md v1.1 F2 (Sprint 2) / AC2.2 / AC2.6 / AC2.7:
  - require_super_admin で保護
  - UNIQUE(supplier_id, alias_text, language) を IntegrityError 409 で返す

API:
  GET    /api/v1/super-admin/aliases
  POST   /api/v1/super-admin/aliases
  PATCH  /api/v1/super-admin/aliases/{id}
  DELETE /api/v1/super-admin/aliases/{id}
  GET    /api/v1/super-admin/aliases/export
  POST   /api/v1/super-admin/aliases/import
"""
from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_super_admin
from app.database import get_db
from app.models import User
from app.schemas.central_masters import (
    SupplierAliasCreate,
    SupplierAliasResponse,
    SupplierAliasUpdate,
)

router = APIRouter()

_COLS = (
    "id, product_id, supplier_id, alias_text, language, confidence, source, "
    "created_by, created_at, updated_at"
)
_UPDATABLE = {"supplier_id", "alias_text", "language", "product_id", "confidence", "source"}


@router.get(
    "/super-admin/aliases",
    response_model=list[SupplierAliasResponse],
    dependencies=[Depends(require_super_admin)],
)
async def list_aliases(
    supplier_id: int | None = Query(default=None),
    q: str | None = Query(default=None, max_length=255),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    offset = (page - 1) * per_page
    conditions: list[str] = []
    params: dict = {"limit": per_page, "offset": offset}
    if supplier_id is not None:
        conditions.append("supplier_id = :supplier_id")
        params["supplier_id"] = supplier_id
    if q:
        conditions.append("alias_text ILIKE :q")
        params["q"] = f"%{q}%"
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    result = await db.execute(
        text(
            f"SELECT {_COLS} FROM public.supplier_aliases {where} "
            f"ORDER BY supplier_id, alias_text LIMIT :limit OFFSET :offset"
        ),
        params,
    )
    return [SupplierAliasResponse(**dict(row)) for row in result.mappings().all()]


@router.post(
    "/super-admin/aliases",
    response_model=SupplierAliasResponse,
    status_code=201,
    dependencies=[Depends(require_super_admin)],
)
async def create_alias(
    data: SupplierAliasCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_super_admin),
):
    try:
        result = await db.execute(
            text(
                f"INSERT INTO public.supplier_aliases "
                f"(supplier_id, alias_text, language, product_id, confidence, source, created_by) "
                f"VALUES (:supplier_id, :alias_text, :language, :product_id, :confidence, :source, :uid) "
                f"RETURNING {_COLS}"
            ),
            {**data.model_dump(), "uid": current_user.id},
        )
    except IntegrityError as exc:
        await db.rollback()
        # AC2.6 / spec F1 AC1.2: UNIQUE 違反は 409
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"重複または FK 違反: {exc.orig}",
        )
    row = result.mappings().first()
    await db.commit()
    return SupplierAliasResponse(**dict(row))


@router.patch(
    "/super-admin/aliases/{alias_id}",
    response_model=SupplierAliasResponse,
    dependencies=[Depends(require_super_admin)],
)
async def update_alias(
    alias_id: int,
    data: SupplierAliasUpdate,
    db: AsyncSession = Depends(get_db),
):
    update_data = data.model_dump(exclude_unset=True)
    update_data = {k: v for k, v in update_data.items() if k in _UPDATABLE}
    if not update_data:
        raise HTTPException(status_code=400, detail="更新するフィールドを指定してください")
    set_clauses = ", ".join(f"{k} = :{k}" for k in update_data)
    update_data["id"] = alias_id
    try:
        result = await db.execute(
            text(
                f"UPDATE public.supplier_aliases SET {set_clauses}, updated_at = NOW() "
                f"WHERE id = :id RETURNING {_COLS}"
            ),
            update_data,
        )
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=f"重複または FK 違反: {exc.orig}")
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="aliasが見つかりません")
    await db.commit()
    return SupplierAliasResponse(**dict(row))


@router.delete(
    "/super-admin/aliases/{alias_id}",
    status_code=204,
    dependencies=[Depends(require_super_admin)],
)
async def delete_alias(alias_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        text("DELETE FROM public.supplier_aliases WHERE id = :id"),
        {"id": alias_id},
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="aliasが見つかりません")
    await db.commit()


@router.get(
    "/super-admin/aliases/export",
    dependencies=[Depends(require_super_admin)],
)
async def export_csv(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        text(f"SELECT {_COLS} FROM public.supplier_aliases ORDER BY id")
    )
    rows = result.mappings().all()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "id", "product_id", "supplier_id", "alias_text", "language",
        "confidence", "source",
    ])
    for r in rows:
        writer.writerow([
            r["id"], r["product_id"], r["supplier_id"], r["alias_text"],
            r["language"],
            float(r["confidence"]) if r["confidence"] is not None else "",
            r["source"] or "",
        ])
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=supplier_aliases.csv"},
    )


_REQUIRED_CSV_COLS = {"supplier_id", "alias_text"}


@router.post(
    "/super-admin/aliases/import",
    dependencies=[Depends(require_super_admin)],
)
async def import_csv(
    file: UploadFile = File(...),
    dry_run: bool = Query(default=True),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_super_admin),
):
    content = (await file.read()).decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(content))
    if reader.fieldnames is None:
        raise HTTPException(status_code=400, detail="CSVが空、またはヘッダーがありません")
    missing = _REQUIRED_CSV_COLS - set(reader.fieldnames)
    if missing:
        raise HTTPException(status_code=400, detail=f"必須列が欠落: {sorted(missing)}")

    rows: list[dict] = []
    errors: list[str] = []
    for idx, raw in enumerate(reader, start=2):
        try:
            supplier_id_raw = (raw.get("supplier_id") or "").strip()
            alias_text = (raw.get("alias_text") or "").strip()
            if not supplier_id_raw or not alias_text:
                errors.append(f"L{idx}: 必須列が空")
                continue
            row = {
                "supplier_id": int(supplier_id_raw),
                "alias_text": alias_text,
                "language": (raw.get("language") or "ja").strip()[:2] or "ja",
                "product_id": int(raw["product_id"]) if raw.get("product_id") else None,
                "confidence": float(raw["confidence"]) if raw.get("confidence") else None,
                "source": (raw.get("source") or None) or None,
            }
            rows.append(row)
        except (TypeError, ValueError) as exc:
            errors.append(f"L{idx}: {exc}")
    if errors:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "CSV にエラーが含まれています",
                "errors": errors[:50],
                "valid_count": len(rows),
            },
        )
    if dry_run:
        return {"dry_run": True, "would_insert": len(rows), "preview": rows[:5]}

    # Sprint 2 Reviewer Minor F1 (PR #510) fix:
    #   ON CONFLICT DO NOTHING は IntegrityError を発生させないため
    #   try/except では UNIQUE 重複行を検出できない（旧実装では UNIQUE 衝突
    #   行もすべて inserted カウントに含めていた）。
    #   PostgreSQL の RETURNING 句で xmax = 0 を返すことで、各行が
    #   実際に新規挿入されたか既存衝突でスキップされたかを行単位で判定する。
    #   xmax = 0  → 新規挿入された
    #   xmax != 0 → 既存行で衝突しスキップされた
    #   ※ ON CONFLICT DO NOTHING + RETURNING はスキップ行も返す（PG 9.5+）
    inserted = 0
    skipped = 0
    fk_errors = 0
    for row in rows:
        try:
            result = await db.execute(
                text(
                    "INSERT INTO public.supplier_aliases "
                    "(supplier_id, alias_text, language, product_id, confidence, source, created_by) "
                    "VALUES (:supplier_id, :alias_text, :language, :product_id, :confidence, :source, :uid) "
                    "ON CONFLICT (supplier_id, alias_text, language) DO NOTHING "
                    "RETURNING id, (xmax = 0) AS inserted_flag"
                ),
                {**row, "uid": current_user.id},
            )
            returned = result.mappings().first()
            if returned is None:
                # RETURNING が 1 行も返らないケース: ON CONFLICT DO NOTHING の
                # 古い PG 実装互換、または FK 違反等の前段でブロックされた行。
                # ここでは「衝突でスキップされた」と扱う。
                skipped += 1
            elif returned["inserted_flag"]:
                inserted += 1
            else:
                skipped += 1
        except IntegrityError:
            # FK 違反等の本物のエラー（supplier_id / product_id が無効など）
            await db.rollback()
            fk_errors += 1
    await db.commit()
    return {
        "dry_run": False,
        "inserted": inserted,
        "skipped": skipped,
        "fk_errors": fk_errors,
    }
