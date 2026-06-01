from __future__ import annotations

"""
リード管理API（CRUD＋案件変換）。

テナントスキーマの leads テーブルに対する操作を提供する。
見込度ランク（prospect_rank）は登録/更新時に温度感・規模・返信速度等から自動算出。

変更履歴:
  2026-04-16: 初版作成（Phase 1）
  2026-04-27: Phase 1-B-2 Step 5d — リード変換時の旧 customer_id 経路撤去
    （resolver / customer 経路廃止、company_id + contact_id を唯一の正に）
"""

import asyncio
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import (
    get_current_tenant,
    get_current_user,
    require_permission,
    tenant_table_ref,
)
from app.cache import invalidate_dashboard_cache
from app.database import get_db
from app.models import User
from app.schemas.lead import LeadConvertRequest, LeadCreate, LeadResponse, LeadUpdate
from app.services import encryption, meta_graph
from app.services import messaging_window as mw
from app.services.audit import record_audit_log
from app.services.meta_graph import (
    MetaGraphAPIError,
    MetaGraphError,
    MetaGraphRateLimitError,
    MetaGraphTimeoutError,
    MetaGraphTransportError,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# ADR-072 Phase 1: ローカル helper を削除し、`tenant_table_ref` を import 使用。


_LEAD_COLUMNS = """
    id, lead_code, customer_name, company_name, email, phone,
    source, type, status, temperature, estimated_scale, customer_type,
    response_speed, monthly_forecast, prospect_rank, assigned_to,
    converted_deal_id, notes, created_at, updated_at,
    next_action, next_action_date, challenge, meeting_memo, meeting_impression,
    cs_memo, sales_form, competitor_check, per_order_amount, monthly_frequency,
    nickname, country, target_titles,
    messenger_link, discord_id,
    instagram_link, whatsapp_link,
    discord_user_id, discord_dm_channel_id,
    discord_role_sync_status, discord_role_sync_at
"""

_UPDATABLE_COLUMNS = {
    "customer_name", "company_name", "email", "phone",
    "source", "type", "status", "temperature", "estimated_scale",
    "customer_type", "response_speed", "monthly_forecast",
    "prospect_rank", "assigned_to", "notes",
    # ADR-015 商談カルテフィールド
    "next_action", "next_action_date", "challenge", "meeting_memo",
    "meeting_impression", "cs_memo", "sales_form", "competitor_check",
    "per_order_amount", "monthly_frequency", "nickname", "country", "target_titles",
    # Migration 090: 連絡先リンク
    "messenger_link", "discord_id",
    # Migration 095: ソーシャルリンク
    "instagram_link", "whatsapp_link",
}


def compute_prospect_rank(
    temperature: str | None,
    estimated_scale: str | None,
    customer_type: str | None,
    response_speed: str | None,
    monthly_forecast: Decimal | None,
) -> str:
    """
    旧GAS版のアルゴリズムを踏襲した見込度ランク自動算出。

    ランク:
      A     = 信頼重視 + 大規模 + 24h以内返信
      B+    = 価格重視 + 大規模 + 24h以内返信
      B     = 価格重視 + 中小規模
      B-    = 上記B条件でやや反応鈍い
      仮C   = C判定要因1つ以上 + 顧客タイプ不明
      確定C = C判定要因4つ以上

    C判定要因はネガティブシグナルのみをカウントする。値が None（未設定）は
    ネガティブとはみなさず、カウントしない。これにより新規登録直後で情報
    が揃っていないリードが不当にCランク扱いされないようにしている。
    """
    c_factors = 0
    if response_speed == "3日超":
        c_factors += 1
    if estimated_scale == "Small":
        c_factors += 1
    if monthly_forecast is not None and monthly_forecast < Decimal("100000"):
        c_factors += 1
    # 温度感が明示的に Cold の場合のみペナルティ（Noneは未判定扱い）
    if customer_type == "価格重視" and temperature == "Cold":
        c_factors += 1

    if c_factors >= 4:
        return "確定C"

    if customer_type == "信頼重視" and estimated_scale == "Large" and response_speed == "24h以内":
        return "A"
    if customer_type == "価格重視" and estimated_scale == "Large" and response_speed == "24h以内":
        return "B+"
    if customer_type == "価格重視" and estimated_scale in ("Small", "Medium"):
        return "B-" if temperature == "Cold" else "B"

    if c_factors >= 1 and customer_type is None:
        return "仮C"

    return "B"


def _enum_to_str(value):
    """Enum型なら値を文字列化、そうでなければそのまま返す。"""
    if value is None:
        return None
    return value.value if hasattr(value, "value") else value


@router.get(
    "/leads",
    response_model=list[LeadResponse],
    dependencies=[Depends(require_permission("leads.view"))],
)
async def list_leads(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    status_filter: str | None = Query(default=None, alias="status"),
    assigned_to: int | None = Query(default=None),
    search: str | None = Query(default=None, max_length=255),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """リード一覧を取得する"""
    offset = (page - 1) * per_page
    conditions = []
    params: dict = {"limit": per_page, "offset": offset}

    if status_filter:
        conditions.append("status = :status")
        params["status"] = status_filter
    if assigned_to:
        conditions.append("assigned_to = :assigned_to")
        params["assigned_to"] = assigned_to
    if search:
        conditions.append(
            "(customer_name ILIKE :search OR company_name ILIKE :search "
            "OR email ILIKE :search OR lead_code ILIKE :search)"
        )
        params["search"] = f"%{search}%"

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    leads_t = tenant_table_ref(db, tenant_id, "leads")
    result = await db.execute(
        text(f"""
            SELECT {_LEAD_COLUMNS}
            FROM {leads_t}
            {where_clause}
            ORDER BY updated_at DESC
            LIMIT :limit OFFSET :offset
        """),
        params,
    )
    rows = result.mappings().all()
    return [LeadResponse(**row) for row in rows]


@router.get(
    "/leads/{lead_id}",
    response_model=LeadResponse,
    dependencies=[Depends(require_permission("leads.view"))],
)
async def get_lead(
    lead_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """リード詳細を取得する"""
    leads_t = tenant_table_ref(db, tenant_id, "leads")
    result = await db.execute(
        text(f"SELECT {_LEAD_COLUMNS} FROM {leads_t} WHERE id = :id"),
        {"id": lead_id},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="リードが見つかりません")
    return LeadResponse(**row)


@router.post(
    "/leads",
    response_model=LeadResponse,
    status_code=201,
    dependencies=[Depends(require_permission("leads.create"))],
)
async def create_lead(
    data: LeadCreate,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """リードを登録する（lead_codeは自動採番、prospect_rankは自動算出）"""
    rank = compute_prospect_rank(
        _enum_to_str(data.temperature),
        _enum_to_str(data.estimated_scale),
        _enum_to_str(data.customer_type),
        _enum_to_str(data.response_speed),
        data.monthly_forecast,
    )

    leads_t = tenant_table_ref(db, tenant_id, "leads")
    result = await db.execute(
        text(f"""
            INSERT INTO {leads_t} (
                tenant_id, customer_name, company_name, email, phone,
                source, type, status, temperature, estimated_scale, customer_type,
                response_speed, monthly_forecast, prospect_rank, assigned_to, notes
            )
            VALUES (
                :tenant_id, :customer_name, :company_name, :email, :phone,
                :source, :type, :status, :temperature, :estimated_scale, :customer_type,
                :response_speed, :monthly_forecast, :prospect_rank, :assigned_to, :notes
            )
            RETURNING id
        """),
        {
            "tenant_id": tenant_id,
            "customer_name": data.customer_name,
            "company_name": data.company_name,
            "email": data.email,
            "phone": data.phone,
            "source": data.source,
            "type": _enum_to_str(data.type),
            "status": _enum_to_str(data.status),
            "temperature": _enum_to_str(data.temperature),
            "estimated_scale": _enum_to_str(data.estimated_scale),
            "customer_type": _enum_to_str(data.customer_type),
            "response_speed": _enum_to_str(data.response_speed),
            "monthly_forecast": data.monthly_forecast,
            "prospect_rank": rank,
            "assigned_to": data.assigned_to,
            "notes": data.notes,
        },
    )
    new_id = result.scalar_one()

    # lead_code = LD-00001 形式で自動採番（Python側で生成してDB非依存）
    await db.execute(
        text(f"UPDATE {leads_t} SET lead_code = :code WHERE id = :id"),
        {"code": f"LD-{new_id:05d}", "id": new_id},
    )

    fetched = await db.execute(
        text(f"SELECT {_LEAD_COLUMNS} FROM {leads_t} WHERE id = :id"),
        {"id": new_id},
    )
    row = fetched.mappings().first()

    await record_audit_log(
        db=db, tenant_id=tenant_id, user_id=current_user.id,
        action="create", table_name="leads", record_id=new_id,
        new_data=data.model_dump(exclude_none=True, mode="json"),
    )
    await db.commit()
    await invalidate_dashboard_cache(tenant_id)
    try:
        from app.services.sse_pubsub import publish_leads_update
        await publish_leads_update(tenant_id)
    except Exception:
        logging.warning("[Leads] SSE publish 失敗（リード作成継続）: tenant_id=%s", tenant_id)

    return LeadResponse(**row)


@router.patch(
    "/leads/{lead_id}",
    response_model=LeadResponse,
    dependencies=[Depends(require_permission("leads.update"))],
)
async def update_lead(
    lead_id: int,
    data: LeadUpdate,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """リード情報を更新する（部分更新、prospect_rankは自動再計算）"""
    leads_t = tenant_table_ref(db, tenant_id, "leads")
    old_result = await db.execute(
        text(f"SELECT {_LEAD_COLUMNS} FROM {leads_t} WHERE id = :id"),
        {"id": lead_id},
    )
    old_row = old_result.mappings().first()
    if not old_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="リードが見つかりません")

    update_data = data.model_dump(exclude_unset=True)
    update_data = {k: v for k, v in update_data.items() if k in _UPDATABLE_COLUMNS}
    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="更新するフィールドを指定してください")

    # Enum→文字列変換
    for key in ("type", "status", "temperature", "estimated_scale", "customer_type", "response_speed"):
        if key in update_data and update_data[key] is not None:
            update_data[key] = _enum_to_str(update_data[key])

    # prospect_rank再計算（リード属性のいずれかが変わった場合）
    rank_fields = {"temperature", "estimated_scale", "customer_type", "response_speed", "monthly_forecast"}
    if rank_fields & update_data.keys():
        merged = {
            "temperature": update_data.get("temperature", old_row["temperature"]),
            "estimated_scale": update_data.get("estimated_scale", old_row["estimated_scale"]),
            "customer_type": update_data.get("customer_type", old_row["customer_type"]),
            "response_speed": update_data.get("response_speed", old_row["response_speed"]),
            "monthly_forecast": update_data.get("monthly_forecast", old_row["monthly_forecast"]),
        }
        update_data["prospect_rank"] = compute_prospect_rank(
            merged["temperature"], merged["estimated_scale"], merged["customer_type"],
            merged["response_speed"], merged["monthly_forecast"],
        )

    set_clauses = ", ".join(f"{k} = :{k}" for k in update_data)
    update_data["id"] = lead_id

    result = await db.execute(
        text(f"""
            UPDATE {leads_t} SET {set_clauses}, updated_at = NOW()
            WHERE id = :id
            RETURNING {_LEAD_COLUMNS}
        """),
        update_data,
    )
    row = result.mappings().first()

    await record_audit_log(
        db=db, tenant_id=tenant_id, user_id=current_user.id,
        action="update", table_name="leads", record_id=lead_id,
        old_data=dict(old_row), new_data=update_data,
    )
    await db.commit()
    await invalidate_dashboard_cache(tenant_id)
    try:
        from app.services.sse_pubsub import publish_leads_update
        await publish_leads_update(tenant_id)
    except Exception:
        logging.warning("[Leads] SSE publish 失敗（リード更新継続）: tenant_id=%s", tenant_id)

    # Discord ロール同期 (fire-and-forget, AC2.7)
    # estimated_scale が変更され、discord_user_id が設定されている場合のみ
    if "estimated_scale" in update_data:
        discord_user_id_val = str(row.get("discord_user_id") or "")
        new_scale_val = str(update_data.get("estimated_scale") or "")
        if discord_user_id_val and new_scale_val:
            try:
                from app.services.discord_role_sync import sync_lead_discord_role
                asyncio.create_task(
                    sync_lead_discord_role(
                        tenant_id=tenant_id,
                        lead_id=lead_id,
                        discord_user_id=discord_user_id_val,
                        new_scale=new_scale_val,
                    )
                )
            except Exception:
                logger.warning(
                    "[leads] Discord role sync task creation failed lead=%d", lead_id,
                )

    return LeadResponse(**row)


@router.delete(
    "/leads/{lead_id}",
    status_code=204,
    dependencies=[Depends(require_permission("leads.delete"))],
)
async def delete_lead(
    lead_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """リードを削除する"""
    leads_t = tenant_table_ref(db, tenant_id, "leads")
    old_result = await db.execute(
        text(f"SELECT {_LEAD_COLUMNS} FROM {leads_t} WHERE id = :id"),
        {"id": lead_id},
    )
    old_row = old_result.mappings().first()
    if not old_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="リードが見つかりません")

    await db.execute(text(f"DELETE FROM {leads_t} WHERE id = :id"), {"id": lead_id})
    await record_audit_log(
        db=db, tenant_id=tenant_id, user_id=current_user.id,
        action="delete", table_name="leads", record_id=lead_id,
        old_data=dict(old_row),
    )
    await db.commit()
    await invalidate_dashboard_cache(tenant_id)
    try:
        from app.services.sse_pubsub import publish_leads_update
        await publish_leads_update(tenant_id)
    except Exception:
        logging.warning("[Leads] SSE publish 失敗（リード削除継続）: tenant_id=%s", tenant_id)


@router.post(
    "/leads/{lead_id}/convert",
    response_model=LeadResponse,
    dependencies=[Depends(require_permission("leads.convert"))],
)
async def convert_lead(
    lead_id: int,
    data: LeadConvertRequest,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """
    リードを商談化する。新しいdealを作成し、leadを'商談中'ステータスに更新＋リンクする。

    同時実行対策:
      - deal作成後、`UPDATE leads ... WHERE converted_deal_id IS NULL` で
        アトミックにクレーム。並行変換でクレームに失敗した場合は
        作成済みdealと共にrollbackして409を返す。
    """
    leads_t = tenant_table_ref(db, tenant_id, "leads")
    contacts_t = tenant_table_ref(db, tenant_id, "contacts")
    deals_t = tenant_table_ref(db, tenant_id, "deals")
    lead_result = await db.execute(
        text(f"SELECT {_LEAD_COLUMNS} FROM {leads_t} WHERE id = :id"),
        {"id": lead_id},
    )
    lead_row = lead_result.mappings().first()
    if not lead_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="リードが見つかりません")
    if lead_row["converted_deal_id"] is not None:
        # 早期409（UXのため）。完全な保証は下のUPDATEで行う。
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="このリードは既に商談中です")

    # Step 5d: contact / company の存在 + 所属一致確認のみ
    contact_check = await db.execute(
        text(f"SELECT company_id FROM {contacts_t} WHERE id = :id"),
        {"id": data.contact_id},
    )
    contact_row = contact_check.first()
    if not contact_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="指定された担当者が見つかりません")
    if contact_row[0] != data.company_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="指定された担当者は指定会社に所属していません",
        )

    # 新案件作成（company_id + contact_id ベース）
    deal_result = await db.execute(
        text(f"""
            INSERT INTO {deals_t} (
                tenant_id, company_id, contact_id, lead_id, title, amount,
                currency, status, stage, probability, assigned_to, notes
            )
            VALUES (
                :tenant_id, :company_id, :contact_id, :lead_id, :title, :amount,
                'JPY', 'open', 'open', 10, :assigned_to, :notes
            )
            RETURNING id
        """),
        {
            "tenant_id": tenant_id,
            "company_id": data.company_id,
            "contact_id": data.contact_id,
            "lead_id": lead_id,
            "title": data.title,
            "amount": data.amount,
            # 担当者はリクエストで指定されたもの優先、省略時はリードの担当者を引き継ぐ
            "assigned_to": data.assigned_to if data.assigned_to is not None else lead_row["assigned_to"],
            "notes": data.notes,
        },
    )
    new_deal_id = deal_result.scalar_one()
    await db.execute(
        text(f"UPDATE {deals_t} SET deal_code = :code WHERE id = :id"),
        {"code": f"DL-{new_deal_id:05d}", "id": new_deal_id},
    )

    # アトミッククレーム: converted_deal_id IS NULL の場合のみ更新する
    # 並行リクエストで既に商談中になっていた場合は0行返却 → 例外で全ロールバック
    updated = await db.execute(
        text(f"""
            UPDATE {leads_t}
            SET status = '商談中', converted_deal_id = :deal_id, updated_at = NOW()
            WHERE id = :id AND converted_deal_id IS NULL
            RETURNING {_LEAD_COLUMNS}
        """),
        {"id": lead_id, "deal_id": new_deal_id},
    )
    row = updated.mappings().first()
    if not row:
        # 並行リクエストが先にクレームした。作成したdealも一緒にrollbackする。
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="このリードは既に商談中です（並行リクエスト）",
        )

    await record_audit_log(
        db=db, tenant_id=tenant_id, user_id=current_user.id,
        action="convert", table_name="leads", record_id=lead_id,
        old_data=dict(lead_row),
        new_data={"converted_deal_id": new_deal_id, "status": "商談中"},
    )
    await record_audit_log(
        db=db, tenant_id=tenant_id, user_id=current_user.id,
        action="create", table_name="deals", record_id=new_deal_id,
        new_data={
            "title": data.title,
            "company_id": data.company_id,
            "contact_id": data.contact_id,
            "lead_id": lead_id,
            "amount": str(data.amount) if data.amount is not None else None,
        },
    )
    await db.commit()
    await invalidate_dashboard_cache(tenant_id)

    return LeadResponse(**row)


