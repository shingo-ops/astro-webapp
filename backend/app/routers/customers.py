from __future__ import annotations

"""
顧客管理API（CRUD）。Phase 1 再設計版。

テナントスキーマの customers 本体 + 3副テーブル（customer_addresses /
customer_sales_channels / customer_discord）を一括で扱う。

search_path は get_current_tenant dependency で自動切り替え済み。

変更履歴:
  2026-04-16: Phase 1拡張（請求先/配送先、customer_code自動採番、
    require_permission権限チェック統合）
  2026-04-23: Phase 1 再設計（副テーブル化、billing_/delivery_ フラット列を廃止）
"""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from app.auth.dependencies import get_current_user, get_current_tenant, require_permission
from app.cache import invalidate_dashboard_cache
from app.database import get_db
from app.models import User
from app.schemas.customer import (
    CustomerAddressInput,
    CustomerAddressResponse,
    CustomerContactChannelInput,
    CustomerContactChannelResponse,
    CustomerCreate,
    CustomerDiscordInput,
    CustomerDiscordResponse,
    CustomerResponse,
    CustomerUpdate,
)
from app.services.audit import record_audit_log

router = APIRouter()

# 本体の SELECT 列（副テーブルは別クエリで取得）
_CUSTOMER_COLUMNS = """
    id, tenant_id, customer_code, lead_id, sales_rep_id, company_name,
    trust_level, priority_focus,
    per_order_amount, monthly_frequency,
    monthly_forecast, monthly_forecast_source, monthly_forecast_updated_at,
    meeting_requested,
    billing_display_name, payment_recipient_name,
    fedex_account, shipping_note, primary_contact_channel, status,
    created_at, updated_at
"""

# PATCH で更新を許可する本体カラム（副テーブルは別処理）
_UPDATABLE_COLUMNS = {
    "lead_id", "sales_rep_id", "company_name",
    "trust_level", "priority_focus",
    "per_order_amount", "monthly_frequency",
    "monthly_forecast", "monthly_forecast_source",
    "meeting_requested",
    "billing_display_name", "payment_recipient_name",
    "fedex_account", "shipping_note", "primary_contact_channel", "status",
}


async def _fetch_addresses(db: AsyncSession, customer_id: int) -> list[CustomerAddressResponse]:
    res = await db.execute(
        text("""
            SELECT id, address_type, name, email, telephone, tax_id,
                   address_line_1, address_line_2, address_line_3,
                   city, state, zip, country_code
            FROM customer_addresses WHERE customer_id = :cid
            ORDER BY
                CASE address_type WHEN 'billing' THEN 0 WHEN 'delivery' THEN 1 ELSE 2 END,
                id
        """),
        {"cid": customer_id},
    )
    return [CustomerAddressResponse(**row) for row in res.mappings().all()]


async def _fetch_sales_channels(db: AsyncSession, customer_id: int) -> list[str]:
    res = await db.execute(
        text("SELECT channel FROM customer_sales_channels WHERE customer_id = :cid ORDER BY channel"),
        {"cid": customer_id},
    )
    return [row.channel for row in res.fetchall()]


async def _fetch_discord(db: AsyncSession, customer_id: int) -> CustomerDiscordResponse | None:
    res = await db.execute(
        text("""
            SELECT is_joined, channel_id, user_id, invoice_webhook, shipment_webhook
            FROM customer_discord WHERE customer_id = :cid
        """),
        {"cid": customer_id},
    )
    row = res.mappings().first()
    return CustomerDiscordResponse(**row) if row else None


async def _fetch_contact_channels(db: AsyncSession, customer_id: int) -> list[CustomerContactChannelResponse]:
    res = await db.execute(
        text("""
            SELECT id, channel, purpose, is_primary
            FROM customer_contact_channels
            WHERE customer_id = :cid
            ORDER BY is_primary DESC, id
        """),
        {"cid": customer_id},
    )
    return [CustomerContactChannelResponse(**row) for row in res.mappings().all()]


