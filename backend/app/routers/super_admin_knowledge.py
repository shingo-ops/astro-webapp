"""
中央 admin 用 public.knowledge_rules CRUD + CSV import/export ルーター。

spec.md v1.1 F2 (Sprint 2) / AC2.2 / AC2.6 / AC2.7:
  - require_super_admin で保護（is_super_admin=true のみ）
  - public schema 直書き（tenant_id 列なし）
  - CSV import は dry_run 必須（diff プレビュー → commit の 2 段階）

API:
  GET    /api/v1/super-admin/knowledge          一覧（検索 q, ページネーション）
  POST   /api/v1/super-admin/knowledge          1 件作成
  PATCH  /api/v1/super-admin/knowledge/{id}     部分更新
  DELETE /api/v1/super-admin/knowledge/{id}     削除（hard delete）
  GET    /api/v1/super-admin/knowledge/export   全件 CSV エクスポート
  POST   /api/v1/super-admin/knowledge/import   CSV import（dry_run 対応）
"""
from __future__ import annotations

import csv
import io
import logging

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_super_admin
from app.database import get_db
from app.models import User
from app.schemas.central_masters import (
    KnowledgeRuleCreate,
    KnowledgeRuleResponse,
    KnowledgeRuleUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_COLS = (
    "id, category, pattern_type, pattern, normalized_to, priority, "
    "language, is_active, created_by, created_at"
)
_UPDATABLE = {
    "category", "pattern_type", "pattern", "normalized_to",
    "priority", "language", "is_active",
}

_REQUIRED_CSV_COLS = {"category", "pattern_type", "pattern", "normalized_to"}


@router.get(
    "/super-admin/knowledge",
    response_model=list[KnowledgeRuleResponse],
    dependencies=[Depends(require_super_admin)],
)
async def list_rules(
    q: str | None = Query(default=None, max_length=255),
    is_active: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    """正規化辞書（knowledge_rules）一覧。検索 q は pattern / normalized_to に部分一致。"""
    offset = (page - 1) * per_page
    conditions: list[str] = []
    params: dict = {"limit": per_page, "offset": offset}
    if q:
        conditions.append("(pattern ILIKE :q OR normalized_to ILIKE :q OR category ILIKE :q)")
        params["q"] = f"%{q}%"
    if is_active is not None:
        conditions.append("is_active = :is_active")
        params["is_active"] = is_active
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    result = await db.execute(
        text(
            f"SELECT {_COLS} FROM public.knowledge_rules {where} "
            f"ORDER BY priority DESC, id LIMIT :limit OFFSET :offset"
        ),
        params,
    )
    return [KnowledgeRuleResponse(**dict(row)) for row in result.mappings().all()]


@router.post(
    "/super-admin/knowledge",
    response_model=KnowledgeRuleResponse,
    status_code=201,
    dependencies=[Depends(require_super_admin)],
)
async def create_rule(
    data: KnowledgeRuleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_super_admin),
):
    try:
        result = await db.execute(
            text(
                f"INSERT INTO public.knowledge_rules "
                f"(category, pattern_type, pattern, normalized_to, priority, language, is_active, created_by) "
                f"VALUES (:category, :pattern_type, :pattern, :normalized_to, :priority, :language, :is_active, :uid) "
                f"RETURNING {_COLS}"
            ),
            {**data.model_dump(), "uid": current_user.id},
        )
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"重複または制約違反: {exc.orig}",
        )
    row = result.mappings().first()
    await db.commit()
    return KnowledgeRuleResponse(**dict(row))


@router.patch(
    "/super-admin/knowledge/{rule_id}",
    response_model=KnowledgeRuleResponse,
    dependencies=[Depends(require_super_admin)],
)
async def update_rule(
    rule_id: int,
    data: KnowledgeRuleUpdate,
    db: AsyncSession = Depends(get_db),
):
    update_data = data.model_dump(exclude_unset=True)
    update_data = {k: v for k, v in update_data.items() if k in _UPDATABLE}
    if not update_data:
        raise HTTPException(status_code=400, detail="更新するフィールドを指定してください")
    set_clauses = ", ".join(f"{k} = :{k}" for k in update_data)
    update_data["id"] = rule_id
    result = await db.execute(
        text(
            f"UPDATE public.knowledge_rules SET {set_clauses} "
            f"WHERE id = :id RETURNING {_COLS}"
        ),
        update_data,
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="ルールが見つかりません")
    await db.commit()
    return KnowledgeRuleResponse(**dict(row))


