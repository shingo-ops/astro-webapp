"""
中央 admin 用 Discord Inbound 一覧 / 詳細 API。

spec.md v1.1 F5 (Sprint 5) / AC5.5:
  - require_super_admin で保護（is_super_admin=true のみ）
  - public.discord_inbound_messages を時系列降順で返す
  - parse_status / supplier_id / search クエリでフィルタ可能
  - 詳細 API で parse_result_json も返す（F6 レビュー UI が後段で参照）

API:
  GET /api/v1/super-admin/inbound/discord       一覧
  GET /api/v1/super-admin/inbound/discord/{id}  詳細
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_super_admin
from app.database import get_db
from app.schemas.discord_inbound import DiscordInboundDetail, DiscordInboundListItem

logger = logging.getLogger(__name__)

router = APIRouter()


_LIST_COLS = (
    "m.id, m.discord_message_id, m.discord_channel_id, m.supplier_id, "
    "m.raw_content, m.parse_status, m.parse_engine, "
    "m.received_at, m.llm_cost_usd, s.name AS supplier_name"
)

_DETAIL_COLS = (
    "m.id, m.discord_message_id, m.discord_channel_id, m.supplier_id, "
    "m.raw_content, m.parse_status, m.parse_engine, "
    "m.parse_result_json, m.received_at, m.exclude_reason, "
    "m.operator_comment, m.operator_id, m.approved_at, m.llm_cost_usd, "
    "m.created_at, m.updated_at, s.name AS supplier_name"
)

_PREVIEW_LEN = 200


def _row_to_list_item(row: dict) -> DiscordInboundListItem:
    raw = row.get("raw_content") or ""
    return DiscordInboundListItem(
        id=row["id"],
        discord_message_id=row["discord_message_id"],
        discord_channel_id=row["discord_channel_id"],
        supplier_id=row.get("supplier_id"),
        supplier_name=row.get("supplier_name"),
        raw_content_preview=raw[:_PREVIEW_LEN],
        parse_status=row["parse_status"],
        parse_engine=row.get("parse_engine"),
        received_at=row["received_at"],
        llm_cost_usd=row.get("llm_cost_usd"),
    )


@router.get(
    "/super-admin/inbound/discord",
    response_model=list[DiscordInboundListItem],
    dependencies=[Depends(require_super_admin)],
)
async def list_inbound(
    parse_status: str | None = Query(default=None, max_length=30),
    supplier_id: int | None = Query(default=None),
    q: str | None = Query(default=None, max_length=255),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    """Discord 受信メッセージ一覧。時系列降順。

    AC5.5: tenant_006 に予め INSERT した 3 件が新しい順で表示される。
    """
    offset = (page - 1) * per_page
    conditions: list[str] = []
    params: dict = {"limit": per_page, "offset": offset}

    if parse_status:
        conditions.append("m.parse_status = :status")
        params["status"] = parse_status
    if supplier_id is not None:
        conditions.append("m.supplier_id = :sup_id")
        params["sup_id"] = supplier_id
    if q:
        conditions.append("m.raw_content ILIKE :q")
        params["q"] = f"%{q}%"

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    sql = (
        f"SELECT {_LIST_COLS} "
        f"FROM public.discord_inbound_messages m "
        f"LEFT JOIN public.suppliers s ON s.id = m.supplier_id "
        f"{where} "
        f"ORDER BY m.received_at DESC, m.id DESC "
        f"LIMIT :limit OFFSET :offset"
    )
    result = await db.execute(text(sql), params)
    return [_row_to_list_item(dict(row)) for row in result.mappings().all()]


@router.get(
    "/super-admin/inbound/discord/{inbound_id}",
    response_model=DiscordInboundDetail,
    dependencies=[Depends(require_super_admin)],
)
async def get_inbound(
    inbound_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Discord 受信メッセージ詳細。parse_result_json 含む。"""
    result = await db.execute(
        text(
            f"SELECT {_DETAIL_COLS} "
            f"FROM public.discord_inbound_messages m "
            f"LEFT JOIN public.suppliers s ON s.id = m.supplier_id "
            f"WHERE m.id = :id"
        ),
        {"id": inbound_id},
    )
    row = result.mappings().first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="inbound not found"
        )
    return DiscordInboundDetail(
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
    )