# ---------------------------------------------------------------------------
# Phase 1-D Sprint 4: メッセージ取得 + 既読マーク
# ---------------------------------------------------------------------------
#
# spec §5-4 / §5-6 に従い、Inbox の右ペインで使う endpoints をここに定義する。
#
# 設計判断:
#   - meta_inbox.py（OAuth / Channels）と分離した本ファイルに置く理由は spec §8-2:
#     "leads.py の既存 CRUD を維持しつつメッセージ周りも leads ドメインに含める"。
#     URL も /leads/{id}/messages 系列で統一できる。
#   - SQLite テスト互換を保つため、SQLite に存在しない PostgreSQL 専用機能は
#     使わない（本 endpoint は単純な SELECT / UPDATE のみ）。
#   - tenant 分離は RLS（PostgreSQL）に加えて WHERE 句でも tenant_id を必須にし、
#     SQLite テストでも他テナント漏れを防ぐ。

# 24h / 7d は spec §3-3, §5-4 の messaging window
# Sprint 5 で `app.services.messaging_window` に切り出した。本ファイルでは
# `mw.compute_window(...)` を呼ぶラッパだけ残す（Sprint 4 Reviewer F5 対応）。


def _meta_msg_format_dt(value) -> Optional[str]:
    """meta_messages の datetime / 文字列 / None を ISO 文字列に正規化。

    meta_inbox.py._format_dt と同じ仕様だが、循環 import を避けるため別関数で持つ。
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _meta_msg_parse_aware(value) -> Optional[datetime]:
    """datetime / 文字列 / None → tz-aware datetime（UTC 仮定）。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    s = str(value).strip()
    if not s:
        return None
    s_iso = s.replace(" ", "T", 1)
    try:
        dt = datetime.fromisoformat(s_iso)
    except ValueError:
        try:
            dt = datetime.fromisoformat(s_iso + "+00:00")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _compute_messaging_window(last_inbound_at: Optional[datetime]) -> dict:
    """spec §5-4 の messaging_window 構造体を組み立てる。

    Sprint 5 で `app.services.messaging_window.compute_window` に実装を移譲。
    本関数は後方互換のための薄いラッパ（既存呼び出し元の API は変えない）。
    """
    return mw.compute_window(last_inbound_at)