async def _compose_response(db: AsyncSession, main_row: dict) -> CustomerResponse:
    """本体行 + 副テーブルの値を集めて CustomerResponse を組み立てる。"""
    cid = main_row["id"]
    return CustomerResponse(
        **main_row,
        addresses=await _fetch_addresses(db, cid),
        sales_channels=await _fetch_sales_channels(db, cid),
        discord=await _fetch_discord(db, cid),
        contact_channels=await _fetch_contact_channels(db, cid),
    )


async def _replace_addresses(db: AsyncSession, customer_id: int, addresses: list[CustomerAddressInput]) -> None:
    """DELETE 後に全件 INSERT でソース値に一致させる（冪等）"""
    await db.execute(
        text("DELETE FROM customer_addresses WHERE customer_id = :cid"),
        {"cid": customer_id},
    )
    for addr in addresses:
        await db.execute(
            text("""
                INSERT INTO customer_addresses (
                    customer_id, address_type, name, email, telephone, tax_id,
                    address_line_1, address_line_2, address_line_3,
                    city, state, zip, country_code
                ) VALUES (
                    :cid, :atype, :name, :email, :telephone, :tax_id,
                    :l1, :l2, :l3, :city, :state, :zip, :country
                )
            """),
            {
                "cid": customer_id,
                "atype": addr.address_type.value,
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
            },
        )


async def _replace_sales_channels(db: AsyncSession, customer_id: int, channels: list[str]) -> None:
    await db.execute(
        text("DELETE FROM customer_sales_channels WHERE customer_id = :cid"),
        {"cid": customer_id},
    )
    for ch in channels:
        if not ch:
            continue
        await db.execute(
            text("""
                INSERT INTO customer_sales_channels (customer_id, channel)
                VALUES (:cid, :ch)
                ON CONFLICT (customer_id, channel) DO NOTHING
            """),
            {"cid": customer_id, "ch": ch.strip()},
        )


async def _replace_contact_channels(
    db: AsyncSession, customer_id: int, channels: list[CustomerContactChannelInput]
) -> None:
    """contact_channels を DELETE + INSERT で全置換。is_primary=TRUE は最大1つに制約される（部分UNIQUE INDEX）"""
    await db.execute(
        text("DELETE FROM customer_contact_channels WHERE customer_id = :cid"),
        {"cid": customer_id},
    )
    # is_primary=TRUE の重複を避けるため Python 側で1つに絞る（先着優先）
    primary_seen = False
    for ch in channels:
        is_primary = ch.is_primary and not primary_seen
        if is_primary:
            primary_seen = True
        await db.execute(
            text("""
                INSERT INTO customer_contact_channels (customer_id, channel, purpose, is_primary)
                VALUES (:cid, :channel, :purpose, :is_primary)
            """),
            {
                "cid": customer_id,
                "channel": ch.channel,
                "purpose": ch.purpose,
                "is_primary": is_primary,
            },
        )


async def _sync_primary_contact_channel(db: AsyncSession, customer_id: int) -> None:
    """contact_channels の is_primary=TRUE から customers.primary_contact_channel を同期（後方互換）"""
    await db.execute(
        text("""
            UPDATE customers SET primary_contact_channel = (
                SELECT channel FROM customer_contact_channels
                WHERE customer_id = :cid AND is_primary = TRUE
                LIMIT 1
            )
            WHERE id = :cid
        """),
        {"cid": customer_id},
    )


