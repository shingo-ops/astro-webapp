"""
中央 admin 用 public.tenant_llm_budgets CRUD ルーター。

spec.md v1.1 F4 / Sprint 4 / AC4.6:
  - require_super_admin で保護（is_super_admin=true のみ）
  - public schema 直書き（tenant_id PK）
  - GET 一覧 / GET 単体 / PUT 更新 (upsert) のみ。DELETE は出さない
    （budget 行の削除は migration / 手動運用のみ。AC4.3 の事故防止）

API:
  GET    /api/v1/super-admin/llm-budget          全テナント一覧（tenants との JOIN で名前付与）
  GET    /api/v1/super-admin/llm-budget/{tenant_id}    単体取得
  PUT    /api/v1/super-admin/llm-budget/{tenant_id}    upsert (monthly_budget_usd / hard_stop / notify_admin)
"""
from __future__ import annotations

import logging
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, condecimal
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_super_admin
from app.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic schemas (in-file: super-admin scoped, 他で再利用しない)
# ---------------------------------------------------------------------------


class LLMBudgetResponse(BaseModel):
    tenant_id: int
    tenant_code: str | None = None
    tenant_name: str | None = None
    monthly_budget_usd: Decimal
    current_month_usd: Decimal
    last_reset_at: str  # ISO 8601 文字列で返す
    hard_stop: bool
    notify_admin: bool
    created_at: str | None = None
    updated_at: str | None = None


class LLMBudgetUpdate(BaseModel):
    monthly_budget_usd: condecimal(ge=Decimal("0"), max_digits=10, decimal_places=2) = Field(  # type: ignore[valid-type]
        ..., description="月次予算 (USD)。0 にすると即予算超過 → API 呼ばない"
    )
    hard_stop: bool = Field(
        default=True,
        description="予算超過時に API 呼び出しを停止するか。AC4.3 デフォルト true",
    )
    notify_admin: bool = Field(
        default=True,
        description="予算超過時に Discord webhook で通知するか",
    )


_COLS = (
    "b.tenant_id, b.monthly_budget_usd, b.current_month_usd, "
    "b.last_reset_at, b.hard_stop, b.notify_admin, "
    "b.created_at, b.updated_at, "
    "t.tenant_code, t.tenant_name"
)


def _row_to_response(row: dict) -> LLMBudgetResponse:
    return LLMBudgetResponse(
        tenant_id=row["tenant_id"],
        tenant_code=row.get("tenant_code"),
        tenant_name=row.get("tenant_name"),
        monthly_budget_usd=Decimal(row["monthly_budget_usd"]),
        current_month_usd=Decimal(row["current_month_usd"]),
        last_reset_at=row["last_reset_at"].isoformat() if row.get("last_reset_at") else "",
        hard_stop=row["hard_stop"],
        notify_admin=row["notify_admin"],
        created_at=row["created_at"].isoformat() if row.get("created_at") else None,
        updated_at=row["updated_at"].isoformat() if row.get("updated_at") else None,
    )


@router.get(
    "/super-admin/llm-budget",
    response_model=list[LLMBudgetResponse],
    dependencies=[Depends(require_super_admin)],
)
async def list_budgets(db: AsyncSession = Depends(get_db)):
    """全テナントの budget 一覧。tenants テーブルと LEFT JOIN して名前を付与。

    AC4.6: admin UI が tenant ごとの予算 / 現在使用量 / hard_stop を一覧で確認する。
    """
    result = await db.execute(
        text(
            f"""
            SELECT {_COLS}
              FROM public.tenant_llm_budgets b
              LEFT JOIN public.tenants t ON t.id = b.tenant_id
             ORDER BY b.tenant_id
            """
        )
    )
    return [_row_to_response(dict(r)) for r in result.mappings().all()]


@router.get(
    "/super-admin/llm-budget/{tenant_id}",
    response_model=LLMBudgetResponse,
    dependencies=[Depends(require_super_admin)],
)
async def get_budget(tenant_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        text(
            f"""
            SELECT {_COLS}
              FROM public.tenant_llm_budgets b
              LEFT JOIN public.tenants t ON t.id = b.tenant_id
             WHERE b.tenant_id = :tid
            """
        ),
        {"tid": tenant_id},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"tenant_id={tenant_id} の LLM 予算行が存在しません",
        )
    return _row_to_response(dict(row))


@router.put(
    "/super-admin/llm-budget/{tenant_id}",
    response_model=LLMBudgetResponse,
    dependencies=[Depends(require_super_admin)],
)
async def upsert_budget(
    tenant_id: int,
    data: LLMBudgetUpdate,
    db: AsyncSession = Depends(get_db),
):
    """upsert (INSERT ON CONFLICT DO UPDATE)。current_month_usd / last_reset_at は変更しない。

    AC4.6: admin が予算編集 → 即 DB 反映。
    """
    await db.execute(
        text(
            """
            INSERT INTO public.tenant_llm_budgets
                (tenant_id, monthly_budget_usd, current_month_usd,
                 last_reset_at, hard_stop, notify_admin)
            VALUES (:tid, :budget, 0, NOW(), :hard_stop, :notify_admin)
            ON CONFLICT (tenant_id) DO UPDATE
                SET monthly_budget_usd = EXCLUDED.monthly_budget_usd,
                    hard_stop          = EXCLUDED.hard_stop,
                    notify_admin       = EXCLUDED.notify_admin
            """
        ),
        {
            "tid": tenant_id,
            "budget": str(data.monthly_budget_usd),
            "hard_stop": data.hard_stop,
            "notify_admin": data.notify_admin,
        },
    )
    await db.commit()

    # 更新後を再取得して返す
    result = await db.execute(
        text(
            f"""
            SELECT {_COLS}
              FROM public.tenant_llm_budgets b
              LEFT JOIN public.tenants t ON t.id = b.tenant_id
             WHERE b.tenant_id = :tid
            """
        ),
        {"tid": tenant_id},
    )
    row = result.mappings().first()
    if not row:
        # ありえないが防御
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="upsert 後の行取得に失敗しました",
        )
    return _row_to_response(dict(row))
