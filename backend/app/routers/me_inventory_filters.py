"""在庫表のユーザー別フィルタ設定 API（ADR-093 Phase 4）。

GET   /api/v1/me/inventory-filters   現在ユーザーの保存済みフィルタを返す（未設定はデフォルト）
PATCH /api/v1/me/inventory-filters   フィルタを upsert（enabled + filters JSONB）

設計は locale/theme（staff.py の public.users 個人設定）と同じ「public 中央テーブル +
get_current_user + upsert」パターン。public.user_inventory_filters は user_id PK で
tenant スキーマに依存しないため reset_tenant_context は不要（locale/theme と同様）。

SQLite (pytest) には user_inventory_filters テーブルが無いため is_postgresql で分岐し、
GET はデフォルト・PATCH は no-op（受領値をそのまま返却）で API 契約のみ検証可能にする。
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, is_postgresql
from app.database import get_db
from app.models import User

router = APIRouter()


class InventoryFilterPayload(BaseModel):
    """在庫表フィルタ設定（ユーザー別）。"""

    enabled: bool = Field(default=False, description="フィルタ ON/OFF トグル")
    hidden_supplier_ids: list[int] = Field(
        default_factory=list, description="非表示にする仕入元ID（複数選択）"
    )
    hidden_columns: list[str] = Field(
        default_factory=list, description="非表示にする列キー（unit / condition / unitPrice / quantity 等）"
    )


def _coerce_int_list(raw: object) -> list[int]:
    out: list[int] = []
    if isinstance(raw, list):
        for x in raw:
            if isinstance(x, bool):
                continue
            if isinstance(x, int):
                out.append(x)
            elif isinstance(x, str) and x.strip().lstrip("-").isdigit():
                out.append(int(x))
    return out


@router.get("/me/inventory-filters", response_model=InventoryFilterPayload)
async def get_my_inventory_filters(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """現在ユーザーの在庫表フィルタ設定を返す（未設定はデフォルト）。"""
    if not is_postgresql(db):
        return InventoryFilterPayload()
    row = (
        await db.execute(
            text("SELECT enabled, filters FROM public.user_inventory_filters WHERE user_id = :uid"),
            {"uid": current_user.id},
        )
    ).mappings().first()
    if not row:
        return InventoryFilterPayload()
    f = row["filters"] or {}
    if isinstance(f, str):
        try:
            f = json.loads(f)
        except (ValueError, TypeError):
            f = {}
    return InventoryFilterPayload(
        enabled=bool(row["enabled"]),
        hidden_supplier_ids=_coerce_int_list(f.get("hidden_supplier_ids")),
        hidden_columns=[str(x) for x in (f.get("hidden_columns") or []) if isinstance(x, str)],
    )


@router.patch("/me/inventory-filters", response_model=InventoryFilterPayload)
async def update_my_inventory_filters(
    payload: InventoryFilterPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """在庫表フィルタ設定を upsert（再ログイン後も保持）。"""
    if not is_postgresql(db):
        return payload
    filters_json = json.dumps(
        {
            "hidden_supplier_ids": payload.hidden_supplier_ids,
            "hidden_columns": payload.hidden_columns,
        }
    )
    await db.execute(
        text(
            """
            INSERT INTO public.user_inventory_filters (user_id, enabled, filters, updated_at)
            VALUES (:uid, :enabled, CAST(:filters AS JSONB), NOW())
            ON CONFLICT (user_id) DO UPDATE SET
                enabled = EXCLUDED.enabled,
                filters = EXCLUDED.filters,
                updated_at = NOW()
            """
        ),
        {"uid": current_user.id, "enabled": payload.enabled, "filters": filters_json},
    )
    await db.commit()
    return payload