async def _upsert_discord(db: AsyncSession, customer_id: int, data: CustomerDiscordInput | None) -> None:
    """data=None なら既存行を削除、値があれば upsert。
    Major 4 対応: customer_discord と customer_contact_channels の整合性を保つため、
    discord 行が存在する場合は contact_channels にも channel='discord' を自動追加する。
    """
    if data is None:
        await db.execute(
            text("DELETE FROM customer_discord WHERE customer_id = :cid"),
            {"cid": customer_id},
        )
        # 案α: contact_channels の channel='discord' 行は削除しない
        # （ユーザーが明示的に Discord タブを無効化した時に、連絡ツールタブで
        #   Discord を設定していたとしたらそれは意図的な使い分けの可能性があるため）
        return
    await db.execute(
        text("""
            INSERT INTO customer_discord (
                customer_id, is_joined, channel_id, user_id,
                invoice_webhook, shipment_webhook
            ) VALUES (
                :cid, :is_joined, :channel_id, :user_id, :invoice_webhook, :shipment_webhook
            )
            ON CONFLICT (customer_id) DO UPDATE SET
                is_joined = EXCLUDED.is_joined,
                channel_id = EXCLUDED.channel_id,
                user_id = EXCLUDED.user_id,
                invoice_webhook = EXCLUDED.invoice_webhook,
                shipment_webhook = EXCLUDED.shipment_webhook,
                updated_at = NOW()
        """),
        {
            "cid": customer_id,
            "is_joined": data.is_joined,
            "channel_id": data.channel_id,
            "user_id": data.user_id,
            "invoice_webhook": data.invoice_webhook,
            "shipment_webhook": data.shipment_webhook,
        },
    )
    # Discord を連絡手段として使用宣言（案α）
    # is_joined=TRUE の場合のみ、contact_channels に channel='discord' 行が無ければ追加
    if data.is_joined:
        await db.execute(
            text("""
                INSERT INTO customer_contact_channels (customer_id, channel, purpose, is_primary)
                SELECT :cid, 'discord', 'Discord連携', FALSE
                WHERE NOT EXISTS (
                    SELECT 1 FROM customer_contact_channels
                    WHERE customer_id = :cid AND channel = 'discord'
                )
            """),
            {"cid": customer_id},
        )


# ========== エンドポイント ==========


@router.get(
    "/customers",
    response_model=list[CustomerResponse],
    dependencies=[Depends(require_permission("customers.view"))],
)
async def list_customers(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None, max_length=255),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """顧客一覧を取得する。検索は customer_code / company_name / billing_display_name を対象とする。"""
    offset = (page - 1) * per_page

    if search:
        result = await db.execute(
            text(f"""
                SELECT {_CUSTOMER_COLUMNS}
                FROM customers
                WHERE customer_code ILIKE :search
                   OR company_name ILIKE :search
                   OR billing_display_name ILIKE :search
                ORDER BY updated_at DESC
                LIMIT :limit OFFSET :offset
            """),
            {"search": f"%{search}%", "limit": per_page, "offset": offset},
        )
    else:
        result = await db.execute(
            text(f"""
                SELECT {_CUSTOMER_COLUMNS}
                FROM customers
                ORDER BY updated_at DESC
                LIMIT :limit OFFSET :offset
            """),
            {"limit": per_page, "offset": offset},
        )

    rows = result.mappings().all()
    return [await _compose_response(db, dict(row)) for row in rows]


