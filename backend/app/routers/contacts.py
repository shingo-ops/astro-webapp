from __future__ import annotations

"""
担当者管理API（CRUD）。Phase 1-B-2 Step 5b-1 で新設。

テナントスキーマの contacts 本体 + 副テーブル（contact_emails /
contact_discord / contact_contact_channels）を一括で扱う。

エンドポイント:
  GET    /api/v1/contacts                      - 全担当者一覧（検索可）
  GET    /api/v1/contacts/{contact_id}         - 単一担当者
  POST   /api/v1/contacts                      - 新規担当者（company_id 必須）
  PATCH  /api/v1/contacts/{contact_id}         - 部分更新
  DELETE /api/v1/contacts/{contact_id}         - 削除
  GET    /api/v1/companies/{company_id}/contacts - 会社配下の担当者一覧
"""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import (
    get_current_user,
    get_current_tenant,
    require_permission,
    reset_tenant_context,
)
from app.cache import invalidate_dashboard_cache
from app.database import get_db
from app.models import User
from app.schemas.contact import (
    ContactChannelInput,
    ContactChannelResponse,
    ContactCreate,
    ContactDiscordInput,
    ContactDiscordResponse,
    ContactEmailInput,
    ContactEmailResponse,
    ContactResponse,
    ContactUpdate,
)
from app.services.audit import (
    build_subtable_diff,
    record_audit_log,
    snapshot_subtable_rows,
)

# 副テーブル diff のスナップショット対象列（id / *_at は audit.diff_rows 内で除外）。
# 明示列指定にして、新カラム追加時の意図しない diff ノイズを防ぐ。
_AUDIT_EMAIL_COLUMNS = ["email", "purpose"]
_AUDIT_DISCORD_COLUMNS = [
    "is_joined", "channel_id", "user_id", "invoice_webhook", "shipment_webhook",
]
_AUDIT_CHANNEL_COLUMNS = ["channel", "purpose", "is_primary"]


async def _snapshot_contact_subtables(db: AsyncSession, contact_id: int) -> dict[str, object]:
    """audit_log 用に contact の副テーブルをスナップショットする。

    PR #145 F9: companies/contacts の副テーブル変更が audit_logs に記録されない問題の対応。

    contact_discord は 1:1 のため list ではなく単一 dict（または None）として扱う。
    """
    discord_rows = await snapshot_subtable_rows(
        db, "contact_discord", "contact_id", contact_id, _AUDIT_DISCORD_COLUMNS,
    )
    return {
        "contact_emails": await snapshot_subtable_rows(
            db, "contact_emails", "contact_id", contact_id, _AUDIT_EMAIL_COLUMNS,
        ),
        "contact_discord": discord_rows[0] if discord_rows else None,
        "contact_contact_channels": await snapshot_subtable_rows(
            db, "contact_contact_channels", "contact_id", contact_id, _AUDIT_CHANNEL_COLUMNS,
        ),
    }

logger = logging.getLogger(__name__)
router = APIRouter()

_CONTACT_COLUMNS = """
    id, tenant_id, company_id, contact_code, lead_id,
    surname, given_name, display_name, job_title, department,
    is_primary_contact, primary_email, primary_phone,
    status, notes, created_at, updated_at
"""

_UPDATABLE_COLUMNS = {
    "company_id", "lead_id",
    "surname", "given_name", "display_name", "job_title", "department",
    "is_primary_contact", "primary_email", "primary_phone",
    "status", "notes",
}


async def _fetch_emails(db: AsyncSession, contact_id: int) -> list[ContactEmailResponse]:
    res = await db.execute(
        text("SELECT id, email, purpose FROM contact_emails WHERE contact_id = :cid ORDER BY id"),
        {"cid": contact_id},
    )
    return [ContactEmailResponse(**row) for row in res.mappings().all()]


async def _fetch_discord(db: AsyncSession, contact_id: int) -> ContactDiscordResponse | None:
    res = await db.execute(
        text("""
            SELECT is_joined, channel_id, user_id, invoice_webhook, shipment_webhook
            FROM contact_discord WHERE contact_id = :cid
        """),
        {"cid": contact_id},
    )
    row = res.mappings().first()
    return ContactDiscordResponse(**row) if row else None


