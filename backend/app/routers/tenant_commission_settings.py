from __future__ import annotations

"""
テナント別の報酬計算設定 API（tenant_commission_settings）。

ADR-021 Phase 5 / Sprint 5: 担当者報酬計算 MVP
  - GET   /tenant-commission-settings — 取得（なければ default で create する idempotent get-or-create）
  - PATCH /tenant-commission-settings — 更新

権限・テナント:
  - require_permission("orders.view")   for GET（既存パーミッション体系を流用）
  - require_permission("orders.update") for PATCH
  - Depends(get_current_tenant) で tenant スキーマを切替

設計:
  1 テナント = 1 行（UNIQUE tenant_id）。GET 時に行が無ければ default を作って返す
  「get-or-create」を採用し、フロント側は「初期化が要るかどうか」を意識せず使える。

変更履歴:
  2026-05-11: 初版（ADR-021 Phase 5 / Sprint 5）
"""

import json

from fastapi import APIRouter, Depends, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import (
    get_current_user,
    get_current_tenant,
    require_permission,
)
from app.database import get_db
from app.models import User
from app.schemas.tenant_commission_settings import (
    DEFAULT_COMMISSION_RATES,
    CommissionRatesConfig,
    TenantCommissionSettingsResponse,
    TenantCommissionSettingsUpdate,
)
from app.services.audit import record_audit_log

router = APIRouter()


_SELECT_COLS = """
    id, tenant_id, commission_rates, created_at, updated_at
"""


def _row_to_response(row: dict) -> TenantCommissionSettingsResponse:
    """DB row（commission_rates が JSON 文字列 or dict）からレスポンスを組む。

    PostgreSQL JSONB は SQLAlchemy が自動で dict にデシリアライズするが、
    SQLite テスト環境では TEXT カラムに JSON 文字列で入っているため、
    両方を受け付ける。
    """
    raw = row["commission_rates"]
    if isinstance(raw, str):
        rates_dict = json.loads(raw)
    else:
        rates_dict = raw or {}
    rates = CommissionRatesConfig.model_validate(rates_dict)
    return TenantCommissionSettingsResponse(
        id=row["id"],
        tenant_id=row["tenant_id"],
        commission_rates=rates,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def _fetch_settings(db: AsyncSession, tenant_id: int) -> dict | None:
    res = await db.execute(
        text(f"""
            SELECT {_SELECT_COLS}
            FROM tenant_commission_settings
            WHERE tenant_id = :tenant_id
        """),
        {"tenant_id": tenant_id},
    )
    row = res.mappings().first()
    return dict(row) if row else None


async def _create_default(db: AsyncSession, tenant_id: int) -> dict:
    """デフォルト rate でテナント設定を作成し、作成行を返す。

    UNIQUE 制約に当たれば（並列に他リクエストが既に作っていた場合）、
    存在チェック → 取得で吸収する（idempotent）。
    """
    default_json = DEFAULT_COMMISSION_RATES.model_dump_json()
    try:
        res = await db.execute(
            text(f"""
                INSERT INTO tenant_commission_settings (tenant_id, commission_rates)
                VALUES (:tenant_id, :rates)
                RETURNING {_SELECT_COLS}
            """),
            {"tenant_id": tenant_id, "rates": default_json},
        )
        row = res.mappings().first()
        await db.commit()
        return dict(row)
    except Exception:
        await db.rollback()
        # 競合時は既存レコードを取得して返す（get-or-create の "or" 側）
        existing = await _fetch_settings(db, tenant_id)
        if existing is None:
            raise
        return existing


@router.get(
    "/tenant-commission-settings",
    response_model=TenantCommissionSettingsResponse,
    dependencies=[Depends(require_permission("orders.view"))],
)
async def get_tenant_commission_settings(
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """テナント別 rate 設定を取得する（なければ default で作成する idempotent get-or-create）。"""
    row = await _fetch_settings(db, tenant_id)
    if row is None:
        row = await _create_default(db, tenant_id)
    return _row_to_response(row)


@router.patch(
    "/tenant-commission-settings",
    response_model=TenantCommissionSettingsResponse,
    dependencies=[Depends(require_permission("orders.update"))],
)
async def update_tenant_commission_settings(
    data: TenantCommissionSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """テナント別 rate 設定を更新する。行が無ければ作成して更新する。"""
    existing = await _fetch_settings(db, tenant_id)
    if existing is None:
        existing = await _create_default(db, tenant_id)

    new_rates_json = data.commission_rates.model_dump_json()
    update_sql = text(f"""
        UPDATE tenant_commission_settings
        SET commission_rates = :rates, updated_at = NOW()
        WHERE tenant_id = :tenant_id
        RETURNING {_SELECT_COLS}
    """)
    res = await db.execute(
        update_sql,
        {"rates": new_rates_json, "tenant_id": tenant_id},
    )
    new_row = dict(res.mappings().first())

    await record_audit_log(
        db=db,
        tenant_id=tenant_id,
        user_id=current_user.id,
        action="update",
        table_name="tenant_commission_settings",
        record_id=new_row["id"],
        old_data={"commission_rates": existing.get("commission_rates")},
        new_data={"commission_rates": data.commission_rates.model_dump(mode="json")},
    )
    await db.commit()

    return _row_to_response(new_row)