@router.get(
    "/leads/{lead_id}/messages",
    dependencies=[Depends(require_permission("messaging.view"))],
)
async def list_lead_messages(
    lead_id: int,
    before: Optional[int] = Query(default=None, description="この id より小さい meta_messages.id を取得"),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """指定 lead のメッセージ一覧 + lead 概要 + messaging_window を返す（spec §5-4）。

    並び順: 古い順（created_at ASC, id ASC）— Inbox UI で上から古い順表示するため。
    pagination: `before=<id>` で『その id より古い id』に絞る（無限スクロール用途）。

    エラー:
        - lead が同テナントに存在しない → 404
    """
    # lead 存在 + tenant 確認（RLS が PostgreSQL でテナント分離するが、SQLite では
    # WHERE で tenant_id を必須にする）
    leads_t = tenant_table_ref(db, tenant_id, "leads")
    meta_messages_t = tenant_table_ref(db, tenant_id, "meta_messages")
    lead_result = await db.execute(
        text(f"SELECT {_LEAD_COLUMNS} FROM {leads_t} WHERE id = :id AND tenant_id = :tenant_id"),
        {"id": lead_id, "tenant_id": tenant_id},
    )
    lead_row = lead_result.mappings().first()
    if not lead_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="リードが見つかりません",
        )

    # messages 取得
    where = ["lead_id = :lead_id", "tenant_id = :tenant_id"]
    params: dict = {"lead_id": lead_id, "tenant_id": tenant_id, "limit": limit}
    if before is not None:
        where.append("id < :before")
        params["before"] = before
    where_sql = " AND ".join(where)

    # attachment_url/attachment_type は migration 097 以降のカラム。未適用環境は graceful fallback。
    try:
        msg_result = await db.execute(
            text(f"""
                SELECT
                    id, platform, sender_id, sender_name, message_text, direction,
                    message_id, recipient_id, messaging_type, message_tag,
                    sent_by_staff_id, error_code, error_message,
                    seen_at, seen_by_staff_id,
                    created_at, attachment_url, attachment_type
                FROM {meta_messages_t}
                WHERE {where_sql}
                ORDER BY created_at ASC, id ASC
                LIMIT :limit
            """),
            params,
        )
        msg_rows = msg_result.mappings().all()
        _has_attachment_cols = True
    except Exception:
        # attachment_url/attachment_type カラム未適用テナント / テスト環境
        msg_result = await db.execute(
            text(f"""
                SELECT
                    id, platform, sender_id, sender_name, message_text, direction,
                    message_id, recipient_id, messaging_type, message_tag,
                    sent_by_staff_id, error_code, error_message,
                    seen_at, seen_by_staff_id,
                    created_at
                FROM {meta_messages_t}
                WHERE {where_sql}
                ORDER BY created_at ASC, id ASC
                LIMIT :limit
            """),
            params,
        )
        msg_rows = msg_result.mappings().all()
        _has_attachment_cols = False

    messages = [
        {
            "id": r["id"],
            "platform": r["platform"],
            "sender_id": r["sender_id"],
            "sender_name": r["sender_name"],
            "message_text": r["message_text"],
            "direction": r["direction"],
            "message_id": r["message_id"],
            "recipient_id": r["recipient_id"],
            "messaging_type": r["messaging_type"],
            "message_tag": r["message_tag"],
            "sent_by_staff_id": r["sent_by_staff_id"],
            "error_code": r["error_code"],
            "error_message": r["error_message"],
            "seen_at": _meta_msg_format_dt(r["seen_at"]),
            "seen_by_staff_id": r["seen_by_staff_id"],
            "created_at": _meta_msg_format_dt(r["created_at"]),
            "attachment_url": r["attachment_url"] if _has_attachment_cols else None,
            "attachment_type": r["attachment_type"] if _has_attachment_cols else None,
        }
        for r in msg_rows
    ]

    # platform は messages 末尾の最新値を採用（pagination 対象外）
    latest_platform: Optional[str] = None
    if messages:
        latest_platform = messages[-1]["platform"]
    else:
        plat_q = await db.execute(
            text(
                f"SELECT platform FROM {meta_messages_t} "
                "WHERE lead_id = :lead_id AND tenant_id = :tenant_id "
                "ORDER BY created_at DESC, id DESC LIMIT 1"
            ),
            {"lead_id": lead_id, "tenant_id": tenant_id},
        )
        plat_row = plat_q.first()
        if plat_row:
            latest_platform = plat_row[0]

    # last_inbound_at（messaging_window 用）— pagination の影響を受けないように
    # フィルタ無しで再クエリ
    inbound_q = await db.execute(
        text(
            f"SELECT MAX(created_at) FROM {meta_messages_t} "
            "WHERE lead_id = :lead_id AND tenant_id = :tenant_id "
            "AND direction = 'inbound'"
        ),
        {"lead_id": lead_id, "tenant_id": tenant_id},
    )
    last_inbound_raw = inbound_q.scalar()
    last_inbound_at = _meta_msg_parse_aware(last_inbound_raw)

    # Discord は 24h 制限なし → 常に送信可能
    if latest_platform == "discord":
        messaging_window: dict = {
            "last_inbound_at": None,
            "expires_at": None,
            "can_send_response": True,
            "requires_human_agent_tag": False,
            "can_send_at_all": True,
        }
    else:
        messaging_window = _compute_messaging_window(last_inbound_at)

    return {
        "messages": messages,
        "lead": {
            "id": lead_row["id"],
            "lead_code": lead_row["lead_code"],
            "customer_name": lead_row["customer_name"],
            "platform": latest_platform,
            "source": lead_row["source"],
        },
        "messaging_window": messaging_window,
    }