async def _fetch_contact_channels(db: AsyncSession, contact_id: int) -> list[ContactChannelResponse]:
    res = await db.execute(
        text("""
            SELECT id, channel, purpose, is_primary
            FROM contact_contact_channels
            WHERE contact_id = :cid
            ORDER BY is_primary DESC, id
        """),
        {"cid": contact_id},
    )
    return [ContactChannelResponse(**row) for row in res.mappings().all()]


async def _compose_response(db: AsyncSession, main_row: dict) -> ContactResponse:
    cid = main_row["id"]
    return ContactResponse(
        **main_row,
        emails=await _fetch_emails(db, cid),
        discord=await _fetch_discord(db, cid),
        contact_channels=await _fetch_contact_channels(db, cid),
    )


async def _replace_emails(db: AsyncSession, contact_id: int, emails: list[ContactEmailInput]) -> None:
    await db.execute(
        text("DELETE FROM contact_emails WHERE contact_id = :cid"),
        {"cid": contact_id},
    )
    for em in emails:
        await db.execute(
            text("""
                INSERT INTO contact_emails (contact_id, email, purpose)
                VALUES (:cid, :email, :purpose)
                ON CONFLICT (contact_id, email) DO NOTHING
            """),
            {"cid": contact_id, "email": em.email, "purpose": em.purpose},
        )


async def _upsert_discord(db: AsyncSession, contact_id: int, data: ContactDiscordInput | None) -> None:
    if data is None:
        await db.execute(
            text("DELETE FROM contact_discord WHERE contact_id = :cid"),
            {"cid": contact_id},
        )
        return
    await db.execute(
        text("""
            INSERT INTO contact_discord (
                contact_id, is_joined, channel_id, user_id,
                invoice_webhook, shipment_webhook
            ) VALUES (
                :cid, :is_joined, :channel_id, :user_id, :invoice_webhook, :shipment_webhook
            )
            ON CONFLICT (contact_id) DO UPDATE SET
                is_joined = EXCLUDED.is_joined,
                channel_id = EXCLUDED.channel_id,
                user_id = EXCLUDED.user_id,
                invoice_webhook = EXCLUDED.invoice_webhook,
                shipment_webhook = EXCLUDED.shipment_webhook,
                updated_at = NOW()
        """),
        {
            "cid": contact_id,
            "is_joined": data.is_joined,
            "channel_id": data.channel_id,
            "user_id": data.user_id,
            "invoice_webhook": data.invoice_webhook,
            "shipment_webhook": data.shipment_webhook,
        },
    )
    # is_joined=TRUE の場合、contact_contact_channels に 'discord' 行を自動追加（Phase 1-B-1 と同じ挙動）
    if data.is_joined:
        await db.execute(
            text("""
                INSERT INTO contact_contact_channels (contact_id, channel, purpose, is_primary)
                SELECT :cid, 'discord', 'Discord連携', FALSE
                WHERE NOT EXISTS (
                    SELECT 1 FROM contact_contact_channels
                    WHERE contact_id = :cid AND channel = 'discord'
                )
            """),
            {"cid": contact_id},
        )


async def _replace_contact_channels(
    db: AsyncSession, contact_id: int, channels: list[ContactChannelInput]
) -> None:
    await db.execute(
        text("DELETE FROM contact_contact_channels WHERE contact_id = :cid"),
        {"cid": contact_id},
    )
    primary_seen = False
    for ch in channels:
        is_primary = ch.is_primary and not primary_seen
        if is_primary:
            primary_seen = True
        await db.execute(
            text("""
                INSERT INTO contact_contact_channels (contact_id, channel, purpose, is_primary)
                VALUES (:cid, :channel, :purpose, :is_primary)
            """),
            {
                "cid": contact_id,
                "channel": ch.channel,
                "purpose": ch.purpose,
                "is_primary": is_primary,
            },
        )


