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

from app.auth.dependencies import (
    get_current_tenant,
    get_current_user,
    require_permission,
    reset_tenant_context,
)
from app.cache import invalidate_dashboard_cache
from app.database import get_db
from app.models import User
from app.schemas.company import (
    CompanyAddressInput,
    CompanyAddressResponse,
    CompanyCreate,
    CompanyMergeRequest,
    CompanyResponse,
    CompanyUpdate,
)
from app.services.audit import (
    build_subtable_diff,
    record_audit_log,
    snapshot_subtable_rows,
    snapshot_subtable_scalars,
)

# 副テーブル diff のスナップショット対象列。id / *_at は audit.diff_rows 内で除外される
# が、明示的に欲しい列だけ取得することでログサイズを抑制し、新列追加時の意図しない
# diff ノイズも防ぐ。
_AUDIT_ADDRESS_COLUMNS = [
    "address_type", "branch_name", "name", "email", "telephone", "tax_id",
    "address_line_1", "address_line_2", "address_line_3",
    "city", "state", "zip", "country_code", "is_default",
]


async def _snapshot_company_subtables(db: AsyncSession, company_id: int) -> dict[str, object]:
    """audit_log 用に company の副テーブルをスナップショットする。

    PR #145 F9: companies/contacts の副テーブル変更が audit_logs に記録されない問題の対応。
    update / delete 時の old / new 比較に使う。
    """
    return {
        "company_addresses": await snapshot_subtable_rows(
            db, "company_addresses", "company_id", company_id, _AUDIT_ADDRESS_COLUMNS,
        ),
        "company_sales_channels": await snapshot_subtable_scalars(
            db, "company_sales_channels", "company_id", company_id, "channel",
        ),
    }

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
                is_default DESC,
                -- branch_name でアルファベット順、PATCH 全置換で id が滑っても並びが安定する
                branch_name ASC NULLS LAST,
                id
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

        await _replace_addresses(db, new_id, data.addresses)
        await _replace_sales_channels(db, new_id, data.sales_channels)

        fetched = await db.execute(
            text(f"SELECT {_COMPANY_COLUMNS} FROM companies WHERE id = :id"),
            {"id": new_id},
        )
        row = fetched.mappings().first()

        # PR #145 F9: 副テーブルの初期状態を _subtables.* にスナップショット
        new_subs_snapshot = await _snapshot_company_subtables(db, new_id)
        new_data_payload: dict = data.model_dump(exclude_none=True, mode="json")
        # create 時は added のみで表現（removed は常に空のため省略）
        sub_diff = build_subtable_diff(
            {"company_addresses": [], "company_sales_channels": []},
            new_subs_snapshot,
        )
        if sub_diff:
            new_data_payload["_subtables"] = sub_diff

        await record_audit_log(
            db=db, tenant_id=tenant_id, user_id=current_user.id,
            action="create", table_name="companies", record_id=new_id,
            new_data=new_data_payload,
        )
        await db.commit()
        await reset_tenant_context(db, tenant_id)  # ADR-072 Phase 2.5
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

    # PR #145 F9: 副テーブルの old スナップショットを _replace_* 前に取得
    old_subs_snapshot = await _snapshot_company_subtables(db, company_id)

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

    # PR #145 F9: 副テーブル変更後の new スナップショットを取得して diff を組み立てる。
    # _replace_* が呼ばれていない副テーブルでも old/new 同一なら diff_rows/diff_scalars が None
    # を返すので _subtables には含まれない（無駄なノイズなし）。
    new_subs_snapshot = await _snapshot_company_subtables(db, company_id)
    sub_diff = build_subtable_diff(old_subs_snapshot, new_subs_snapshot)

    new_data_payload: dict = data.model_dump(exclude_unset=True, mode="json")
    if sub_diff:
        new_data_payload["_subtables"] = sub_diff

    await record_audit_log(
        db=db, tenant_id=tenant_id, user_id=current_user.id,
        action="update", table_name="companies", record_id=company_id,
        old_data=dict(old_row), new_data=new_data_payload,
    )
    await db.commit()
    await reset_tenant_context(db, tenant_id)  # ADR-072 Phase 2.5
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

    # PR #145 F9: 副テーブルも CASCADE で消える前にスナップショットを取って old_data に含める
    old_subs_snapshot = await _snapshot_company_subtables(db, company_id)
    sub_diff = build_subtable_diff(
        old_subs_snapshot,
        {"company_addresses": [], "company_sales_channels": []},
    )
    old_data_payload: dict = dict(old_row)
    if sub_diff:
        old_data_payload["_subtables"] = sub_diff

    try:
        await db.execute(text("DELETE FROM companies WHERE id = :id"), {"id": company_id})
        await record_audit_log(
            db=db, tenant_id=tenant_id, user_id=current_user.id,
            action="delete", table_name="companies", record_id=company_id,
            old_data=old_data_payload,
        )
        await db.commit()
        await reset_tenant_context(db, tenant_id)  # ADR-072 Phase 2.5
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="この会社には関連する商談・注文・見積・請求書・担当者があるため削除できません。先に関連データを削除してください。",
        )
    await invalidate_dashboard_cache(tenant_id)


