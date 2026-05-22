"""中央 admin 用 解析結果レビュー API (Sprint 6 F6)。

spec.md v1.1 F6 (Sprint 6) / AC6.1〜6.8:
  - require_super_admin で保護（is_super_admin=true のみ、AC6.8）
  - GET 詳細 / POST approve / POST reject の 3 エンドポイント
  - approve: parse_result_json 内の items を inventory_movements + products へ反映
  - reject: exclude_reason 必須 (AC6.4)
  - 楽観ロック: discord_inbound_messages.version で同時承認後勝ち禁止 (AC6.5)

A1 確定: 全件人手承認（自動承認なし）

API:
  GET  /api/v1/super-admin/parse-review/{inbound_id}
  POST /api/v1/super-admin/parse-review/{inbound_id}/approve
  POST /api/v1/super-admin/parse-review/{inbound_id}/reject
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_super_admin
from app.database import get_db
from app.models import User
from app.schemas.parse_review import (
    ApproveRequest,
    ApproveResponse,
    InventoryMovementSummary,
    ParseReviewDetail,
    RejectRequest,
    RejectResponse,
)
from app.services.inventory_movements import (
    InventoryApplyError,
    apply_inbound_items,
)

logger = logging.getLogger(__name__)

router = APIRouter()


_DETAIL_COLS = (
    "m.id, m.discord_message_id, m.discord_channel_id, m.supplier_id, "
    "m.raw_content, m.parse_status, m.parse_engine, "
    "m.parse_result_json, m.received_at, m.exclude_reason, "
    "m.operator_comment, m.operator_id, m.approved_at, m.llm_cost_usd, "
    "m.created_at, m.updated_at, m.version, "
    "s.name AS supplier_name"
)


def _row_to_detail(row: dict) -> ParseReviewDetail:
    return ParseReviewDetail(
        id=row["id"],
        discord_message_id=row["discord_message_id"],
        discord_channel_id=row["discord_channel_id"],
        supplier_id=row.get("supplier_id"),
        supplier_name=row.get("supplier_name"),
        raw_content=row["raw_content"],
        parse_status=row["parse_status"],
        parse_engine=row.get("parse_engine"),
        parse_result_json=row.get("parse_result_json"),
        received_at=row["received_at"],
        exclude_reason=row.get("exclude_reason"),
        operator_comment=row.get("operator_comment"),
        operator_id=row.get("operator_id"),
        approved_at=row.get("approved_at"),
        llm_cost_usd=row.get("llm_cost_usd"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        version=row.get("version") or 0,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _coerce_parse_result_json(value: Any) -> dict[str, Any]:
    """parse_result_json は JSONB なので dict のはずだが、稀に str/None も来る前提で正規化。"""
    if value is None:
        return {}
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return {}
    if isinstance(value, dict):
        return value
    return {}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/super-admin/parse-review/{inbound_id}",
    response_model=ParseReviewDetail,
    dependencies=[Depends(require_super_admin)],
)
async def get_review_detail(
    inbound_id: int,
    db: AsyncSession = Depends(get_db),
):
    """承認 / 差戻し対象 inbound の詳細を返す（楽観ロック version 含む）。

    AC6.1 entry point: 行単位 UI が parse_result_json.items を行に展開する。
    """
    row = (
        (
            await db.execute(
                text(
                    f"SELECT {_DETAIL_COLS} "
                    f"FROM public.discord_inbound_messages m "
                    f"LEFT JOIN public.suppliers s ON s.id = m.supplier_id "
                    f"WHERE m.id = :id"
                ),
                {"id": inbound_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="inbound not found"
        )
    return _row_to_detail(dict(row))


@router.post(
    "/super-admin/parse-review/{inbound_id}/approve",
    response_model=ApproveResponse,
)
async def approve_review(
    inbound_id: int,
    payload: ApproveRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_super_admin),
):
    """承認 → inventory_movements 反映 + products.stock_quantity 更新。

    AC6.1: items の delta_qty が products に反映される
    AC6.2: parse_status='approved', operator_id, operator_comment 保存
    AC6.3: skipped_indices を parse_result_json.skipped[] に保存
    AC6.5: version mismatch → 409 Conflict
    AC6.6: inventory_movements append-only + SUM = stock_quantity 不変条件
    """
    # 1. 現在の inbound 行を取得 + 楽観ロック値検証
    row = (
        (
            await db.execute(
                text(
                    "SELECT id, supplier_id, parse_result_json, parse_status, version "
                    "FROM public.discord_inbound_messages "
                    "WHERE id = :id "
                    "FOR UPDATE"
                ),
                {"id": inbound_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="inbound not found")

    current_version = int(row["version"] or 0)
    if current_version != payload.version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"version mismatch (expected {payload.version}, "
                f"server has {current_version}). Reload and retry."
            ),
        )

    # すでに approved/rejected な inbound への再 approve は禁止
    if row["parse_status"] in ("approved", "rejected"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"inbound already {row['parse_status']}; cannot approve again",
        )

    # 2. items を inventory_movements + products に反映（同一 transaction、commit せず）
    try:
        result = await apply_inbound_items(
            db,
            inbound_id=inbound_id,
            items=[i.model_dump() for i in payload.items],
            operator_id=int(current_user.id),
            supplier_id=row.get("supplier_id"),
        )
    except InventoryApplyError as e:
        # 業務エラーは 400。db.commit() していないので変更は破棄される。
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    # 3. parse_result_json.skipped[] を更新 (AC6.3)
    existing_parse_result = _coerce_parse_result_json(row.get("parse_result_json"))
    skipped_payload = list(payload.skipped_indices)
    if skipped_payload:
        existing_parse_result.setdefault("skipped", [])
        # 既存 skipped と union（重複排除、順序維持）
        seen = set(existing_parse_result["skipped"])
        for idx in skipped_payload:
            if idx not in seen:
                existing_parse_result["skipped"].append(idx)
                seen.add(idx)

    # 4. discord_inbound_messages 更新（version++、parse_status='approved'、approved_at、
    #    operator_id、operator_comment、parse_result_json）
    upd = (
        await db.execute(
            text(
                """
            UPDATE public.discord_inbound_messages
               SET parse_status     = 'approved',
                   version          = version + 1,
                   approved_at      = NOW(),
                   operator_id      = :op_id,
                   operator_comment = :op_cmt,
                   parse_result_json = :prj
             WHERE id = :id
               AND version = :ver
            RETURNING version
            """
            ),
            {
                "id": inbound_id,
                "ver": current_version,
                "op_id": int(current_user.id),
                "op_cmt": payload.operator_comment,
                "prj": json.dumps(existing_parse_result),
            },
        )
    ).first()
    if upd is None:
        # 別 admin が間に挟まった
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="version mismatch detected during update; concurrent approve.",
        )

    await db.commit()

    return ApproveResponse(
        inbound_id=inbound_id,
        parse_status="approved",
        version=int(upd[0]),
        movements=[
            InventoryMovementSummary(
                movement_id=m.movement_id,
                product_id=m.product_id,
                delta_qty=m.delta_qty,
                before_qty=m.before_qty,
                after_qty=m.after_qty,
            )
            for m in result.movements
        ],
        skipped_count=len(skipped_payload) + result.skipped,
        # Sprint 9 / F9 v1.2: Phase A 並走時に UI が warning toast を出すための情報
        skipped_stock_update=result.stock_quantity_skipped,
        phase=str(result.phase),
    )


@router.post(
    "/super-admin/parse-review/{inbound_id}/reject",
    response_model=RejectResponse,
)
async def reject_review(
    inbound_id: int,
    payload: RejectRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_super_admin),
):
    """差戻し → parse_status='rejected' + exclude_reason 記録、products 無変化。

    AC6.4: exclude_reason 必須（Pydantic で min_length=1 検証済）
    AC6.5: version mismatch → 409
    """
    # exclude_reason 空白だけは Pydantic を通り抜けるので明示弾く
    if not payload.exclude_reason.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="exclude_reason は必須です（空白のみは不可）",
        )

    row = (
        (
            await db.execute(
                text(
                    "SELECT id, parse_status, version "
                    "FROM public.discord_inbound_messages "
                    "WHERE id = :id FOR UPDATE"
                ),
                {"id": inbound_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="inbound not found")

    current_version = int(row["version"] or 0)
    if current_version != payload.version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"version mismatch (expected {payload.version}, "
                f"server has {current_version}). Reload and retry."
            ),
        )

    if row["parse_status"] in ("approved", "rejected"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"inbound already {row['parse_status']}; cannot reject again",
        )

    upd = (
        await db.execute(
            text(
                """
            UPDATE public.discord_inbound_messages
               SET parse_status   = 'rejected',
                   version        = version + 1,
                   exclude_reason = :reason,
                   operator_id    = :op_id
             WHERE id = :id
               AND version = :ver
            RETURNING version
            """
            ),
            {
                "id": inbound_id,
                "ver": current_version,
                "reason": payload.exclude_reason,
                "op_id": int(current_user.id),
            },
        )
    ).first()
    if upd is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="version mismatch detected during update; concurrent reject.",
        )

    await db.commit()
    return RejectResponse(
        inbound_id=inbound_id,
        parse_status="rejected",
        version=int(upd[0]),
        exclude_reason=payload.exclude_reason,
    )