async def _clear_primary_contact_flag(db: AsyncSession, company_id: int, keep_contact_id: int | None = None) -> None:
    """指定 company の is_primary_contact=TRUE を全て FALSE にクリア（keep_contact_id 以外）。
    1社1 primary の部分UNIQUE INDEX と整合させるため、新 primary 指定前にクリアする。
    """
    if keep_contact_id is not None:
        await db.execute(
            text("""
                UPDATE contacts SET is_primary_contact = FALSE
                WHERE company_id = :cid AND id != :keep AND is_primary_contact = TRUE
            """),
            {"cid": company_id, "keep": keep_contact_id},
        )
    else:
        await db.execute(
            text("""
                UPDATE contacts SET is_primary_contact = FALSE
                WHERE company_id = :cid AND is_primary_contact = TRUE
            """),
            {"cid": company_id},
        )


# ========== Endpoints ==========


@router.get(
    "/contacts",
    response_model=list[ContactResponse],
    dependencies=[Depends(require_permission("customers.view"))],
)
async def list_contacts(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None, max_length=255),
    company_id: int | None = Query(default=None, description="特定会社の担当者のみ"),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """担当者一覧。検索対象は contact_code / display_name / primary_email / primary_phone。"""
    offset = (page - 1) * per_page
    where_clauses = []
    params: dict = {"limit": per_page, "offset": offset}

    if search:
        where_clauses.append(
            "(contact_code ILIKE :search OR display_name ILIKE :search "
            "OR primary_email ILIKE :search OR primary_phone ILIKE :search "
            "OR surname ILIKE :search OR given_name ILIKE :search)"
        )
        params["search"] = f"%{search}%"
    if company_id is not None:
        where_clauses.append("company_id = :company_id")
        params["company_id"] = company_id

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    # PR #147 review F5: company_id 絞り込み時は CompanyContactSelector のドロップダウンで
    # 主担当を先頭に表示する UX 期待があるため、is_primary_contact DESC を最優先にしつつ、
    # 同じ primary フラグ内では最新更新順を維持する。company_id 絞り込みなしの一覧は従来どおり
    # 更新順（ORDER BY updated_at DESC）。
    order_sql = (
        "ORDER BY is_primary_contact DESC, updated_at DESC"
        if company_id is not None
        else "ORDER BY updated_at DESC"
    )
    result = await db.execute(
        text(f"""
            SELECT {_CONTACT_COLUMNS}
            FROM contacts
            {where_sql}
            {order_sql}
            LIMIT :limit OFFSET :offset
        """),
        params,
    )
    rows = result.mappings().all()
    return [await _compose_response(db, dict(row)) for row in rows]