@router.post(
    "/leads/{lead_id}/messages/mark-read",
    dependencies=[Depends(require_permission("messaging.view"))],
)
async def mark_lead_messages_read(
    lead_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """指定 lead の inbound 未読メッセージに seen_at を設定（spec §5-6）。

    動作:
        - direction='inbound' AND seen_at IS NULL の行に seen_at=NOW(),
          seen_by_staff_id=<current> を UPDATE
        - 該当 lead が同テナントに無い場合は 404

    返却: { "marked_count": N }

    Meta 側 mark_seen Send API は呼ばない（DB のみで管理）。Meta 既読同期は
    out of scope（spec §5-6 注記）。
    """
    leads_t = tenant_table_ref(db, tenant_id, "leads")
    staff_t = tenant_table_ref(db, tenant_id, "staff")
    meta_messages_t = tenant_table_ref(db, tenant_id, "meta_messages")
    lead_q = await db.execute(
        text(f"SELECT id FROM {leads_t} WHERE id = :id AND tenant_id = :tenant_id"),
        {"id": lead_id, "tenant_id": tenant_id},
    )
    if lead_q.first() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="リードが見つかりません",
        )

    # 現 staff の解決（user.email → staff.id）
    staff_id: Optional[int] = None
    if current_user.email:
        try:
            sr = await db.execute(
                text(f"SELECT id FROM {staff_t} WHERE primary_email = :email "
                     "ORDER BY id ASC LIMIT 1"),
                {"email": current_user.email},
            )
            row = sr.first()
            if row:
                staff_id = int(row[0])
        except Exception:
            staff_id = None

    upd = await db.execute(
        text(f"""
            UPDATE {meta_messages_t}
            SET seen_at = NOW(),
                seen_by_staff_id = :staff_id
            WHERE lead_id = :lead_id
              AND tenant_id = :tenant_id
              AND direction = 'inbound'
              AND seen_at IS NULL
        """),
        {"lead_id": lead_id, "tenant_id": tenant_id, "staff_id": staff_id},
    )
    marked = int(upd.rowcount or 0)

    # Phase 1-E F9-S4 (Sprint 4 Reviewer F2): mark-read アクションを audit_log に記録。
    # 既読化の事実を残す。失敗時はログのみ（ユーザー操作は中断しない）。
    # firebase_uid 列追加は別 follow-up（F9-S4 拡張版）。現状は user_id (DB id) のみ。
    if marked > 0:
        try:
            await record_audit_log(
                db=db,
                tenant_id=tenant_id,
                user_id=current_user.id,
                action="mark_messages_read",
                table_name="meta_messages",
                record_id=lead_id,
                new_data={
                    "marked_count": marked,
                    "lead_id": lead_id,
                    "staff_id": staff_id,
                },
            )
        except Exception:
            # audit_logs テーブル不在 (テスト環境) や DB 障害でも機能を止めない
            logger.exception(
                "audit_log 記録失敗 (mark_messages_read), lead_id=%s",
                lead_id,
            )

    await db.commit()

    return {"marked_count": marked}


# ---------------------------------------------------------------------------
# ADR-088: メッセージ翻訳
# ---------------------------------------------------------------------------


class _TranslateRequest(BaseModel):
    """翻訳リクエスト body。"""
    target_language: str = Field(min_length=2, max_length=10)


@router.post(
    "/leads/{lead_id}/messages/{message_id}/translate",
    dependencies=[Depends(require_permission("messaging.view"))],
)
async def translate_message_endpoint(
    lead_id: int,
    message_id: str,
    body: _TranslateRequest,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """指定メッセージを AI 翻訳する（ADR-088）。

    キャッシュヒット時は Gemini 未呼び出しで即返却。
    予算超過時は 429 を返す。
    """
    from app.services.inventory_parser_llm import LLMConfigError, LLMParseError
    from app.services.message_translator import (
        BudgetExceededError,
        translate_message,
    )

    if not message_id or message_id.strip() == "":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="message_id is required",
        )

    # lead 存在確認
    leads_t = tenant_table_ref(db, tenant_id, "leads")
    lead_q = await db.execute(
        text(f"SELECT id FROM {leads_t} WHERE id = :id AND tenant_id = :tenant_id"),
        {"id": lead_id, "tenant_id": tenant_id},
    )
    if lead_q.first() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="リードが見つかりません",
        )

    # message 存在確認 & テキスト取得
    meta_messages_t = tenant_table_ref(db, tenant_id, "meta_messages")
    msg_q = await db.execute(
        text(
            f"SELECT message_text FROM {meta_messages_t} "
            "WHERE message_id = :message_id AND lead_id = :lead_id AND tenant_id = :tenant_id"
        ),
        {"message_id": message_id, "lead_id": lead_id, "tenant_id": tenant_id},
    )
    msg_row = msg_q.first()
    if msg_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="メッセージが見つかりません",
        )

    message_text = msg_row[0]
    if not message_text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="メッセージ本文が空です",
        )

    translations_t = tenant_table_ref(db, tenant_id, "message_translations")

    try:
        result = await translate_message(
            db=db,
            tenant_id=tenant_id,
            table_ref=translations_t,
            message_id=message_id,
            message_text=message_text,
            target_language=body.target_language,
        )
    except BudgetExceededError:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="LLM budget exceeded for this month",
        )
    except LLMConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )
    except LLMParseError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        )

    return {
        "translated_text": result.translated_text,
        "cached": result.cached,
        "engine": result.engine,
    }