# ========== 重複マージ（A-4: PR #145 + #152 follow-up） ==========
#
# 設計メモ:
#   旧 routers/duplicates.py の merge_customers は customers.id 空間の値を
#   companies.id 空間に流し込むデータ破壊バグ（PR #152 round 1 Major 1）を抱えていた。
#   companies (Phase 1-B-2 移行で独立採番) ベースで再実装し、副テーブル付け替えと
#   merge 元 company の DELETE を 1 トランザクションで完結させる。
#
# トランザクション境界:
#   - get_db() の AsyncSession は 1 リクエスト 1 セッション（commit はエンドポイント末尾）。
#   - 途中で例外を投げた場合は database.py の get_db で rollback されるため、
#     部分的な付け替えが残ることはない。
#
# 監査ログ:
#   - master 側: action=update, _subtables に「全副テーブル added」+ _merge に
#     {merge_id, merge_company_code, reason, reassigned_*} を記録（差分の意味付け）。
#   - merge 元: action=delete, old_data に最終状態（副テーブル含む）を記録。
#
# 制約:
#   - master_id == merge_id → 400
#   - 片方でも存在しない（同テナント外含む） → 404 （search_path で隔離されるため
#     クロステナント参照は SQL レベルで NULL row になる）
#   - master が status='archived' → 409（混乱回避。archived はゴミ箱扱い）
#   - merge 元 company の status は問わない（archived でも吸収できる方が運用上ラク）