@router.get(
    "/companies/{company_id}/contacts",
    response_model=list[ContactResponse],
    dependencies=[Depends(require_permission("customers.view"))],
)
async def list_company_contacts(
    company_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """指定会社の全担当者を取得（is_primary_contact=TRUE が先頭）。"""
    # 会社存在チェック
    exists = await db.execute(
        text("SELECT 1 FROM companies WHERE id = :id"),
        {"id": company_id},
    )
    if exists.first() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会社が見つかりません")

    result = await db.execute(
        text(f"""
            SELECT {_CONTACT_COLUMNS}
            FROM contacts
            WHERE company_id = :cid
            ORDER BY is_primary_contact DESC, contact_code
        """),
        {"cid": company_id},
    )
    rows = result.mappings().all()
    return [await _compose_response(db, dict(row)) for row in rows]


@router.get(
    "/contacts/{contact_id}",
    response_model=ContactResponse,
    dependencies=[Depends(require_permission("customers.view"))],
)
async def get_contact(
    contact_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        text(f"SELECT {_CONTACT_COLUMNS} FROM contacts WHERE id = :id"),
        {"id": contact_id},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="担当者が見つかりません")
    return await _compose_response(db, dict(row))


@router.post(
    "/contacts",
    response_model=ContactResponse,
    status_code=201,
    dependencies=[Depends(require_permission("customers.create"))],
)
async def create_contact(
    data: ContactCreate,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """担当者を登録。company_id の会社は同テナントである必要がある（RLS で自動保証）。"""
    # 会社存在確認
    company_exists = await db.execute(
        text("SELECT 1 FROM companies WHERE id = :id"),
        {"id": data.company_id},
    )
    if company_exists.first() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="指定の会社が見つかりません")

    try:
        explicit_code = data.contact_code and data.contact_code.strip()
        # CT-PEND-<8hex> = 最大 16 文字 (VARCHAR(20) に収まる)。
        # companies.py と同じパターンで、StringDataRightTruncationError 500 を回避。
        contact_code = explicit_code if explicit_code else f"CT-PEND-{uuid.uuid4().hex[:8]}"

        # is_primary_contact=TRUE 指定なら既存の primary をクリア
        if data.is_primary_contact:
            await _clear_primary_contact_flag(db, data.company_id)

        result = await db.execute(
            text("""
                INSERT INTO contacts (
                    tenant_id, company_id, contact_code, lead_id,
                    surname, given_name, display_name, job_title, department,
                    is_primary_contact, primary_email, primary_phone,
                    status, notes
                ) VALUES (
                    :tenant_id, :company_id, :contact_code, :lead_id,
                    :surname, :given_name, :display_name, :job_title, :department,
                    :is_primary_contact, :primary_email, :primary_phone,
                    :status, :notes
                )
                RETURNING id
            """),
            {
                "tenant_id": tenant_id,
                "company_id": data.company_id,
                "contact_code": contact_code,
                "lead_id": data.lead_id,
                "surname": data.surname,
                "given_name": data.given_name,
                "display_name": data.display_name,
                "job_title": data.job_title,
                "department": data.department,
                "is_primary_contact": data.is_primary_contact,
                "primary_email": data.primary_email,
                "primary_phone": data.primary_phone,
                "status": data.status.value,
                "notes": data.notes,
            },
        )
        new_id = result.scalar_one()

        if not explicit_code:
            await db.execute(
                text("UPDATE contacts SET contact_code = :code WHERE id = :id"),
                {"code": f"CT-{new_id:05d}", "id": new_id},
            )

        # 順序重要: _replace_contact_channels は冒頭で DELETE するため、
        # _upsert_discord の 'discord' 自動追加より前に呼ぶ必要がある。
        # さもないと Discord 自動追加が即座に消える（PR #121 Critical 1）。
        await _replace_emails(db, new_id, data.emails)
        await _replace_contact_channels(db, new_id, data.contact_channels)
        await _upsert_discord(db, new_id, data.discord)

        fetched = await db.execute(
            text(f"SELECT {_CONTACT_COLUMNS} FROM contacts WHERE id = :id"),
            {"id": new_id},
        )
        row = fetched.mappings().first()

        # PR #145 F9: 副テーブルの初期状態を _subtables.* にスナップショット
        new_subs_snapshot = await _snapshot_contact_subtables(db, new_id)
        new_data_payload: dict = data.model_dump(exclude_none=True, mode="json")
        sub_diff = build_subtable_diff(
            {"contact_emails": [], "contact_discord": None, "contact_contact_channels": []},
            new_subs_snapshot,
        )
        if sub_diff:
            new_data_payload["_subtables"] = sub_diff

        await record_audit_log(
            db=db, tenant_id=tenant_id, user_id=current_user.id,
            action="create", table_name="contacts", record_id=new_id,
            new_data=new_data_payload,
        )
        await db.commit()
        await reset_tenant_context(db, tenant_id)  # ADR-072 Phase 2.5
    except IntegrityError as e:
        await db.rollback()
        logger.warning("create_contact IntegrityError: tenant=%d, err=%s", tenant_id, e.orig)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="担当者の登録に失敗しました（contact_code 重複または制約違反の可能性）",
        )
    await invalidate_dashboard_cache(tenant_id)
    return await _compose_response(db, dict(row))


