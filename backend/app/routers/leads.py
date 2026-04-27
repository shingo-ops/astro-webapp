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

from decimal import Decimal

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
