"""Sprint 9 / F9: スプレッドシート並走 Phase 判定サービス (spec v1.3)。

spec.md v1.3 F9 / AC9.1〜9.7:
  - Phase A (撤回済): ~~spreadsheet 並走~~ v1.3 で撤回。技術的には許可するが
    運用標準ではない (移行誤操作の戻し等の緊急用途のみ想定)。
  - Phase B (CRM 正本化): inventory_movements + products.stock_quantity を
    同一トランザクションで更新 (default、v1.3 標準運用)。
  - Phase C (GS 閉鎖): 同上 + 本格データ移行。Out-of-scope (別 ADR)。

  v1.3 では 'B' 標準運用、'A' は技術的に許可 (戻しのみ)、'C' は UI 上 disabled。

API:
  get_phase(tenant_id, db) -> Literal['A', 'B', 'C']
  should_update_stock_quantity(tenant_id, db) -> bool

使い方:
  from app.services.phase_gate import should_update_stock_quantity

  phase_ok = await should_update_stock_quantity(tenant_id=6, db=db)
  if phase_ok:
      # Phase B/C: products.stock_quantity を更新
      ...
  else:
      # Phase A (緊急戻し時のみ): skip + warning toast
      ...

呼出元:
  backend/app/services/inventory_movements.py (apply_inbound_items)

冪等性/キャッシュ:
  - 各呼出で 1 度 SELECT する（毎承認操作で <1ms、キャッシュ不要）。
  - tenant_settings 行が無い場合は 'B' を返す（v1.3 default、migration 080 と整合）。
"""

from __future__ import annotations

import logging
from typing import Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

Phase = Literal["A", "B", "C"]

# Sprint 9 v1.3: B 標準運用、A は技術的に許可 (緊急戻し用)、C は UI 上 disabled
ALLOWED_PHASES: tuple[Phase, ...] = ("A", "B", "C")
SCOPED_PHASES: tuple[Phase, ...] = ("A", "B")

# 後方互換 (一部の旧 import 経路のため一時的に残す。v1.3 移行完了後に削除予定)。
SCOPED_PHASES_V1_2: tuple[Phase, ...] = SCOPED_PHASES


async def get_phase(tenant_id: int, db: AsyncSession) -> Phase:
    """テナントの現在 Phase を返す。

    Args:
        tenant_id: public.tenants.id
        db: AsyncSession (同一トランザクション)

    Returns:
        'A' / 'B' / 'C' のいずれか。tenant_settings 行が無い場合は 'B' (v1.3 default)。

    Notes:
        - 単一テナントの Phase を返す SELECT 1 行のみ実行。トランザクション中断しない。
        - tenant_id が public.tenants に存在しない場合も 'B' を返す（warning ログのみ）。
    """
    row = (
        await db.execute(
            text(
                "SELECT spreadsheet_phase FROM public.tenant_settings "
                "WHERE tenant_id = :tid"
            ),
            {"tid": tenant_id},
        )
    ).first()
    if row is None:
        logger.warning(
            "tenant_settings に行がありません (tenant_id=%s)。デフォルト 'B' で続行 (v1.3)。",
            tenant_id,
        )
        return "B"
    phase_value = str(row[0])
    if phase_value not in ALLOWED_PHASES:
        logger.error(
            "tenant_settings.spreadsheet_phase 値が不正 (tenant_id=%s, value=%s)。'B' で fallback。",
            tenant_id,
            phase_value,
        )
        return "B"
    # mypy: cast via narrowing
    return phase_value  # type: ignore[return-value]


async def should_update_stock_quantity(tenant_id: int, db: AsyncSession) -> bool:
    """products.stock_quantity を更新すべきか判定する。

    spec v1.3 F9 / AC9.1:
      - Phase A (緊急戻し時のみ): False (GS が真値、CRM は inventory_movements 記録のみ)
      - Phase B/C: True (CRM が正本)

    Args:
        tenant_id: public.tenants.id
        db: AsyncSession

    Returns:
        Phase A → False、Phase B/C → True
    """
    phase = await get_phase(tenant_id, db)
    return phase != "A"


async def set_phase(
    tenant_id: int,
    new_phase: Phase,
    db: AsyncSession,
) -> Phase:
    """テナントの Phase を切り替える (UPSERT)。

    spec v1.3 F9 / AC9.3:
      'B' 標準運用、'A' (緊急戻し) も技術的に許可、'C' は Out-of-scope (別 ADR)。
      'C' を渡された場合は呼出側でエラーレスポンスを返す責務 (本サービスは DB 更新のみ実行)。

    Args:
        tenant_id: public.tenants.id
        new_phase: 'A' / 'B' / 'C'
        db: AsyncSession (同一トランザクションで commit は呼出側)

    Returns:
        DB 上の最新 Phase

    Raises:
        ValueError: new_phase が ALLOWED_PHASES に無い場合。
    """
    if new_phase not in ALLOWED_PHASES:
        raise ValueError(
            f"new_phase={new_phase!r} は ALLOWED_PHASES={ALLOWED_PHASES} のいずれかである必要があります"
        )
    row = (
        await db.execute(
            text(
                """
                INSERT INTO public.tenant_settings (tenant_id, spreadsheet_phase)
                VALUES (:tid, :phase)
                ON CONFLICT (tenant_id) DO UPDATE
                    SET spreadsheet_phase = EXCLUDED.spreadsheet_phase,
                        updated_at = NOW()
                RETURNING spreadsheet_phase
                """
            ),
            {"tid": tenant_id, "phase": new_phase},
        )
    ).first()
    if row is None:
        raise RuntimeError(
            f"tenant_settings UPSERT に失敗 (tenant_id={tenant_id}, phase={new_phase})"
        )
    return row[0]  # type: ignore[no-any-return]


__all__ = [
    "ALLOWED_PHASES",
    "Phase",
    "SCOPED_PHASES",
    "SCOPED_PHASES_V1_2",
    "get_phase",
    "set_phase",
    "should_update_stock_quantity",
]