# ---------------------------------------------------------------------------
# Phase 1-D Sprint 5: メッセージ送信
# ---------------------------------------------------------------------------
#
# spec §5-5 / §3-3 に従い、Inbox の右ペインから返信を Meta に送る endpoint を実装する。
#
# フロー:
#   1. lead_id が同テナントに存在するか確認（404）
#   2. text のバリデーション（空 / 長すぎ → 400）
#   3. last_inbound_at 取得 → messaging_window.compute_state で 24h/7d 判定
#      - EXPIRED / NO_INBOUND → 400
#      - WITHIN_24H or WITHIN_HUMAN_AGENT → (messaging_type, tag) 決定
#      - force_human_agent_tag=True で 24h 以内でも HUMAN_AGENT に上書き（spec §5-5）
#   4. tenant_meta_config から該当 Page の access_token を Fernet 復号
#      - platform=messenger → page_id ベースで解決
#      - platform=instagram → ig_business_account_id ベースで解決
#   5. Meta Send API 呼び出し（Messenger: /me/messages, Instagram: /{ig_user_id}/messages）
#      - エラー → meta_messages に書かず 502 返却 + audit_log
#      - 成功 → meta_messages に direction='outbound' で INSERT
#   6. 返却: {id, message_id, messaging_type, message_tag, sent_at}

# Meta テキストメッセージの最大長（Send API 制約）。spec で明記なし、Meta Docs ベース。
_MESSAGE_TEXT_MAX_LEN = 2000


class _SendMessageRequest(BaseModel):
    """spec §5-5 リクエスト body。"""
    text: str = Field(min_length=1, max_length=_MESSAGE_TEXT_MAX_LEN)


def _extract_recipient_id(source: Optional[str], inbound_sender_id: Optional[str]) -> Optional[str]:
    """送信先 PSID / IGSID を決める。

    優先順:
      1) leads.source が `messenger:PSID` / `instagram:IGSID` 形式ならコロン後を採用
      2) 直近 inbound メッセージの sender_id を fallback で使用

    inbound 履歴ベースが最も堅牢（OAuth 接続前の旧 lead でも source が空のケースに対応）。
    """
    if source and ":" in source:
        prefix, _, value = source.partition(":")
        if prefix in ("messenger", "instagram") and value:
            return value
    if inbound_sender_id:
        return inbound_sender_id
    return None


def _decode_token_blob(value) -> str:
    """tenant_meta_config.page_access_token_encrypted を str に変換。

    BYTEA / memoryview / bytes / str いずれにも対応。
    """
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).decode("ascii")
    return str(value)