@router.delete(
    "/super-admin/knowledge/{rule_id}",
    status_code=204,
    dependencies=[Depends(require_super_admin)],
)
async def delete_rule(rule_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        text("DELETE FROM public.knowledge_rules WHERE id = :id"),
        {"id": rule_id},
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="ルールが見つかりません")
    await db.commit()


@router.get(
    "/super-admin/knowledge/export",
    dependencies=[Depends(require_super_admin)],
)
async def export_csv(db: AsyncSession = Depends(get_db)):
    """全件 CSV エクスポート（id 含む、再 import 時の identity 維持のため）"""
    result = await db.execute(
        text(f"SELECT {_COLS} FROM public.knowledge_rules ORDER BY id")
    )
    rows = result.mappings().all()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "id", "category", "pattern_type", "pattern", "normalized_to",
        "priority", "language", "is_active",
    ])
    for r in rows:
        writer.writerow([
            r["id"], r["category"], r["pattern_type"], r["pattern"],
            r["normalized_to"], r["priority"], r["language"],
            "true" if r["is_active"] else "false",
        ])
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=knowledge_rules.csv"},
    )


@router.post(
    "/super-admin/knowledge/import",
    dependencies=[Depends(require_super_admin)],
)
async def import_csv(
    file: UploadFile = File(...),
    dry_run: bool = Query(default=True),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_super_admin),
):
    """
    CSV import。dry_run=True で diff プレビュー、=False で commit。
    必須列: category, pattern_type, pattern, normalized_to
    任意列: priority (default 100), language (default ja), is_active (default true)
    """
    content = (await file.read()).decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(content))
    if reader.fieldnames is None:
        raise HTTPException(status_code=400, detail="CSVが空、またはヘッダーがありません")
    missing = _REQUIRED_CSV_COLS - set(reader.fieldnames)
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"必須列が欠落: {sorted(missing)}",
        )
    rows: list[dict] = []
    errors: list[str] = []
    for idx, raw in enumerate(reader, start=2):  # ヘッダ行を 1 とした 1-origin
        try:
            row = {
                "category": (raw.get("category") or "").strip(),
                "pattern_type": (raw.get("pattern_type") or "").strip(),
                "pattern": (raw.get("pattern") or "").strip(),
                "normalized_to": (raw.get("normalized_to") or "").strip(),
                "priority": int(raw.get("priority") or 100),
                "language": (raw.get("language") or "ja").strip()[:2] or "ja",
                "is_active": str(raw.get("is_active") or "true").lower() not in {"false", "0", "no"},
            }
            if not row["category"] or not row["pattern"] or not row["normalized_to"]:
                errors.append(f"L{idx}: 必須列が空")
                continue
            if row["pattern_type"] not in {"regex", "exact", "prefix", "suffix", "contains"}:
                errors.append(f"L{idx}: pattern_type 不正: {row['pattern_type']}")
                continue
            rows.append(row)
        except (TypeError, ValueError) as exc:
            errors.append(f"L{idx}: {exc}")

    if errors:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "CSV にエラーが含まれています。修正後に再実行してください。",
                "errors": errors[:50],
                "valid_count": len(rows),
            },
        )

    if dry_run:
        return {
            "dry_run": True,
            "would_insert": len(rows),
            "preview": rows[:5],
        }

    # commit
    for row in rows:
        await db.execute(
            text(
                "INSERT INTO public.knowledge_rules "
                "(category, pattern_type, pattern, normalized_to, priority, language, is_active, created_by) "
                "VALUES (:category, :pattern_type, :pattern, :normalized_to, :priority, :language, :is_active, :uid)"
            ),
            {**row, "uid": current_user.id},
        )
    await db.commit()
    return {"dry_run": False, "inserted": len(rows)}