@router.get(
    "/customers/{customer_id}",
    response_model=CustomerResponse,
    dependencies=[Depends(require_permission("customers.view"))],
)
async def get_customer(
    customer_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """顧客詳細（副テーブル付き）を取得する。"""
    result = await db.execute(
        text(f"SELECT {_CUSTOMER_COLUMNS} FROM customers WHERE id = :id"),
        {"id": customer_id},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="顧客が見つかりません")
    return await _compose_response(db, dict(row))


@router.post(
    "/customers",
    response_model=CustomerResponse,
    status_code=201,
    dependencies=[Depends(require_permission("customers.create"))],
)
async def create_customer(
    data: CustomerCreate,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """
    顧客を登録する（本体 + 副テーブル）。customer_code は未指定なら
    CT-{id:05d} 形式でサーバー側自動採番する（旧実装との互換性維持）。
    """
    try:
        # customer_code 自動採番は Python 側で処理（Postgres/SQLite 両対応）:
        #   1. 明示指定があればそのまま使用
        #   2. 未指定なら一時コードを UUID で生成して UNIQUE 制約を満たし、
        #      INSERT 後に id を使って CT-{id:05d} へ UPDATE する
        explicit_code = data.customer_code and data.customer_code.strip()
        # CT-PEND-<8hex> = 最大 16 文字 (VARCHAR(20) に収まる)。
        # 旧 f"CT-PENDING-{uuid.uuid4().hex}" は 43 文字で VARCHAR(20) 超過のバグ（companies.py 側の Playwright 検証で発覚）。
        # 本番ではこの経路が UI 未経由（migration script が customer_code 明示指定）だったため気付かれなかった。
        customer_code = explicit_code if explicit_code else f"CT-PEND-{uuid.uuid4().hex[:8]}"
        # 月間見込み予測の source / updated_at は Python 側で決定（NOW() は dialect 依存）
        now_for_forecast = (
            data.monthly_forecast_source.value if data.monthly_forecast_source else "manual"
        ) if data.monthly_forecast is not None else None

        result = await db.execute(
            text("""
                INSERT INTO customers (
                    tenant_id, customer_code, lead_id, sales_rep_id, company_name,
                    trust_level, priority_focus,
                    per_order_amount, monthly_frequency,
                    monthly_forecast, monthly_forecast_source, monthly_forecast_updated_at,
                    meeting_requested,
                    billing_display_name, payment_recipient_name,
                    fedex_account, shipping_note, primary_contact_channel, status
                ) VALUES (
                    :tenant_id, :customer_code,
                    :lead_id, :sales_rep_id, :company_name,
                    :trust_level, :priority_focus,
                    :per_order_amount, :monthly_frequency,
                    :monthly_forecast, :monthly_forecast_source, :monthly_forecast_updated_at,
                    :meeting_requested,
                    :billing_display_name, :payment_recipient_name,
                    :fedex_account, :shipping_note, :primary_contact_channel, :status
                )
                RETURNING id
            """),
            {
                "tenant_id": tenant_id,
                "customer_code": customer_code,
                "lead_id": data.lead_id,
                "sales_rep_id": data.sales_rep_id,
                "company_name": data.company_name,
                "trust_level": data.trust_level,
                "priority_focus": data.priority_focus,
                "per_order_amount": data.per_order_amount,
                "monthly_frequency": data.monthly_frequency,
                "monthly_forecast": data.monthly_forecast,
                "monthly_forecast_source": now_for_forecast,
                # NOW() は dialect 依存なので、後続 UPDATE で trigger 経由 or 明示更新
                "monthly_forecast_updated_at": None,
                "meeting_requested": data.meeting_requested,
                "billing_display_name": data.billing_display_name,
                "payment_recipient_name": data.payment_recipient_name,
                "fedex_account": data.fedex_account,
                "shipping_note": data.shipping_note,
                "primary_contact_channel": data.primary_contact_channel,
                "status": data.status.value,
            },
        )
        new_id = result.scalar_one()

        # customer_code 未指定なら CT-{id:05d} 形式へ置き換え
        if not explicit_code:
            await db.execute(
                text("UPDATE customers SET customer_code = :code WHERE id = :id"),
                {"code": f"CT-{new_id:05d}", "id": new_id},
            )
        # monthly_forecast があれば updated_at を現在時刻に（NOW() は PG でも SQLite でも動く）
        if data.monthly_forecast is not None:
            await db.execute(
                text("UPDATE customers SET monthly_forecast_updated_at = NOW() WHERE id = :id"),
                {"id": new_id},
            )

        await _replace_addresses(db, new_id, data.addresses)
        await _replace_sales_channels(db, new_id, data.sales_channels)
        await _upsert_discord(db, new_id, data.discord)

        # contact_channels: 明示指定があればそれを使用、未指定なら primary_contact_channel から自動作成
        # Major 3 対応: contact_channels=[] + primary_contact_channel='x' の場合、
        #   明示的に「空の contact_channels」とユーザー指定があるので [] を優先。
        #   その結果、_sync_primary_contact_channel で primary_contact_channel が NULL になる
        #   が、これは意図通り（ユーザーが空を明示指定しているため）。
        if data.contact_channels is not None:
            # is_primary=TRUE の行が contact_channels 内にあるかチェック
            has_primary_in_list = any(c.is_primary for c in data.contact_channels)
            # contact_channels に is_primary が無く primary_contact_channel があれば、
            # その値を is_primary=TRUE の1行として先頭に補完（データ喪失防止）
            channels_to_insert = list(data.contact_channels)
            if (
                not has_primary_in_list
                and data.primary_contact_channel
                and not any(c.channel == data.primary_contact_channel for c in channels_to_insert)
            ):
                channels_to_insert.insert(0, CustomerContactChannelInput(
                    channel=data.primary_contact_channel,
                    purpose="主連絡ツール",
                    is_primary=True,
                ))
            await _replace_contact_channels(db, new_id, channels_to_insert)
        elif data.primary_contact_channel:
            await _replace_contact_channels(db, new_id, [
                CustomerContactChannelInput(
                    channel=data.primary_contact_channel,
                    purpose="主連絡ツール",
                    is_primary=True,
                )
            ])
        await _sync_primary_contact_channel(db, new_id)

        fetched = await db.execute(
            text(f"SELECT {_CUSTOMER_COLUMNS} FROM customers WHERE id = :id"),
            {"id": new_id},
        )
        row = fetched.mappings().first()

        await record_audit_log(
            db=db, tenant_id=tenant_id, user_id=current_user.id,
            action="create", table_name="customers", record_id=new_id,
            new_data=data.model_dump(exclude_none=True, mode="json"),
        )
        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        # 詳細はログにのみ、API には generic なメッセージ（制約名漏洩防止）
        logger.warning("create_customer IntegrityError: tenant=%d, err=%s", tenant_id, e.orig)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="顧客の登録に失敗しました（customer_code 重複または制約違反の可能性）",
        )
    await invalidate_dashboard_cache(tenant_id)
    return await _compose_response(db, dict(row))


@router.patch(
    "/customers/{customer_id}",
    response_model=CustomerResponse,
    dependencies=[Depends(require_permission("customers.update"))],
)
async def update_customer(
    customer_id: int,
    data: CustomerUpdate,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """顧客情報を更新する（部分更新）。副テーブルはフィールドが指定されたときのみ置換。"""
    old_result = await db.execute(
        text(f"SELECT {_CUSTOMER_COLUMNS} FROM customers WHERE id = :id"),
        {"id": customer_id},
    )
    old_row = old_result.mappings().first()
    if not old_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="顧客が見つかりません")

    update_data = data.model_dump(exclude_unset=True, mode="python")
    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="更新するフィールドを少なくとも1つ指定してください",
        )
    # 副テーブル系は本体 UPDATE には入れず、別処理
    addresses = update_data.pop("addresses", None)
    sales_channels = update_data.pop("sales_channels", None)
    discord = update_data.pop("discord", None)
    contact_channels = update_data.pop("contact_channels", None)
    # discord は CustomerDiscordInput 型のままだが model_dump で辞書化されている点に注意
    discord_model: CustomerDiscordInput | None = None
    if discord is not None:
        discord_model = CustomerDiscordInput(**discord)

    # ホワイトリストで不正なキーを除外（防御の二重化）
    update_data = {k: v for k, v in update_data.items() if k in _UPDATABLE_COLUMNS}

    # Enum 値の実体化
    for k, v in list(update_data.items()):
        if hasattr(v, "value"):  # Pydantic Enum
            update_data[k] = v.value

    # monthly_forecast が更新対象に含まれる場合、source / updated_at を連動
    touch_forecast_updated_at = False
    if "monthly_forecast" in update_data:
        if update_data["monthly_forecast"] is None:
            update_data["monthly_forecast_source"] = None
            update_data["monthly_forecast_updated_at"] = None
        else:
            if not update_data.get("monthly_forecast_source"):
                update_data["monthly_forecast_source"] = "manual"
            # updated_at = NOW() はバインド不能のため別 SQL で
            touch_forecast_updated_at = True
            update_data.pop("monthly_forecast_updated_at", None)

    if update_data:
        set_sql = ", ".join(f"{k} = :{k}" for k in update_data)
        params = {**update_data, "id": customer_id}
        await db.execute(
            text(f"UPDATE customers SET {set_sql}, updated_at = NOW() WHERE id = :id"),
            params,
        )

    if touch_forecast_updated_at:
        await db.execute(
            text("UPDATE customers SET monthly_forecast_updated_at = NOW() WHERE id = :id"),
            {"id": customer_id},
        )

    # 副テーブル更新（None=触らない）
    if addresses is not None:
        addresses_models = [CustomerAddressInput(**a) for a in addresses]
        await _replace_addresses(db, customer_id, addresses_models)
    if sales_channels is not None:
        await _replace_sales_channels(db, customer_id, sales_channels)
    if "discord" in data.model_fields_set:
        # 明示的に discord キーを送ってきた場合（None=既存削除、値=upsert）
        await _upsert_discord(db, customer_id, discord_model)

    # Phase 1-B-1: contact_channels の PATCH 処理
    # None = 触らない、[...] = 全置換（空配列も含む）
    if contact_channels is not None:
        ch_models = [
            CustomerContactChannelInput(**c) if isinstance(c, dict) else c
            for c in contact_channels
        ]
        await _replace_contact_channels(db, customer_id, ch_models)
        await _sync_primary_contact_channel(db, customer_id)
    elif "primary_contact_channel" in data.model_fields_set:
        # contact_channels 未指定 + primary_contact_channel 単独更新 → is_primary を同期
        new_pcc = data.primary_contact_channel
        await db.execute(
            text("UPDATE customer_contact_channels SET is_primary = FALSE WHERE customer_id = :cid AND is_primary = TRUE"),
            {"cid": customer_id},
        )
        if new_pcc:
            # 該当 channel が無ければ追加（purpose=主連絡ツール, is_primary=TRUE）
            await db.execute(
                text("""
                    INSERT INTO customer_contact_channels (customer_id, channel, purpose, is_primary)
                    SELECT :cid, :ch, '主連絡ツール', TRUE
                    WHERE NOT EXISTS (
                        SELECT 1 FROM customer_contact_channels
                        WHERE customer_id = :cid AND channel = :ch
                    )
                """),
                {"cid": customer_id, "ch": new_pcc},
            )
            # 既に行があれば is_primary を TRUE に
            await db.execute(
                text("""
                    UPDATE customer_contact_channels SET is_primary = TRUE
                    WHERE customer_id = :cid AND channel = :ch
                """),
                {"cid": customer_id, "ch": new_pcc},
            )

    await record_audit_log(
        db=db, tenant_id=tenant_id, user_id=current_user.id,
        action="update", table_name="customers", record_id=customer_id,
        old_data=dict(old_row), new_data=data.model_dump(exclude_unset=True, mode="json"),
    )
    await db.commit()
    await invalidate_dashboard_cache(tenant_id)

    fetched = await db.execute(
        text(f"SELECT {_CUSTOMER_COLUMNS} FROM customers WHERE id = :id"),
        {"id": customer_id},
    )
    row = fetched.mappings().first()
    return await _compose_response(db, dict(row))


@router.delete(
    "/customers/{customer_id}",
    status_code=204,
    dependencies=[Depends(require_permission("customers.delete"))],
)
async def delete_customer(
    customer_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """顧客を削除する（副テーブルは ON DELETE CASCADE で自動削除）"""
    old_result = await db.execute(
        text(f"SELECT {_CUSTOMER_COLUMNS} FROM customers WHERE id = :id"),
        {"id": customer_id},
    )
    old_row = old_result.mappings().first()
    if not old_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="顧客が見つかりません")

    try:
        await db.execute(text("DELETE FROM customers WHERE id = :id"), {"id": customer_id})
        await record_audit_log(
            db=db, tenant_id=tenant_id, user_id=current_user.id,
            action="delete", table_name="customers", record_id=customer_id,
            old_data=dict(old_row),
        )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="この顧客には関連する商談・注文・見積・請求書があるため削除できません。先に関連データを削除してください。",
        )
    await invalidate_dashboard_cache(tenant_id)
