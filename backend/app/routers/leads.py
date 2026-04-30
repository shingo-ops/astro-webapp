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

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, get_current_tenant, require_permission
from app.cache import invalidate_dashboard_cache
from app.database import get_db
from app.models import User
from app.schemas.lead import LeadConvertRequest, LeadCreate, LeadResponse, LeadUpdate
from app.services.audit import record_audit_log

router = APIRouter()

_LEAD_COLUMNS = """
    id, lead_code, customer_name, company_name, email, phone,
    source, type, status, temperature, estimated_scale, customer_type,
    response_speed, monthly_forecast, prospect_rank, assigned_to,
    converted_deal_id, notes, created_at, updated_at
"""

_UPDATABLE_COLUMNS = {
    "customer_name", "company_name", "email", "phone",
    "source", "type", "status", "temperature", "estimated_scale",
    "customer_type", "response_speed", "monthly_forecast",
    "prospect_rank", "assigned_to", "notes",
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

    result = await db.execute(
        text(f"""
            SELECT {_LEAD_COLUMNS}
            FROM leads
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
    result = await db.execute(
        text(f"SELECT {_LEAD_COLUMNS} FROM leads WHERE id = :id"),
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

    result = await db.execute(
        text("""
            INSERT INTO leads (
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
        text("UPDATE leads SET lead_code = :code WHERE id = :id"),
        {"code": f"LD-{new_id:05d}", "id": new_id},
    )

    fetched = await db.execute(
        text(f"SELECT {_LEAD_COLUMNS} FROM leads WHERE id = :id"),
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
    old_result = await db.execute(
        text(f"SELECT {_LEAD_COLUMNS} FROM leads WHERE id = :id"),
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
            UPDATE leads SET {set_clauses}, updated_at = NOW()
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
    old_result = await db.execute(
        text(f"SELECT {_LEAD_COLUMNS} FROM leads WHERE id = :id"),
        {"id": lead_id},
    )
    old_row = old_result.mappings().first()
    if not old_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="リードが見つかりません")

    await db.execute(text("DELETE FROM leads WHERE id = :id"), {"id": lead_id})
    await record_audit_log(
        db=db, tenant_id=tenant_id, user_id=current_user.id,
        action="delete", table_name="leads", record_id=lead_id,
        old_data=dict(old_row),
    )
    await db.commit()
    await invalidate_dashboard_cache(tenant_id)


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
    リードを案件化する。新しいdealを作成し、leadを'案件化'ステータスに更新＋リンクする。

    同時実行対策:
      - deal作成後、`UPDATE leads ... WHERE converted_deal_id IS NULL` で
        アトミックにクレーム。並行変換でクレームに失敗した場合は
        作成済みdealと共にrollbackして409を返す。
    """
    lead_result = await db.execute(
        text(f"SELECT {_LEAD_COLUMNS} FROM leads WHERE id = :id"),
        {"id": lead_id},
    )
    lead_row = lead_result.mappings().first()
    if not lead_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="リードが見つかりません")
    if lead_row["converted_deal_id"] is not None:
        # 早期409（UXのため）。完全な保証は下のUPDATEで行う。
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="このリードは既に案件化されています")

    # Step 5d: contact / company の存在 + 所属一致確認のみ
    contact_check = await db.execute(
        text("SELECT company_id FROM contacts WHERE id = :id"),
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
        text("""
            INSERT INTO deals (
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
        text("UPDATE deals SET deal_code = :code WHERE id = :id"),
        {"code": f"DL-{new_deal_id:05d}", "id": new_deal_id},
    )

    # アトミッククレーム: converted_deal_id IS NULL の場合のみ更新する
    # 並行リクエストで既に案件化されていた場合は0行返却 → 例外で全ロールバック
    updated = await db.execute(
        text(f"""
            UPDATE leads
            SET status = '案件化', converted_deal_id = :deal_id, updated_at = NOW()
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
            detail="このリードは既に案件化されています（並行リクエスト）",
        )

    await record_audit_log(
        db=db, tenant_id=tenant_id, user_id=current_user.id,
        action="convert", table_name="leads", record_id=lead_id,
        old_data=dict(lead_row),
        new_data={"converted_deal_id": new_deal_id, "status": "案件化"},
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
_MESSAGING_WINDOW_RESPONSE_HOURS = 24
_MESSAGING_WINDOW_HUMAN_AGENT_DAYS = 7


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

    返却 keys: last_inbound_at, expires_at, can_send_response,
              requires_human_agent_tag, can_send_at_all
    """
    if last_inbound_at is None:
        # inbound 履歴なし → 24h ルール上は送信不可（Meta 仕様）
        return {
            "last_inbound_at": None,
            "expires_at": None,
            "can_send_response": False,
            "requires_human_agent_tag": False,
            "can_send_at_all": False,
        }
    now = datetime.now(timezone.utc)
    elapsed = now - last_inbound_at
    expires_at = last_inbound_at + timedelta(hours=_MESSAGING_WINDOW_RESPONSE_HOURS)
    can_send_response = elapsed <= timedelta(hours=_MESSAGING_WINDOW_RESPONSE_HOURS)
    requires_human_agent = (
        elapsed > timedelta(hours=_MESSAGING_WINDOW_RESPONSE_HOURS)
        and elapsed <= timedelta(days=_MESSAGING_WINDOW_HUMAN_AGENT_DAYS)
    )
    can_send_at_all = elapsed <= timedelta(days=_MESSAGING_WINDOW_HUMAN_AGENT_DAYS)
    return {
        "last_inbound_at": last_inbound_at.isoformat(),
        "expires_at": expires_at.isoformat(),
        "can_send_response": bool(can_send_response),
        "requires_human_agent_tag": bool(requires_human_agent),
        "can_send_at_all": bool(can_send_at_all),
    }


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
    lead_result = await db.execute(
        text(f"SELECT {_LEAD_COLUMNS} FROM leads WHERE id = :id AND tenant_id = :tenant_id"),
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

    msg_result = await db.execute(
        text(f"""
            SELECT
                id, platform, sender_id, sender_name, message_text, direction,
                message_id, recipient_id, messaging_type, message_tag,
                sent_by_staff_id, error_code, error_message,
                seen_at, seen_by_staff_id,
                created_at
            FROM meta_messages
            WHERE {where_sql}
            ORDER BY created_at ASC, id ASC
            LIMIT :limit
        """),
        params,
    )
    msg_rows = msg_result.mappings().all()

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
                "SELECT platform FROM meta_messages "
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
            "SELECT MAX(created_at) FROM meta_messages "
            "WHERE lead_id = :lead_id AND tenant_id = :tenant_id "
            "AND direction = 'inbound'"
        ),
        {"lead_id": lead_id, "tenant_id": tenant_id},
    )
    last_inbound_raw = inbound_q.scalar()
    last_inbound_at = _meta_msg_parse_aware(last_inbound_raw)

    return {
        "messages": messages,
        "lead": {
            "id": lead_row["id"],
            "lead_code": lead_row["lead_code"],
            "customer_name": lead_row["customer_name"],
            "platform": latest_platform,
            "source": lead_row["source"],
        },
        "messaging_window": _compute_messaging_window(last_inbound_at),
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
    lead_q = await db.execute(
        text("SELECT id FROM leads WHERE id = :id AND tenant_id = :tenant_id"),
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
                text("SELECT id FROM staff WHERE primary_email = :email "
                     "ORDER BY id ASC LIMIT 1"),
                {"email": current_user.email},
            )
            row = sr.first()
            if row:
                staff_id = int(row[0])
        except Exception:
            staff_id = None

    upd = await db.execute(
        text("""
            UPDATE meta_messages
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

    await db.commit()

    return {"marked_count": marked}