@router.post(
    "/companies/{master_id}/merge",
    response_model=CompanyResponse,
    dependencies=[Depends(require_permission("customers.delete"))],
)
async def merge_companies(
    master_id: int,
    merge_id: int = Query(..., description="マージ元の会社 id（吸収されて削除される側）"),
    data: CompanyMergeRequest | None = None,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """会社の重複マージ（merge 元 → master へ全副テーブルを付け替え、merge 元を削除）。

    認可:
        `customers.delete` 権限が必要（merge は実質 merge 元の DELETE を含むため）。

    パラメータ:
        master_id: 残す側（master）の会社 id。
        merge_id: 吸収されて削除される側の会社 id。query parameter。
        data: 任意 body。`reason` を渡すと audit_logs に判断根拠を残せる。

    戻り値:
        master 会社の最新状態（CompanyResponse）。

    エラー:
        - 400: master_id == merge_id（自己マージ）
        - 404: master / merge のいずれかがテナント内に存在しない
        - 409: master が archived（混乱回避）
    """
    if master_id == merge_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="master_id と merge_id が同じです。同一会社をマージすることはできません。",
        )

    # 1) master / merge 両方の存在確認（search_path により同テナント内でのみヒット）。
    #    PR #164 round1 Minor 1: 並行マージのデッドロック回避のため、2行を canonical な
    #    昇順 (id) で同一クエリ内にロックする。User A: master=10/merge=20、User B:
    #    master=20/merge=10 を同時に投げても、両セッションとも 10→20 の順でロックを
    #    取りに行くため、PostgreSQL の deadlock detector に頼らずデッドロックが起きない。
    locked_res = await db.execute(
        text(
            f"SELECT {_COMPANY_COLUMNS} FROM companies "
            "WHERE id IN (:m1, :m2) "
            "ORDER BY id "
            "FOR UPDATE"
        ),
        {"m1": master_id, "m2": merge_id},
    )
    locked_rows = locked_res.mappings().all()
    rows_by_id = {r["id"]: r for r in locked_rows}
    master_row = rows_by_id.get(master_id)
    merge_row = rows_by_id.get(merge_id)
    if not master_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"master 会社 (id={master_id}) が見つかりません",
        )
    if not merge_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"merge 会社 (id={merge_id}) が見つかりません",
        )

    # 2) safety: master が archived ならマージ不可
    if master_row["status"] == "archived":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="master 会社が archived 状態のため、マージ先として使用できません。先に master を active に戻してください。",
        )

    # 3) 副テーブルのスナップショット（master の old / merge の最終状態の両方）。
    #    audit_log 用。merge 元側は DELETE で消えるので必ず先に取る。
    master_old_subs = await _snapshot_company_subtables(db, master_id)
    merge_final_subs = await _snapshot_company_subtables(db, merge_id)

    # 4) 商談 / 注文 / 見積 / 請求書 の company_id を merge → master に付け替え。
    #    deals/orders/quotes/invoices の company_id FK は ON DELETE 指定なし (NO ACTION)
    #    のため、付け替えずに company を DELETE すると 23503 で失敗する。
    reassigned_deals = (await db.execute(
        text("UPDATE deals SET company_id = :master WHERE company_id = :merge"),
        {"master": master_id, "merge": merge_id},
    )).rowcount or 0
    reassigned_orders = (await db.execute(
        text("UPDATE orders SET company_id = :master WHERE company_id = :merge"),
        {"master": master_id, "merge": merge_id},
    )).rowcount or 0
    reassigned_quotes = (await db.execute(
        text("UPDATE quotes SET company_id = :master WHERE company_id = :merge"),
        {"master": master_id, "merge": merge_id},
    )).rowcount or 0
    reassigned_invoices = (await db.execute(
        text("UPDATE invoices SET company_id = :master WHERE company_id = :merge"),
        {"master": master_id, "merge": merge_id},
    )).rowcount or 0

    # 5) contacts.company_id を付け替え。
    #    contacts は ON DELETE CASCADE のため、付け替えなければ company DELETE で
    #    巻き込まれて消える。先に master へ移管する。
    #    is_primary_contact は (company_id) WHERE is_primary_contact=TRUE の部分UNIQUE
    #    INDEX があるため、master に既に primary がある状態で merge 元 primary を
    #    そのまま移すと UNIQUE 違反になる。merge 元 primary は is_primary_contact=FALSE
    #    に降格したうえで移管する（master 側の primary を維持するのが運用上自然）。
    has_master_primary_res = await db.execute(
        text("SELECT 1 FROM contacts WHERE company_id = :cid AND is_primary_contact = TRUE LIMIT 1"),
        {"cid": master_id},
    )
    master_has_primary = has_master_primary_res.scalar() is not None
    if master_has_primary:
        await db.execute(
            text(
                "UPDATE contacts SET is_primary_contact = FALSE "
                "WHERE company_id = :merge AND is_primary_contact = TRUE"
            ),
            {"merge": merge_id},
        )
    reassigned_contacts = (await db.execute(
        text("UPDATE contacts SET company_id = :master WHERE company_id = :merge"),
        {"master": master_id, "merge": merge_id},
    )).rowcount or 0

    # 6) company_addresses を付け替え。
    #    company_addresses には (company_id, address_type, branch_name) の自然な一意性
    #    制約は無いが、IS DEFAULT は (company_id, address_type) WHERE is_default=TRUE
    #    の部分UNIQUE INDEX で保護される。master に既に既定がある状態で merge 元の
    #    既定をそのまま移管すると UNIQUE 違反になるため、merge 元側を非既定に降格して
    #    から付け替える。branch_name の重複は許容（merge 元の支店として残す）。
    master_default_billing_res = await db.execute(
        text(
            "SELECT 1 FROM company_addresses "
            "WHERE company_id = :cid AND address_type = 'billing' AND is_default = TRUE LIMIT 1"
        ),
        {"cid": master_id},
    )
    master_has_default_billing = master_default_billing_res.scalar() is not None
    master_default_delivery_res = await db.execute(
        text(
            "SELECT 1 FROM company_addresses "
            "WHERE company_id = :cid AND address_type = 'delivery' AND is_default = TRUE LIMIT 1"
        ),
        {"cid": master_id},
    )
    master_has_default_delivery = master_default_delivery_res.scalar() is not None

    if master_has_default_billing:
        await db.execute(
            text(
                "UPDATE company_addresses SET is_default = FALSE "
                "WHERE company_id = :merge AND address_type = 'billing' AND is_default = TRUE"
            ),
            {"merge": merge_id},
        )
    if master_has_default_delivery:
        await db.execute(
            text(
                "UPDATE company_addresses SET is_default = FALSE "
                "WHERE company_id = :merge AND address_type = 'delivery' AND is_default = TRUE"
            ),
            {"merge": merge_id},
        )

    # branch_name は重複可。同じ branch_name が master 側にあれば識別を保つために
    # suffix を付ける（merge 元 company_code を末尾につけて運用者が起源を追えるように）。
    merge_company_code = merge_row["company_code"]
    suffix = f" (merged from {merge_company_code})"

    addr_dup_res = await db.execute(
        text(
            "SELECT ma.id, COALESCE(ma.branch_name, '') AS original_branch_name "
            "FROM company_addresses ma "
            "WHERE ma.company_id = :merge AND EXISTS ("
            "  SELECT 1 FROM company_addresses x "
            "  WHERE x.company_id = :master "
            "    AND x.address_type = ma.address_type "
            "    AND COALESCE(x.branch_name, '') = COALESCE(ma.branch_name, '')"
            ")"
        ),
        {"master": master_id, "merge": merge_id},
    )
    dup_records = [(row[0], row[1]) for row in addr_dup_res.fetchall()]
    # PR #164 round1 Minor 4: branch_name は VARCHAR(100)。suffix 付けで 100 字を
    # 超えると LEFT で切り詰められて元の支店名が不可逆に潰れる。再マージで suffix が
    # 積み重なるケースも考えて、切り詰めが発生したら audit_log に元 branch_name を
    # 残し、運用ログにも警告を出して気づけるようにする。
    branch_name_truncations: list[dict] = []
    for dup_id, original_branch in dup_records:
        combined = f"{original_branch}{suffix}"
        if len(combined) > 100:
            branch_name_truncations.append({
                "address_id": dup_id,
                "original_branch_name": original_branch,
                "suffix": suffix,
                "stored_branch_name": combined[:100],
                "dropped_chars": len(combined) - 100,
            })
            logger.warning(
                "merge_companies: branch_name が VARCHAR(100) を超えたため切り詰め "
                "(master=%d, merge=%d, address_id=%d, original=%r, dropped=%d 文字)",
                master_id, merge_id, dup_id, original_branch, len(combined) - 100,
            )
        await db.execute(
            text(
                "UPDATE company_addresses "
                "SET branch_name = LEFT(COALESCE(branch_name, '') || :suffix, 100) "
                "WHERE id = :id"
            ),
            {"suffix": suffix, "id": dup_id},
        )

    moved_addresses = (await db.execute(
        text("UPDATE company_addresses SET company_id = :master WHERE company_id = :merge"),
        {"master": master_id, "merge": merge_id},
    )).rowcount or 0

    # 7) company_sales_channels を merge → master に追加（PK = (company_id, channel) のため
    #    INSERT ... SELECT ON CONFLICT DO NOTHING で重複は弾く）。merge 元の行は
    #    company DELETE 時に CASCADE で消えるので明示削除は不要だが、視認性のため明示削除する。
    moved_channels = (await db.execute(
        text(
            "INSERT INTO company_sales_channels (company_id, channel) "
            "SELECT :master, channel FROM company_sales_channels WHERE company_id = :merge "
            "ON CONFLICT (company_id, channel) DO NOTHING"
        ),
        {"master": master_id, "merge": merge_id},
    )).rowcount or 0
    await db.execute(
        text("DELETE FROM company_sales_channels WHERE company_id = :merge"),
        {"merge": merge_id},
    )

    # 8) Forward-compat defensive guard (PR #164 round1 Major 1):
    #    Phase 1-B-2 の移行期に作られた `_customer_migration_map.new_company_id` は
    #    `REFERENCES companies(id)` (ON DELETE NO ACTION) を持つため、本表が残存している
    #    環境では merge 元 company の DELETE が 23503 で必ず失敗する。
    #    本番では migration 036 が deploy.yml 経由で全テナントに適用済みのため map は
    #    既に DROP 済み（よって本コードは no-op になるはず）だが、ロールバック後の
    #    一時的な再生成・別環境の pre-036 状態など、map が残っているケースに備えて
    #    DELETE 直前に「行が存在すれば new_company_id を master に付け替える」防御を入れる。
    #    `pg_tables` で物理存在を確認してから UPDATE することで、map が無い環境では
    #    無駄な SQL を発行しない。
    map_exists_res = await db.execute(
        text(
            "SELECT 1 FROM pg_tables "
            "WHERE schemaname = current_schema() AND tablename = '_customer_migration_map'"
        )
    )
    if map_exists_res.scalar() is not None:
        await db.execute(
            text(
                "UPDATE _customer_migration_map "
                "SET new_company_id = :master "
                "WHERE new_company_id = :merge"
            ),
            {"master": master_id, "merge": merge_id},
        )

    # 9) merge 元 company を削除。CASCADE で残った副テーブル（既に空のはず）も整理される。
    #    deals/orders/quotes/invoices/contacts/addresses/channels は全て master に移動済み。
    #    `_customer_migration_map` も step 8 で付け替え済み（map が存在する環境のみ）。
    try:
        await db.execute(text("DELETE FROM companies WHERE id = :id"), {"id": merge_id})
    except IntegrityError as e:
        # 想定外: 把握していない FK 参照が残っていた場合。明示 rollback で他 endpoint
        # (create_company / delete_company) と流儀を揃える。get_db でも保険的に rollback
        # されるが、ここで明示的に呼ぶことで以降に commit が紛れ込んだ場合の事故を防げる。
        await db.rollback()
        logger.error(
            "merge_companies: 想定外の FK 参照で merge 元の DELETE に失敗 "
            "(master=%d, merge=%d): %s", master_id, merge_id, e.orig,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "merge 元会社を削除できませんでした（想定外の関連レコードが残存しています）。"
                "管理者に連絡してください。"
            ),
        )

    # 10) master の status が pending_dedup_review なら active に昇格
    promoted = False
    if master_row["status"] == "pending_dedup_review":
        await db.execute(
            text("UPDATE companies SET status = 'active', updated_at = NOW() WHERE id = :id"),
            {"id": master_id},
        )
        promoted = True

    # 11) 監査ログ記録
    #     - master 側: action=update, 副テーブル diff（new = master_old + merge_final 全部 added）
    #       + _merge メタデータ（merge_id / 件数 / 理由）
    #     - merge 元: action=delete, old_data に最終状態（本体 + 副テーブル）
    master_new_subs = await _snapshot_company_subtables(db, master_id)
    sub_diff = build_subtable_diff(master_old_subs, master_new_subs)

    reason = data.reason if data and data.reason else None
    # PR #164 round1 Minor 2: master 側の audit log は update_company と同じ流儀で
    # `new_data` のトップレベルに変更後カラムを直接載せる。merge は本体カラムを
    # status の active 昇格以外いじらないため、promoted=True のときだけ status を
    # 上乗せする。これで old_data (status='pending_dedup_review') と対称な diff が
    # audit log 閲覧 UI 側で読める。
    master_audit_payload: dict = {
        "_merge": {
            "merge_id": merge_id,
            "merge_company_code": merge_company_code,
            "merge_company_name": merge_row["name"],
            "reason": reason,
            "reassigned": {
                "contacts": reassigned_contacts,
                "deals": reassigned_deals,
                "orders": reassigned_orders,
                "quotes": reassigned_quotes,
                "invoices": reassigned_invoices,
                "addresses": moved_addresses,
                "sales_channels": moved_channels,
            },
            "status_promoted_to_active": promoted,
        },
    }
    if promoted:
        master_audit_payload["status"] = "active"
    # PR #164 round1 Minor 4: branch_name 切り詰めが発生したら _merge に痕跡を残す。
    if branch_name_truncations:
        master_audit_payload["_merge"]["branch_name_truncations"] = branch_name_truncations
    if sub_diff:
        master_audit_payload["_subtables"] = sub_diff

    await record_audit_log(
        db=db, tenant_id=tenant_id, user_id=current_user.id,
        action="update", table_name="companies", record_id=master_id,
        old_data=dict(master_row), new_data=master_audit_payload,
    )

    # merge 元の最終状態を delete log に残す。副テーブルの中身は既に master へ移動済みのため、
    # snapshot は移動「前」の状態（merge_final_subs）を記録する。
    merge_old_data: dict = dict(merge_row)
    merge_sub_diff = build_subtable_diff(
        merge_final_subs,
        {"company_addresses": [], "company_sales_channels": []},
    )
    if merge_sub_diff:
        merge_old_data["_subtables"] = merge_sub_diff
    merge_old_data["_merge"] = {
        "merged_into_company_id": master_id,
        "merged_into_company_code": master_row["company_code"],
        "reason": reason,
    }
    await record_audit_log(
        db=db, tenant_id=tenant_id, user_id=current_user.id,
        action="delete", table_name="companies", record_id=merge_id,
        old_data=merge_old_data,
    )

    await db.commit()
    await reset_tenant_context(db, tenant_id)  # ADR-072 Phase 2.5
    await invalidate_dashboard_cache(tenant_id)

    fetched = await db.execute(
        text(f"SELECT {_COMPANY_COLUMNS} FROM companies WHERE id = :id"),
        {"id": master_id},
    )
    row = fetched.mappings().first()
    return await _compose_response(db, dict(row))