@router.post(
    "/leads/{lead_id}/messages",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("messaging.send"))],
)
async def send_lead_message(
    lead_id: int,
    payload: _SendMessageRequest,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """指定 lead に Meta 経由でメッセージを送信する（spec §5-5）。

    `messaging_window` を再評価し、24h/7d ルールに沿って `messaging_type` /
    `message_tag` を自動セット。送信成功時は meta_messages に
    `direction='outbound'` で記録、失敗時は記録しない（リトライは MVP 範囲外）。

    エラー:
        400: text 不正 / 7d 超過 / inbound 履歴なし / platform が messenger/instagram でない
        404: lead が同テナントに存在しない
        409: 同 Page の `tenant_meta_config` が見つからない（OAuth 未接続）
        502: Meta Send API がエラー / タイムアウト
    """
    # ----- (1) lead 存在 + tenant 確認 -----
    leads_t = tenant_table_ref(db, tenant_id, "leads")
    meta_messages_t = tenant_table_ref(db, tenant_id, "meta_messages")
    tenant_meta_config_t = tenant_table_ref(db, tenant_id, "tenant_meta_config")
    staff_t = tenant_table_ref(db, tenant_id, "staff")
    lead_q = await db.execute(
        text(f"SELECT {_LEAD_COLUMNS} FROM {leads_t} "
             "WHERE id = :id AND tenant_id = :tenant_id"),
        {"id": lead_id, "tenant_id": tenant_id},
    )
    lead_row = lead_q.mappings().first()
    if not lead_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="リードが見つかりません",
        )

    text_body = payload.text.strip()
    if not text_body:
        # 空白のみは拒否（max_length は Pydantic で済み）
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="本文が空です",
        )

    # ----- (2) 直近 inbound 取得 + platform 推論 -----
    inbound_q = await db.execute(
        text(f"""
            SELECT created_at, sender_id, platform
            FROM {meta_messages_t}
            WHERE lead_id = :lead_id
              AND tenant_id = :tenant_id
              AND direction = 'inbound'
            ORDER BY created_at DESC, id DESC
            LIMIT 1
        """),
        {"lead_id": lead_id, "tenant_id": tenant_id},
    )
    inbound_row = inbound_q.first()
    if inbound_row is None:
        last_inbound_at = None
        inbound_sender_id = None
        inbound_platform = None
    else:
        last_inbound_at = _meta_msg_parse_aware(inbound_row[0])
        inbound_sender_id = inbound_row[1]
        inbound_platform = inbound_row[2]

    # platform 推論: 直近 inbound > leads.source プレフィクス > エラー
    platform = inbound_platform
    source_str = lead_row.get("source") if hasattr(lead_row, "get") else lead_row["source"]
    if not platform and source_str:
        if isinstance(source_str, str) and ":" in source_str:
            prefix = source_str.split(":", 1)[0]
            if prefix in ("messenger", "instagram", "discord"):
                platform = prefix
    if platform not in ("messenger", "instagram", "discord"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="このリードはメッセージング連携されていないため送信できません",
        )

    # ----- (2b) Discord 送信経路（messaging_window 不要）-----
    if platform == "discord":
        return await _send_discord_message(
            db=db,
            tenant_id=tenant_id,
            lead_id=lead_id,
            lead_row=lead_row,
            text_body=text_body,
            current_user=current_user,
        )

    # ----- (3) messaging window 判定（Meta のみ）-----
    state = mw.compute_state(last_inbound_at)
    messaging_type, message_tag = mw.messaging_type_for_state(state)
    if messaging_type is None:
        # EXPIRED or NO_INBOUND → 送信不可
        if state == mw.WindowState.EXPIRED:
            detail = "メッセージウィンドウを超過しています（受信から 7 日以上経過）"
        else:
            detail = "受信履歴がないため送信できません（最初のメッセージは顧客側からの必要があります）"
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail,
        )

    # ----- (4) recipient_id 解決 -----
    recipient_id = _extract_recipient_id(source_str, inbound_sender_id)
    if not recipient_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="送信先 ID が解決できません（lead.source / 受信履歴がいずれも未設定）",
        )

    # ----- (5) tenant_meta_config から Page Access Token を復号 -----
    if platform == "messenger":
        token_q = await db.execute(
            text(f"""
                SELECT id, page_id, page_access_token_encrypted, instagram_business_account_id
                FROM {tenant_meta_config_t}
                WHERE tenant_id = :tenant_id AND is_active = TRUE
                ORDER BY connected_at DESC, id DESC
                LIMIT 1
            """),
            {"tenant_id": tenant_id},
        )
    else:
        # instagram: ig_business_account_id がセットされている行を優先
        token_q = await db.execute(
            text(f"""
                SELECT id, page_id, page_access_token_encrypted, instagram_business_account_id
                FROM {tenant_meta_config_t}
                WHERE tenant_id = :tenant_id
                  AND is_active = TRUE
                  AND instagram_business_account_id IS NOT NULL
                ORDER BY connected_at DESC, id DESC
                LIMIT 1
            """),
            {"tenant_id": tenant_id},
        )
    config_row = token_q.first()
    if config_row is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="送信に使う Meta 接続が見つかりません（Channels 設定で接続してください）",
        )
    config_id, page_id_for_send, encrypted_token_blob, ig_business_id = (
        int(config_row[0]),
        config_row[1],
        config_row[2],
        config_row[3],
    )
    try:
        page_access_token = encryption.decrypt(_decode_token_blob(encrypted_token_blob))
    except encryption.EncryptionError as e:
        logger.error("Page Access Token 復号失敗: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="保存トークンの復号に失敗しました（鍵不一致の可能性）",
        )

    # ----- (6) Meta Send API 呼び出し -----
    meta_error_payload: Optional[dict] = None
    try:
        if platform == "messenger":
            send_result = await meta_graph.send_messenger_message(
                page_access_token=page_access_token,
                recipient_id=recipient_id,
                text=text_body,
                messaging_type=messaging_type,
                tag=message_tag,
                # Send API は /me/messages でも可だが、複数 Page 接続時の安全性のため page_id 明示
                page_id=str(page_id_for_send) if page_id_for_send else "me",
            )
        else:  # instagram
            if not ig_business_id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Instagram Business Account が紐づいていません",
                )
            send_result = await meta_graph.send_instagram_message(
                page_access_token=page_access_token,
                page_id=str(page_id_for_send) if page_id_for_send else "me",
                recipient_id=recipient_id,
                text=text_body,
                messaging_type=messaging_type,
                tag=message_tag,
            )
    except MetaGraphRateLimitError as e:
        logger.warning("Meta Send API rate limit for lead %s: retry_after=%s", lead_id, e.retry_after)
        await _record_send_audit_safely(
            db, tenant_id=tenant_id, user_id=current_user.id,
            action="meta_message_send_failed", record_id=config_id,
            new_data={
                "lead_id": lead_id,
                "platform": platform,
                "messaging_type": messaging_type,
                "message_tag": message_tag,
                "meta_error": e.to_audit_dict(),
            },
        )
        rate_detail: dict = {"message": "Meta APIのレート制限に達しました"}
        if e.retry_after:
            rate_detail["retry_after"] = e.retry_after
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=rate_detail)
    except MetaGraphTimeoutError as e:
        logger.warning("Meta Send API timeout for lead %s: %s", lead_id, e)
        await _record_send_audit_safely(
            db, tenant_id=tenant_id, user_id=current_user.id,
            action="meta_message_send_failed", record_id=config_id,
            new_data={
                "lead_id": lead_id,
                "platform": platform,
                "messaging_type": messaging_type,
                "message_tag": message_tag,
                "transport_error": str(e),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Meta Send API がタイムアウトしました",
        )
    except MetaGraphAPIError as e:
        meta_error_payload = e.to_audit_dict()
        logger.warning("Meta Send API error for lead %s: %s", lead_id, e.error_type)
        await _record_send_audit_safely(
            db, tenant_id=tenant_id, user_id=current_user.id,
            action="meta_message_send_failed", record_id=config_id,
            new_data={
                "lead_id": lead_id,
                "platform": platform,
                "messaging_type": messaging_type,
                "message_tag": message_tag,
                "meta_error": meta_error_payload,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "detail": "Meta Send API がエラーを返しました",
                "error_code": e.error_code,
                "error_type": e.error_type,
            },
        )
    except MetaGraphError as e:
        logger.warning("Meta Send transport error for lead %s: %s", lead_id, e)
        await _record_send_audit_safely(
            db, tenant_id=tenant_id, user_id=current_user.id,
            action="meta_message_send_failed", record_id=config_id,
            new_data={
                "lead_id": lead_id,
                "platform": platform,
                "messaging_type": messaging_type,
                "message_tag": message_tag,
                "transport_error": str(e),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Meta Send API への接続に失敗しました",
        )

    # ----- (7) sent_by_staff_id 解決（mark-read と同パターン） -----
    sent_by_staff_id: Optional[int] = None
    if current_user.email:
        try:
            sr = await db.execute(
                text(f"SELECT id FROM {staff_t} WHERE primary_email = :email "
                     "ORDER BY id ASC LIMIT 1"),
                {"email": current_user.email},
            )
            row = sr.first()
            if row:
                sent_by_staff_id = int(row[0])
        except Exception:
            sent_by_staff_id = None

    # ----- (8) meta_messages に outbound 行 INSERT -----
    sender_id = page_id_for_send if platform == "messenger" else (ig_business_id or page_id_for_send)
    # Phase 1-E F14-S5: outbound 行も page_id を埋める（Page フィルタ適用時に
    # 送信直後の会話が一覧から消えないようにする）
    # Messenger: tenant_meta_config 由来の page_id_for_send を保存
    # Instagram: 当面 NULL（inbound IG と整合、F14-FU1 で対応）
    page_id_for_message = page_id_for_send if platform == "messenger" else None
    insert_params = {
        "tenant_id": tenant_id,
        "lead_id": lead_id,
        "platform": platform,
        "sender_id": str(sender_id) if sender_id is not None else None,
        "text": text_body,
        "message_id": send_result.get("message_id"),
        "recipient_id": recipient_id,
        "messaging_type": messaging_type,
        "message_tag": message_tag,
        "sent_by_staff_id": sent_by_staff_id,
        "page_id": page_id_for_message,
    }
    insert_result = await db.execute(
        text(f"""
            INSERT INTO {meta_messages_t} (
                tenant_id, lead_id, platform, sender_id, message_text,
                direction, message_id, recipient_id,
                messaging_type, message_tag, sent_by_staff_id, page_id, created_at
            )
            VALUES (
                :tenant_id, :lead_id, :platform, :sender_id, :text,
                'outbound', :message_id, :recipient_id,
                :messaging_type, :message_tag, :sent_by_staff_id, :page_id, NOW()
            )
            RETURNING id, created_at
        """),
        insert_params,
    )
    new_row = insert_result.first()
    if new_row is None:
        # RETURNING 非対応の SQLite 古バージョンへの保険
        await db.execute(
            text(f"""
                INSERT INTO {meta_messages_t} (
                    tenant_id, lead_id, platform, sender_id, message_text,
                    direction, message_id, recipient_id,
                    messaging_type, message_tag, sent_by_staff_id, page_id, created_at
                )
                VALUES (
                    :tenant_id, :lead_id, :platform, :sender_id, :text,
                    'outbound', :message_id, :recipient_id,
                    :messaging_type, :message_tag, :sent_by_staff_id, :page_id, NOW()
                )
            """),
            insert_params,
        )
        # last_insert_rowid で id を取得
        last_id_row = await db.execute(text("SELECT last_insert_rowid(), CURRENT_TIMESTAMP"))
        new_id_row = last_id_row.first()
        new_id = int(new_id_row[0]) if new_id_row else 0
        new_created_at = new_id_row[1] if new_id_row else None
    else:
        new_id = int(new_row[0])
        new_created_at = new_row[1]

    await _record_send_audit_safely(
        db, tenant_id=tenant_id, user_id=current_user.id,
        action="meta_message_sent", record_id=new_id,
        new_data={
            "lead_id": lead_id,
            "platform": platform,
            "messaging_type": messaging_type,
            "message_tag": message_tag,
            "message_id": send_result.get("message_id"),
        },
    )

    await db.commit()

    return {
        "id": new_id,
        "message_id": send_result.get("message_id"),
        "messaging_type": messaging_type,
        "message_tag": message_tag,
        "sent_at": _meta_msg_format_dt(new_created_at),
        "lead_id": lead_id,
        "platform": platform,
    }


async def _record_send_audit_safely(
    db: AsyncSession,
    *,
    tenant_id: int,
    user_id: int,
    action: str,
    record_id: int,
    new_data: dict,
) -> None:
    """Send 経路の audit_log 記録の例外を握りつぶす（送信本体を守る）。"""
    try:
        await record_audit_log(
            db=db, tenant_id=tenant_id, user_id=user_id,
            action=action, table_name="meta_messages", record_id=record_id,
            new_data=new_data,
        )
    except Exception:
        logger.warning("audit_log 記録に失敗（無視して継続）", exc_info=True)


# ---------------------------------------------------------------------------
# Discord DM 送信ヘルパ
# ---------------------------------------------------------------------------


async def _send_discord_message(
    *,
    db: AsyncSession,
    tenant_id: int,
    lead_id: int,
    lead_row,
    text_body: str,
    current_user,
) -> dict:
    """Discord DM 経由でメッセージを送信し、meta_messages に outbound 行を INSERT して返す。

    messaging_window 制約なし（Discord は 24h 制限を持たない）。
    discord_dm_channel_id が未設定（顧客からのメッセージ受信前）の場合は 409。
    Bot Token が未設定の場合も 409。
    Discord API エラーは 502。
    """
    from app.services.discord_sender import DiscordSendError, send_discord_dm

    leads_t = tenant_table_ref(db, tenant_id, "leads")
    meta_messages_t = tenant_table_ref(db, tenant_id, "meta_messages")
    staff_t = tenant_table_ref(db, tenant_id, "staff")

    # discord_dm_channel_id を leads から取得
    ch_q = await db.execute(
        text(f"SELECT discord_user_id, discord_dm_channel_id FROM {leads_t} "
             "WHERE id = :id AND tenant_id = :tenant_id"),
        {"id": lead_id, "tenant_id": tenant_id},
    )
    ch_row = ch_q.first()
    if ch_row is None or not ch_row[1]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Discord DM チャンネルが設定されていません。"
                "顧客から先にメッセージを受信すると自動設定されます。"
            ),
        )
    discord_user_id = ch_row[0]
    dm_channel_id = str(ch_row[1])

    # Discord Bot API で送信
    try:
        discord_msg_id = await send_discord_dm(
            tenant_id=tenant_id,
            dm_channel_id=dm_channel_id,
            text=text_body,
        )
    except DiscordSendError as e:
        logger.warning("Discord DM 送信失敗 lead=%s: %s", lead_id, e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Discord 送信エラー: {e}",
        )

    # sent_by_staff_id 解決
    sent_by_staff_id: Optional[int] = None
    if current_user.email:
        try:
            sr = await db.execute(
                text(f"SELECT id FROM {staff_t} WHERE primary_email = :email "
                     "ORDER BY id ASC LIMIT 1"),
                {"email": current_user.email},
            )
            row = sr.first()
            if row:
                sent_by_staff_id = int(row[0])
        except Exception:
            sent_by_staff_id = None

    # meta_messages に outbound 行 INSERT
    insert_result = await db.execute(
        text(f"""
            INSERT INTO {meta_messages_t}
                (tenant_id, lead_id, platform, sender_id, message_text,
                 direction, message_id, recipient_id,
                 sent_by_staff_id, created_at)
            VALUES
                (:tenant_id, :lead_id, 'discord', :sender_id, :text,
                 'outbound', :message_id, :recipient_id,
                 :sent_by_staff_id, NOW())
            RETURNING id, created_at
        """),
        {
            "tenant_id": tenant_id,
            "lead_id": lead_id,
            "sender_id": f"bot:{tenant_id}",
            "text": text_body,
            "message_id": discord_msg_id,
            "recipient_id": discord_user_id,
            "sent_by_staff_id": sent_by_staff_id,
        },
    )
    new_row = insert_result.first()
    new_id = int(new_row[0]) if new_row else 0
    new_created_at = new_row[1] if new_row else None

    await _record_send_audit_safely(
        db, tenant_id=tenant_id, user_id=current_user.id,
        action="discord_message_sent", record_id=new_id,
        new_data={"lead_id": lead_id, "platform": "discord", "message_id": discord_msg_id},
    )
    await db.commit()

    return {
        "id": new_id,
        "message_id": discord_msg_id,
        "messaging_type": None,
        "message_tag": None,
        "sent_at": _meta_msg_format_dt(new_created_at),
        "lead_id": lead_id,
        "platform": "discord",
    }


