from __future__ import annotations

"""
会社管理API（CRUD）。Phase 1-B-2 Step 5b-1 で新設。

テナントスキーマの companies 本体 + 2副テーブル（company_addresses /
company_sales_channels）を一括で扱う。担当者は routers/contacts.py で別管理。

search_path は get_current_tenant dependency で自動切り替え済み。
permission は 'customers.*' をそのまま流用（companies = 会社 = 顧客の新表現）。
Step 5d で独立の companies.* 権限を導入する方針は残す。
"""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, get_current_tenant, require_permission
from app.cache import invalidate_dashboard_cache
from app.database import get_db
from app.models import User
from app.schemas.company import (
    CompanyAddressInput,
    CompanyAddressResponse,
    CompanyCreate,
    CompanyResponse,
    CompanyUpdate,
)
from app.services.audit import record_audit_log

logger = logging.getLogger(__name__)
router = APIRouter()

_COMPANY_COLUMNS = """
    id, tenant_id, company_code, lead_id, sales_rep_id,
    name, name_en, normalized_name,
    industry, website,
    trust_level, priority_focus,
    per_order_amount, monthly_frequency,
    monthly_forecast, monthly_forecast_source, monthly_forecast_updated_at,
    billing_display_name, payment_recipient_name,
    fedex_account, shipping_note,
    status, notes,
    created_at, updated_at
"""

_UPDATABLE_COLUMNS = {
    "lead_id", "sales_rep_id", "name", "name_en", "normalized_name",
    "industry", "website",
    "trust_level", "priority_focus",
    "per_order_amount", "monthly_frequency",
    "monthly_forecast", "monthly_forecast_source",
    "billing_display_name", "payment_recipient_name",
    "fedex_account", "shipping_note", "status", "notes",
}


async def _fetch_addresses(db: AsyncSession, company_id: int) -> list[CompanyAddressResponse]:
    res = await db.execute(
        text("""
            SELECT id, address_type, branch_name, name, email, telephone, tax_id,
                   address_line_1, address_line_2, address_line_3,
                   city, state, zip, country_code, is_default
            FROM company_addresses WHERE company_id = :cid
            ORDER BY
                CASE address_type WHEN 'billing' THEN 0 WHEN 'delivery' THEN 1 ELSE 2 END,
                is_default DESC, id
        """),
        {"cid": company_id},
    )
    return [CompanyAddressResponse(**row) for row in res.mappings().all()]


async def _fetch_sales_channels(db: AsyncSession, company_id: int) -> list[str]:
    res = await db.execute(
        text("SELECT channel FROM company_sales_channels WHERE company_id = :cid ORDER BY channel"),
        {"cid": company_id},
    )
    return [row.channel for row in res.fetchall()]


async def _compose_response(db: AsyncSession, main_row: dict) -> CompanyResponse:
    cid = main_row["id"]
    return CompanyResponse(
        **main_row,
        addresses=await _fetch_addresses(db, cid),
        sales_channels=await _fetch_sales_channels(db, cid),
    )


async def _replace_addresses(
    db: AsyncSession, company_id: int, addresses: list[CompanyAddressInput]
) -> None:
    """DELETE + 全件 INSERT で冪等置換。address_type ごとに is_default=TRUE は最大1つ
    （DB の部分UNIQUE INDEX で保証されるが、Python 側でも先着優先で1つに絞る）"""
    await db.execute(
        text("DELETE FROM company_addresses WHERE company_id = :cid"),
        {"cid": company_id},
    )
    seen_default: dict[str, bool] = {"billing": False, "delivery": False}
    for addr in addresses:
        atype = addr.address_type.value
        effective_is_default = addr.is_default and not seen_default.get(atype, False)
        if effective_is_default:
            seen_default[atype] = True
        await db.execute(
            text("""
                INSERT INTO company_addresses (
                    company_id, address_type, branch_name,
                    name, email, telephone, tax_id,
                    address_line_1, address_line_2, address_line_3,
                    city, state, zip, country_code, is_default
                ) VALUES (
                    :cid, :atype, :branch,
                    :name, :email, :telephone, :tax_id,
                    :l1, :l2, :l3, :city, :state, :zip, :country, :is_default
                )
            """),
            {
                "cid": company_id,
                "atype": atype,
                "branch": addr.branch_name,
                "name": addr.name,
                "email": addr.email,
                "telephone": addr.telephone,
                "tax_id": addr.tax_id,
                "l1": addr.address_line_1,
                "l2": addr.address_line_2,
                "l3": addr.address_line_3,
                "city": addr.city,
                "state": addr.state,
                "zip": addr.zip,
                "country": addr.country_code,
                "is_default": effective_is_default,
            },
        )


async def _replace_sales_channels(db: AsyncSession, company_id: int, channels: list[str]) -> None:
    await db.execute(
        text("DELETE FROM company_sales_channels WHERE company_id = :cid"),
        {"cid": company_id},
    )
    for ch in channels:
        if not ch or not ch.strip():
            continue
        await db.execute(
            text("""
                INSERT INTO company_sales_channels (company_id, channel)
                VALUES (:cid, :ch)
                ON CONFLICT (company_id, channel) DO NOTHING
            """),
            {"cid": company_id, "ch": ch.strip()},
        )


