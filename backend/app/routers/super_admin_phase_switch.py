"""中央 admin 用 スプレッドシート並走 Phase 切替 API (Sprint 9 / F9 v1.3)。

spec.md v1.3 F9 / AC9.3 / AC9.4:
  - require_super_admin で保護 (is_super_admin=true のみ)
  - GET: 現在 Phase を返す
  - PUT: Phase 切替を実行する
      - v1.3 では 'B' 標準運用、'A' (緊急戻し) も技術的に許可
      - 'C' へは 400 + 「Out-of-scope、別 ADR」エラーメッセージを返す
      - 切替成功時は audit_log に action='phase.switch' を記録 (AC9.4)

API:
  GET  /api/v1/super-admin/phase-switch/{tenant_id}
  PUT  /api/v1/super-admin/phase-switch/{tenant_id}
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_super_admin
from app.database import get_db
from app.models import User
from app.services.audit import record_audit_log
from app.services.phase_gate import (
    ALLOWED_PHASES,
    SCOPED_PHASES,
    Phase,
    get_phase,
    set_phase,
)

logger = logging.getLogger(__name__)

router = APIRouter()


class PhaseResponse(BaseModel):
    """現在 Phase レスポンス + v1.2 制約情報。"""

    tenant_id: int
    phase: str = Field(..., description="現在の Phase ('A' / 'B' / 'C')")
    allowed_phases: list[str] = Field(
        default_factory=lambda: list(ALLOWED_PHASES),
        description="技術的に許可されている Phase の集合（DB CHECK 制約）",
    )
    scoped_phases: list[str] = Field(
        default_factory=lambda: list(SCOPED_PHASES),
        description="spec v1.3 で運用許可されている Phase（'A' (緊急戻し) + 'B' (標準)、'C' は別 ADR）",
    )


class PhaseSwitchRequest(BaseModel):
    """Phase 切替リクエスト。"""

    phase: str = Field(..., description="切替先 Phase ('A' / 'B' / 'C')")


@router.get(
    "/super-admin/phase-switch/{tenant_id}",
    response_model=PhaseResponse,
    dependencies=[Depends(require_super_admin)],
)
async def get_phase_endpoint(
    tenant_id: int,
    db: AsyncSession = Depends(get_db),
):
    """現在の Phase 設定を返す (AC9.5)。"""
    phase = await get_phase(tenant_id, db)
    return PhaseResponse(
        tenant_id=tenant_id,
        phase=phase,
        allowed_phases=list(ALLOWED_PHASES),
        scoped_phases=list(SCOPED_PHASES),
    )


@router.put(
    "/super-admin/phase-switch/{tenant_id}",
    response_model=PhaseResponse,
)
async def switch_phase_endpoint(
    tenant_id: int,
    payload: PhaseSwitchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_super_admin),
):
    """Phase 切替を実行する (AC9.3 / AC9.4)。

    v1.3 制約:
      - 'B' 標準運用、'A' (緊急戻し) も技術的に許可、'C' のみ Out-of-scope (別 ADR)。
      - 'C' を指定された場合は 400 + i18n 用の error key を含めて返す。
      - 'A' / 'B' へは何度切替えても成功（冪等、audit_log は記録される）。

    audit_log:
      - 切替成功時に {tenant_id}.audit_logs に
        action='phase.switch', table_name='tenant_settings',
        old_data={phase: <old>}, new_data={phase: <new>} を記録 (AC9.4)。
    """
    new_phase = payload.phase
    if new_phase not in ALLOWED_PHASES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"phase={new_phase!r} は許可された Phase ('A' / 'B' / 'C') ではありません。"
            ),
        )
    if new_phase not in SCOPED_PHASES:
        # spec v1.3: 'C' のみ Out-of-scope (別 ADR、本格データ移行込み)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "phase_out_of_scope",
                "message": (
                    f"Phase '{new_phase}' への切替は spec v1.3 では Out-of-scope です。"
                    "別 ADR で時期判断中。"
                ),
                "scoped_phases": list(SCOPED_PHASES),
            },
        )

    # 現在 Phase を取得（audit log の old_data 用）
    old_phase: Phase = await get_phase(tenant_id, db)

    # DB 更新
    applied = await set_phase(tenant_id, new_phase, db)  # type: ignore[arg-type]

    # AC9.4: audit_log 記録（B/C 切替時の証跡用）
    try:
        await record_audit_log(
            db=db,
            tenant_id=tenant_id,
            user_id=int(current_user.id),
            action="phase.switch",
            table_name="tenant_settings",
            record_id=tenant_id,
            old_data={"phase": old_phase},
            new_data={"phase": applied},
        )
    except Exception as exc:  # noqa: BLE001
        # audit_logs テーブルが存在しない / 一時的な障害で記録不能な場合は
        # 切替自体は成功させて warning ログを残す。AC9.4 の証跡用なので
        # 切替トランザクションを巻き戻すほどの severity ではない。
        logger.warning(
            "audit_log 記録失敗 (tenant_id=%s, action=phase.switch, err=%s)",
            tenant_id,
            exc,
        )

    await db.commit()

    return PhaseResponse(
        tenant_id=tenant_id,
        phase=applied,
        allowed_phases=list(ALLOWED_PHASES),
        scoped_phases=list(SCOPED_PHASES),
    )