# ---------------------------------------------------------------------------
# POST /leads/{lead_id}/messages/image — 画像メッセージ送信
# ---------------------------------------------------------------------------

# 許可する画像 MIME タイプ（Meta Messenger 対応形式）
_ALLOWED_IMAGE_TYPES = frozenset({
    "image/jpeg", "image/png", "image/gif", "image/webp",
})
# ファイルサイズ上限: 8MB（Meta 制限は 25MB だが運用バッファを考慮）
_MAX_IMAGE_BYTES = 8 * 1024 * 1024


@router.post(
    "/leads/{lead_id}/messages/image",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("messaging.send"))],
)
async def send_lead_image_message(
    lead_id: int,
    image: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """指定 lead に Meta 経由で画像メッセージを送信する（Sprint 2）。

    1. バリデーション: MIME タイプ (image/*) + サイズ (≤8MB)
    2. lead 存在確認 + platform 推論（text 送信と同じロジック）
    3. messaging window 判定（Meta のみ）
    4. Meta Attachment Upload API でアップロード → attachment_id 取得
    5. Meta Send API で attachment_id を使って送信
    6. meta_messages に direction='outbound', attachment_type='image' で INSERT

    Discord は画像送信未対応（400）。
    """
    # ----- (1) バリデーション -----
    content_type = image.content_type or ""
    if content_type not in _ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"サポートされていない画像形式です（{content_type}）。JPEG/PNG/GIF/WebP を使用してください",
        )
    file_bytes = await image.read()
    if len(file_bytes) > _MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"ファイルサイズが上限（8MB）を超えています（{len(file_bytes) // 1024 // 1024}MB）",
        )
    if not file_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="空のファイルです")

    # ----- (2) lead 存在 + tenant 確認 -----
    leads_t = tenant_table_ref(db, tenant_id, "leads")
    meta_messages_t = tenant_table_ref(db, tenant_id, "meta_messages")
    tenant_meta_config_t = tenant_table_ref(db, tenant_id, "tenant_meta_config")
    staff_t = tenant_table_ref(db, tenant_id, "staff")

    lead_q = await db.execute(
        text(f"SELECT {_LEAD_COLUMNS} FROM {leads_t} "
             "WHERE id = :id AND tenant_id = :tenant_id"),
        {"id": lead_id, "tenant_id": tenant_id},
    )
    lead_row = lead_q.mappings().first()
    if not lead_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="リードが見つかりません")

    # ----- (3) 直近 inbound 取得 + platform 推論 -----
    inbound_q = await db.execute(
        text(f"""
            SELECT created_at, sender_id, platform
            FROM {meta_messages_t}
            WHERE lead_id = :lead_id AND tenant_id = :tenant_id AND direction = 'inbound'
            ORDER BY created_at DESC, id DESC LIMIT 1
        """),
        {"lead_id": lead_id, "tenant_id": tenant_id},
    )
    inbound_row = inbound_q.first()
    if inbound_row is None:
        last_inbound_at = None
        inbound_sender_id = None
        inbound_platform = None
    else:
        last_inbound_at = _meta_msg_parse_aware(inbound_row[0])
        inbound_sender_id = inbound_row[1]
        inbound_platform = inbound_row[2]

    source_str = lead_row.get("source") if hasattr(lead_row, "get") else lead_row["source"]
    platform = inbound_platform
    if not platform and source_str:
        if isinstance(source_str, str) and ":" in source_str:
            prefix = source_str.split(":", 1)[0]
            if prefix in ("messenger", "instagram", "discord"):
                platform = prefix

    if platform == "discord":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Discord への画像送信はサポートされていません",
        )
    if platform not in ("messenger", "instagram"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="このリードはメッセージング連携されていないため送信できません",
        )

    # ----- (4) messaging window 判定 -----
    state = mw.compute_state(last_inbound_at)
    messaging_type, message_tag = mw.messaging_type_for_state(state)
    if messaging_type is None:
        if state == mw.WindowState.EXPIRED:
            detail = "メッセージウィンドウを超過しています（受信から 7 日以上経過）"
        else:
            detail = "受信履歴がないため送信できません"
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)

    # ----- (5) recipient_id 解決 -----
    recipient_id = _extract_recipient_id(source_str, inbound_sender_id)
    if not recipient_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="送信先 ID が解決できません",
        )

    # ----- (6) Page Access Token 取得 -----
    if platform == "messenger":
        token_q = await db.execute(
            text(f"""
                SELECT id, page_id, page_access_token_encrypted, instagram_business_account_id
                FROM {tenant_meta_config_t}
                WHERE tenant_id = :tenant_id AND is_active = TRUE
                ORDER BY connected_at DESC, id DESC LIMIT 1
            """),
            {"tenant_id": tenant_id},
        )
    else:
        token_q = await db.execute(
            text(f"""
                SELECT id, page_id, page_access_token_encrypted, instagram_business_account_id
                FROM {tenant_meta_config_t}
                WHERE tenant_id = :tenant_id AND is_active = TRUE
                  AND instagram_business_account_id IS NOT NULL
                ORDER BY connected_at DESC, id DESC LIMIT 1
            """),
            {"tenant_id": tenant_id},
        )
    config_row = token_q.first()
    if config_row is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="送信に使う Meta 接続が見つかりません（Channels 設定で接続してください）",
        )
    config_id, page_id_for_send, encrypted_token_blob, ig_business_id = (
        int(config_row[0]),
        config_row[1],
        config_row[2],
        config_row[3],
    )
    try:
        page_access_token = encryption.decrypt(_decode_token_blob(encrypted_token_blob))
    except encryption.EncryptionError as e:
        logger.error("Page Access Token 復号失敗: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="保存トークンの復号に失敗しました",
        )

    # ----- (7) Attachment Upload → attachment_id -----
    pid_str = str(page_id_for_send) if page_id_for_send else "me"
    filename = image.filename or f"image.{content_type.split('/')[-1]}"
    try:
        attachment_id = await meta_graph.upload_attachment(
            page_id=pid_str,
            page_access_token=page_access_token,
            file_bytes=file_bytes,
            content_type=content_type,
            filename=filename,
        )
    except MetaGraphAPIError as e:
        logger.warning("Attachment Upload API error for lead %s: %s", lead_id, e.error_type)
        await _record_send_audit_safely(
            db, tenant_id=tenant_id, user_id=current_user.id,
            action="meta_image_upload_failed", record_id=config_id,
            new_data={"lead_id": lead_id, "meta_error": e.to_audit_dict()},
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"detail": "画像アップロードに失敗しました", "error_code": e.error_code},
        )
    except MetaGraphTimeoutError:
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="画像アップロードがタイムアウトしました")
    except MetaGraphTransportError as e:
        logger.warning("Attachment Upload transport error for lead %s: %s", lead_id, e)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="画像アップロードへの接続に失敗しました")

    # ----- (8) Meta Send API で attachment_id 送信 -----
    try:
        if platform == "messenger":
            send_result = await meta_graph.send_messenger_attachment(
                page_access_token=page_access_token,
                recipient_id=recipient_id,
                attachment_id=attachment_id,
                messaging_type=messaging_type,
                tag=message_tag,
                page_id=pid_str,
            )
        else:  # instagram
            if not ig_business_id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Instagram Business Account が紐づいていません",
                )
            send_result = await meta_graph.send_instagram_attachment(
                page_access_token=page_access_token,
                page_id=pid_str,
                recipient_id=recipient_id,
                attachment_id=attachment_id,
                messaging_type=messaging_type,
                tag=message_tag,
            )
    except MetaGraphRateLimitError:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                            detail={"message": "Meta APIのレート制限に達しました"})
    except MetaGraphTimeoutError:
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="Meta Send API がタイムアウトしました")
    except MetaGraphAPIError as e:
        logger.warning("Meta Send API error (image) for lead %s: %s", lead_id, e.error_type)
        await _record_send_audit_safely(
            db, tenant_id=tenant_id, user_id=current_user.id,
            action="meta_image_send_failed", record_id=config_id,
            new_data={"lead_id": lead_id, "meta_error": e.to_audit_dict()},
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"detail": "Meta Send API がエラーを返しました", "error_code": e.error_code},
        )
    except MetaGraphError as e:
        logger.warning("Meta Send transport error (image) for lead %s: %s", lead_id, e)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Meta Send API への接続に失敗しました")

    # ----- (9) sent_by_staff_id 解決 -----
    sent_by_staff_id: Optional[int] = None
    if current_user.email:
        try:
            sr = await db.execute(
                text(f"SELECT id FROM {staff_t} WHERE primary_email = :email ORDER BY id ASC LIMIT 1"),
                {"email": current_user.email},
            )
            row = sr.first()
            if row:
                sent_by_staff_id = int(row[0])
        except Exception:
            sent_by_staff_id = None

    # ----- (10) meta_messages に outbound 行 INSERT -----
    sender_id = page_id_for_send if platform == "messenger" else (ig_business_id or page_id_for_send)
    page_id_for_message = page_id_for_send if platform == "messenger" else None
    insert_params = {
        "tenant_id": tenant_id,
        "lead_id": lead_id,
        "platform": platform,
        "sender_id": str(sender_id) if sender_id is not None else None,
        "message_id": send_result.get("message_id"),
        "recipient_id": recipient_id,
        "messaging_type": messaging_type,
        "message_tag": message_tag,
        "sent_by_staff_id": sent_by_staff_id,
        "page_id": page_id_for_message,
        "attachment_type": "image",
    }
    insert_result = await db.execute(
        text(f"""
            INSERT INTO {meta_messages_t} (
                tenant_id, lead_id, platform, sender_id, message_text,
                direction, message_id, recipient_id,
                messaging_type, message_tag, sent_by_staff_id, page_id,
                attachment_type, created_at
            )
            VALUES (
                :tenant_id, :lead_id, :platform, :sender_id, '',
                'outbound', :message_id, :recipient_id,
                :messaging_type, :message_tag, :sent_by_staff_id, :page_id,
                :attachment_type, NOW()
            )
            RETURNING id, created_at
        """),
        insert_params,
    )
    new_row = insert_result.first()
    if new_row is None:
        await db.execute(
            text(f"""
                INSERT INTO {meta_messages_t} (
                    tenant_id, lead_id, platform, sender_id, message_text,
                    direction, message_id, recipient_id,
                    messaging_type, message_tag, sent_by_staff_id, page_id,
                    attachment_type, created_at
                )
                VALUES (
                    :tenant_id, :lead_id, :platform, :sender_id, '',
                    'outbound', :message_id, :recipient_id,
                    :messaging_type, :message_tag, :sent_by_staff_id, :page_id,
                    :attachment_type, NOW()
                )
            """),
            insert_params,
        )
        last_id_row = await db.execute(text("SELECT last_insert_rowid(), CURRENT_TIMESTAMP"))
        new_id_row = last_id_row.first()
        new_id = int(new_id_row[0]) if new_id_row else 0
        new_created_at = new_id_row[1] if new_id_row else None
    else:
        new_id = int(new_row[0])
        new_created_at = new_row[1]

    await _record_send_audit_safely(
        db, tenant_id=tenant_id, user_id=current_user.id,
        action="meta_image_sent", record_id=new_id,
        new_data={
            "lead_id": lead_id,
            "platform": platform,
            "messaging_type": messaging_type,
            "message_tag": message_tag,
            "message_id": send_result.get("message_id"),
            "attachment_type": "image",
        },
    )
    await db.commit()

    return {
        "id": new_id,
        "message_id": send_result.get("message_id"),
        "messaging_type": messaging_type,
        "message_tag": message_tag,
        "sent_at": _meta_msg_format_dt(new_created_at),
        "lead_id": lead_id,
        "platform": platform,
        "attachment_type": "image",
    }