# ========== Endpoints ==========


@router.get(
    "/companies",
    response_model=list[CompanyResponse],
    dependencies=[Depends(require_permission("customers.view"))],
)
async def list_companies(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None, max_length=255),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """会社一覧を取得。検索対象は company_code / name / normalized_name / billing_display_name。"""
    offset = (page - 1) * per_page

    if search:
        result = await db.execute(
            text(f"""
                SELECT {_COMPANY_COLUMNS}
                FROM companies
                WHERE company_code ILIKE :search
                   OR name ILIKE :search
                   OR normalized_name ILIKE :search
                   OR billing_display_name ILIKE :search
                ORDER BY updated_at DESC
                LIMIT :limit OFFSET :offset
            """),
            {"search": f"%{search}%", "limit": per_page, "offset": offset},
        )
    else:
        result = await db.execute(
            text(f"""
                SELECT {_COMPANY_COLUMNS}
                FROM companies
                ORDER BY updated_at DESC
                LIMIT :limit OFFSET :offset
            """),
            {"limit": per_page, "offset": offset},
        )

    rows = result.mappings().all()
    return [await _compose_response(db, dict(row)) for row in rows]


@router.get(
    "/companies/{company_id}",
    response_model=CompanyResponse,
    dependencies=[Depends(require_permission("customers.view"))],
)
async def get_company(
    company_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        text(f"SELECT {_COMPANY_COLUMNS} FROM companies WHERE id = :id"),
        {"id": company_id},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会社が見つかりません")
    return await _compose_response(db, dict(row))


@router.post(
    "/companies",
    response_model=CompanyResponse,
    status_code=201,
    dependencies=[Depends(require_permission("customers.create"))],
)
async def create_company(
    data: CompanyCreate,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """会社を登録する（本体 + 副テーブル）。company_code 未指定なら CO-{id:05d}。"""
    try:
        explicit_code = data.company_code and data.company_code.strip()
        # CO-PEND-<8hex> = 最大 16 文字 (VARCHAR(20) に収まる)。
        # 元は hex 32 文字で VARCHAR(20) 超過の StringDataRightTruncationError 500 が出ていた（Step 5c-1 検証で発覚）。
        company_code = explicit_code if explicit_code else f"CO-PEND-{uuid.uuid4().hex[:8]}"

        forecast_source_value = (
            data.monthly_forecast_source.value if data.monthly_forecast_source else "manual"
        ) if data.monthly_forecast is not None else None

        result = await db.execute(
            text("""
                INSERT INTO companies (
                    tenant_id, company_code, lead_id, sales_rep_id,
                    name, name_en, normalized_name, industry, website,
                    trust_level, priority_focus,
                    per_order_amount, monthly_frequency,
                    monthly_forecast, monthly_forecast_source, monthly_forecast_updated_at,
                    billing_display_name, payment_recipient_name,
                    fedex_account, shipping_note,
                    status, notes
                ) VALUES (
                    :tenant_id, :company_code, :lead_id, :sales_rep_id,
                    :name, :name_en, :normalized_name, :industry, :website,
                    :trust_level, :priority_focus,
                    :per_order_amount, :monthly_frequency,
                    :monthly_forecast, :monthly_forecast_source, NULL,
                    :billing_display_name, :payment_recipient_name,
                    :fedex_account, :shipping_note,
                    :status, :notes
                )
                RETURNING id
            """),
            {
                "tenant_id": tenant_id,
                "company_code": company_code,
                "lead_id": data.lead_id,
                "sales_rep_id": data.sales_rep_id,
                "name": data.name,
                "name_en": data.name_en,
                "normalized_name": data.normalized_name,
                "industry": data.industry,
                "website": data.website,
                "trust_level": data.trust_level,
                "priority_focus": data.priority_focus,
                "per_order_amount": data.per_order_amount,
                "monthly_frequency": data.monthly_frequency,
                "monthly_forecast": data.monthly_forecast,
                "monthly_forecast_source": forecast_source_value,
                "billing_display_name": data.billing_display_name,
                "payment_recipient_name": data.payment_recipient_name,
                "fedex_account": data.fedex_account,
                "shipping_note": data.shipping_note,
                "status": data.status.value,
                "notes": data.notes,
            },
        )
        new_id = result.scalar_one()

        if not explicit_code:
            await db.execute(
                text("UPDATE companies SET company_code = :code WHERE id = :id"),
                {"code": f"CO-{new_id:05d}", "id": new_id},
            )
        if data.monthly_forecast is not None:
            await db.execute(
                text("UPDATE companies SET monthly_forecast_updated_at = NOW() WHERE id = :id"),
                {"id": new_id},
            )

        # DEBUG: Step 5c-1 検証で DELETE FROM company_addresses が
        # "relation does not exist" で落ちる原因調査
        try:
            sp = await db.execute(text("SELECT current_schemas(true)"))
            logger.warning("create_company: search_path=%s tenant_id=%s new_id=%s", sp.scalar(), tenant_id, new_id)
        except Exception as e:
            logger.warning("create_company: search_path probe failed: %s", e)
        await _replace_addresses(db, new_id, data.addresses)
        await _replace_sales_channels(db, new_id, data.sales_channels)

        fetched = await db.execute(
            text(f"SELECT {_COMPANY_COLUMNS} FROM companies WHERE id = :id"),
            {"id": new_id},
        )
        row = fetched.mappings().first()

        await record_audit_log(
            db=db, tenant_id=tenant_id, user_id=current_user.id,
            action="create", table_name="companies", record_id=new_id,
            new_data=data.model_dump(exclude_none=True, mode="json"),
        )
        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        logger.warning("create_company IntegrityError: tenant=%d, err=%s", tenant_id, e.orig)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="会社の登録に失敗しました（company_code 重複または制約違反の可能性）",
        )
    await invalidate_dashboard_cache(tenant_id)
    return await _compose_response(db, dict(row))


@router.patch(
    "/companies/{company_id}",
    response_model=CompanyResponse,
    dependencies=[Depends(require_permission("customers.update"))],
)
async def update_company(
    company_id: int,
    data: CompanyUpdate,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    old_result = await db.execute(
        text(f"SELECT {_COMPANY_COLUMNS} FROM companies WHERE id = :id"),
        {"id": company_id},
    )
    old_row = old_result.mappings().first()
    if not old_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会社が見つかりません")

    update_data = data.model_dump(exclude_unset=True, mode="python")
    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="更新するフィールドを少なくとも1つ指定してください",
        )

    addresses = update_data.pop("addresses", None)
    sales_channels = update_data.pop("sales_channels", None)

    update_data = {k: v for k, v in update_data.items() if k in _UPDATABLE_COLUMNS}
    for k, v in list(update_data.items()):
        if hasattr(v, "value"):
            update_data[k] = v.value

    touch_forecast_updated_at = False
    if "monthly_forecast" in update_data:
        if update_data["monthly_forecast"] is None:
            update_data["monthly_forecast_source"] = None
            update_data["monthly_forecast_updated_at"] = None
        else:
            if not update_data.get("monthly_forecast_source"):
                update_data["monthly_forecast_source"] = "manual"
            touch_forecast_updated_at = True
            update_data.pop("monthly_forecast_updated_at", None)

    if update_data:
        set_sql = ", ".join(f"{k} = :{k}" for k in update_data)
        params = {**update_data, "id": company_id}
        await db.execute(
            text(f"UPDATE companies SET {set_sql}, updated_at = NOW() WHERE id = :id"),
            params,
        )

    if touch_forecast_updated_at:
        await db.execute(
            text("UPDATE companies SET monthly_forecast_updated_at = NOW() WHERE id = :id"),
            {"id": company_id},
        )

    if addresses is not None:
        addr_models = [CompanyAddressInput(**a) for a in addresses]
        await _replace_addresses(db, company_id, addr_models)
    if sales_channels is not None:
        await _replace_sales_channels(db, company_id, sales_channels)

    await record_audit_log(
        db=db, tenant_id=tenant_id, user_id=current_user.id,
        action="update", table_name="companies", record_id=company_id,
        old_data=dict(old_row), new_data=data.model_dump(exclude_unset=True, mode="json"),
    )
    await db.commit()
    await invalidate_dashboard_cache(tenant_id)

    fetched = await db.execute(
        text(f"SELECT {_COMPANY_COLUMNS} FROM companies WHERE id = :id"),
        {"id": company_id},
    )
    row = fetched.mappings().first()
    return await _compose_response(db, dict(row))


@router.delete(
    "/companies/{company_id}",
    status_code=204,
    dependencies=[Depends(require_permission("customers.delete"))],
)
async def delete_company(
    company_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """会社を削除する。contacts (ON DELETE CASCADE) + 副テーブル (CASCADE) も連動削除。
    ただし deals/quotes/invoices/orders が company_id 参照で残っている場合は
    FK 制約で 409 Conflict になる。また _customer_migration_map が参照している場合も同様。
    """
    old_result = await db.execute(
        text(f"SELECT {_COMPANY_COLUMNS} FROM companies WHERE id = :id"),
        {"id": company_id},
    )
    old_row = old_result.mappings().first()
    if not old_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会社が見つかりません")

    try:
        await db.execute(text("DELETE FROM companies WHERE id = :id"), {"id": company_id})
        await record_audit_log(
            db=db, tenant_id=tenant_id, user_id=current_user.id,
            action="delete", table_name="companies", record_id=company_id,
            old_data=dict(old_row),
        )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="この会社には関連する商談・注文・見積・請求書・担当者があるため削除できません。先に関連データを削除してください。",
        )
    await invalidate_dashboard_cache(tenant_id)