@router.patch(
    "/contacts/{contact_id}",
    response_model=ContactResponse,
    dependencies=[Depends(require_permission("customers.update"))],
)
async def update_contact(
    contact_id: int,
    data: ContactUpdate,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    old_result = await db.execute(
        text(f"SELECT {_CONTACT_COLUMNS} FROM contacts WHERE id = :id"),
        {"id": contact_id},
    )
    old_row = old_result.mappings().first()
    if not old_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="担当者が見つかりません")

    # PR #145 F9: 副テーブルの old スナップショットを _replace_* 前に取得
    old_subs_snapshot = await _snapshot_contact_subtables(db, contact_id)

    update_data = data.model_dump(exclude_unset=True, mode="python")
    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="更新するフィールドを少なくとも1つ指定してください",
        )
    emails = update_data.pop("emails", None)
    discord = update_data.pop("discord", None)
    contact_channels = update_data.pop("contact_channels", None)

    update_data = {k: v for k, v in update_data.items() if k in _UPDATABLE_COLUMNS}
    for k, v in list(update_data.items()):
        if hasattr(v, "value"):
            update_data[k] = v.value

    # is_primary_contact=TRUE に切替時は既存 primary をクリア（部分UNIQUE INDEX 対応）
    if update_data.get("is_primary_contact") is True:
        company_id_for_primary = update_data.get("company_id")
        if company_id_for_primary is None:
            company_id_for_primary = old_row["company_id"]
        await _clear_primary_contact_flag(db, company_id_for_primary, keep_contact_id=contact_id)

    if update_data:
        set_sql = ", ".join(f"{k} = :{k}" for k in update_data)
        params = {**update_data, "id": contact_id}
        await db.execute(
            text(f"UPDATE contacts SET {set_sql}, updated_at = NOW() WHERE id = :id"),
            params,
        )

    # 順序重要: contact_channels 置換 → discord upsert（Discord 自動追加が消えないように）
    if emails is not None:
        em_models = [ContactEmailInput(**e) for e in emails]
        await _replace_emails(db, contact_id, em_models)
    if contact_channels is not None:
        ch_models = [ContactChannelInput(**c) for c in contact_channels]
        await _replace_contact_channels(db, contact_id, ch_models)
    if "discord" in data.model_fields_set:
        discord_model = ContactDiscordInput(**discord) if discord else None
        await _upsert_discord(db, contact_id, discord_model)

    # PR #145 F9: 副テーブル変更後の new スナップショットと old から diff を組み立てる。
    # 変更されていない副テーブルは old/new 同一で diff_* が None を返すため _subtables から省かれる。
    new_subs_snapshot = await _snapshot_contact_subtables(db, contact_id)
    sub_diff = build_subtable_diff(old_subs_snapshot, new_subs_snapshot)

    new_data_payload: dict = data.model_dump(exclude_unset=True, mode="json")
    if sub_diff:
        new_data_payload["_subtables"] = sub_diff

    await record_audit_log(
        db=db, tenant_id=tenant_id, user_id=current_user.id,
        action="update", table_name="contacts", record_id=contact_id,
        old_data=dict(old_row), new_data=new_data_payload,
    )
    await db.commit()
    await reset_tenant_context(db, tenant_id)  # ADR-072 Phase 2.5
    await invalidate_dashboard_cache(tenant_id)

    fetched = await db.execute(
        text(f"SELECT {_CONTACT_COLUMNS} FROM contacts WHERE id = :id"),
        {"id": contact_id},
    )
    row = fetched.mappings().first()
    return await _compose_response(db, dict(row))


@router.delete(
    "/contacts/{contact_id}",
    status_code=204,
    dependencies=[Depends(require_permission("customers.delete"))],
)
async def delete_contact(
    contact_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """担当者を削除する（副テーブルは ON DELETE CASCADE で自動削除）"""
    old_result = await db.execute(
        text(f"SELECT {_CONTACT_COLUMNS} FROM contacts WHERE id = :id"),
        {"id": contact_id},
    )
    old_row = old_result.mappings().first()
    if not old_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="担当者が見つかりません")

    # PR #145 F9: 副テーブルも CASCADE で消える前にスナップショットを取って old_data に含める
    old_subs_snapshot = await _snapshot_contact_subtables(db, contact_id)
    sub_diff = build_subtable_diff(
        old_subs_snapshot,
        {"contact_emails": [], "contact_discord": None, "contact_contact_channels": []},
    )
    old_data_payload: dict = dict(old_row)
    if sub_diff:
        old_data_payload["_subtables"] = sub_diff

    try:
        await db.execute(text("DELETE FROM contacts WHERE id = :id"), {"id": contact_id})
        await record_audit_log(
            db=db, tenant_id=tenant_id, user_id=current_user.id,
            action="delete", table_name="contacts", record_id=contact_id,
            old_data=old_data_payload,
        )
        await db.commit()
        await reset_tenant_context(db, tenant_id)  # ADR-072 Phase 2.5
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="この担当者には関連する商談・注文・見積・請求書があるため削除できません。先に関連データを削除してください。",
        )
    await invalidate_dashboard_cache(tenant_id)