# ---------------------------------------------------------------------------
# GET /leads/stream — SSE リアルタイム通知（Phase 3）
# ---------------------------------------------------------------------------
from starlette.requests import Request
from starlette.responses import StreamingResponse

_SSE_HEARTBEAT_SEC = 30


@router.get(
    "/leads/stream",
    dependencies=[Depends(require_permission("leads.view"))],
)
async def stream_leads_updates(
    request: Request,
    tenant_id: int = Depends(get_current_tenant),
) -> StreamingResponse:
    """
    SSE でリード一覧の更新を通知する。
    リード作成・更新・削除時に "event: update" を送信。
    30 秒ごとにハートビート ping。
    """
    from app.services.sse_pubsub import (
        decrement_connection,
        increment_connection,
        subscribe_leads,
    )

    if not await increment_connection("leads", tenant_id):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SSE接続数が上限に達しています",
        )

    async def event_generator():
        gen = subscribe_leads(tenant_id)
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    await asyncio.wait_for(gen.__anext__(), timeout=_SSE_HEARTBEAT_SEC)
                    yield "event: update\ndata: {}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                except StopAsyncIteration:
                    break
                except Exception:
                    logger.warning(
                        "SSE leads generator 予期しないエラー: tenant_id=%s", tenant_id, exc_info=True
                    )
                    break
        finally:
            await gen.aclose()
            await decrement_connection("leads", tenant_id)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
