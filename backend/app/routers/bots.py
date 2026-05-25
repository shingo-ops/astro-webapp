from __future__ import annotations

"""
Bot 管理 API。Phase 1 再設計版。

テナントスキーマの bots テーブルに対する CRUD。
API キーは作成時のみ平文で返し、DB には bcrypt ハッシュのみ保持する。
API キー再発行（rotate）エンドポイントも提供する。

変更履歴:
  2026-04-23: 初版作成（Phase 1 再設計 スプリント C）
"""

import logging
import secrets
import uuid

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import (
    get_current_tenant,
    get_current_user,
    require_permission,
    tenant_table_ref,
)
from app.database import get_db
from app.models import User
from app.schemas.bot import BotCreate, BotCreatedResponse, BotResponse, BotUpdate
from app.services.audit import record_audit_log

logger = logging.getLogger(__name__)
router = APIRouter()

# ADR-072 Phase 1: ローカル `_is_postgresql` / `_t` は削除し、
# `app.auth.dependencies.tenant_table_ref` を import して使う。


_BOT_COLS = """
    b.id, b.tenant_id, b.bot_code, b.display_name, b.purpose, b.status,
    b.discord_user_id, b.sender_email, b.owner_staff_id,
    b.last_executed_at, b.execution_count, b.created_at, b.updated_at,
    CONCAT(s.surname_jp, ' ', s.given_name_jp) AS owner_staff_name
"""

_UPDATABLE = {
    "display_name", "purpose", "status", "discord_user_id",
    "sender_email", "owner_staff_id",
}


def _generate_api_key() -> tuple[str, str]:
    """(平文APIキー, bcryptハッシュ) のタプルを返す"""
    plain = f"botkey_{secrets.token_urlsafe(32)}"
    hashed = bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")
    return plain, hashed


@router.get("/bots", response_model=list[BotResponse],
            dependencies=[Depends(require_permission("bots.view"))])
async def list_bots(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    purpose: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    offset = (page - 1) * per_page
    conds: list[str] = []
    params: dict = {"limit": per_page, "offset": offset}
    if purpose:
        conds.append("b.purpose = :pp")
        params["pp"] = purpose
    if status_filter:
        conds.append("b.status = :st")
        params["st"] = status_filter
    where = f"WHERE {' AND '.join(conds)}" if conds else ""
    bots_t = tenant_table_ref(db, tenant_id, "bots")
    staff_t = tenant_table_ref(db, tenant_id, "staff")
    result = await db.execute(
        text(f"""
            SELECT {_BOT_COLS}
            FROM {bots_t} b
            LEFT JOIN {staff_t} s ON s.id = b.owner_staff_id
            {where}
            ORDER BY b.bot_code
            LIMIT :limit OFFSET :offset
        """),
        params,
    )
    return [BotResponse(**row) for row in result.mappings().all()]


@router.get("/bots/{bot_id}", response_model=BotResponse,
            dependencies=[Depends(require_permission("bots.view"))])
async def get_bot(bot_id: int, db: AsyncSession = Depends(get_db),
                  tenant_id: int = Depends(get_current_tenant),
                  current_user: User = Depends(get_current_user)):
    bots_t = tenant_table_ref(db, tenant_id, "bots")
    staff_t = tenant_table_ref(db, tenant_id, "staff")
    result = await db.execute(
        text(f"""
            SELECT {_BOT_COLS}
            FROM {bots_t} b
            LEFT JOIN {staff_t} s ON s.id = b.owner_staff_id
            WHERE b.id = :id
        """),
        {"id": bot_id},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Botが見つかりません")
    return BotResponse(**row)


@router.post("/bots", response_model=BotCreatedResponse, status_code=201,
             dependencies=[Depends(require_permission("bots.create"))])
async def create_bot(data: BotCreate, db: AsyncSession = Depends(get_db),
                     tenant_id: int = Depends(get_current_tenant),
                     current_user: User = Depends(get_current_user)):
    # owner_staff_id の存在チェック（同一テナント）
    staff_t = tenant_table_ref(db, tenant_id, "staff")
    check = await db.execute(
        text(f"SELECT id FROM {staff_t} WHERE id = :sid AND tenant_id = :tid"),
        {"sid": data.owner_staff_id, "tid": tenant_id},
    )
    if not check.first():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="指定の owner_staff_id はこのテナントに存在しません")

    explicit_code = data.bot_code and data.bot_code.strip()
    bot_code = explicit_code if explicit_code else f"BOT-PENDING-{uuid.uuid4().hex}"
    plain_key, key_hash = _generate_api_key()

    bots_t = tenant_table_ref(db, tenant_id, "bots")
    try:
        result = await db.execute(
            text(f"""
                INSERT INTO {bots_t} (
                    tenant_id, bot_code, display_name, purpose, status,
                    api_key_hash, discord_user_id, sender_email, owner_staff_id
                ) VALUES (
                    :tid, :code, :name, :purp, :st,
                    :khash, :did, :email, :owner
                )
                RETURNING id
            """),
            {
                "tid": tenant_id, "code": bot_code, "name": data.display_name,
                "purp": data.purpose.value, "st": data.status.value,
                "khash": key_hash, "did": data.discord_user_id,
                "email": data.sender_email, "owner": data.owner_staff_id,
            },
        )
        new_id = result.scalar_one()
        if not explicit_code:
            await db.execute(
                text(f"UPDATE {bots_t} SET bot_code = :code WHERE id = :id"),
                {"code": f"BOT-{new_id:05d}", "id": new_id},
            )
        await record_audit_log(
            db=db, tenant_id=tenant_id, user_id=current_user.id,
            action="create", table_name="bots", record_id=new_id,
            new_data={**data.model_dump(exclude_none=True, mode="json"), "api_key": "(redacted)"},
        )
        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        logger.warning("create_bot IntegrityError: tenant=%d err=%s", tenant_id, e.orig)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Botの登録に失敗しました（bot_code / discord_user_id 重複の可能性）",
        )
    fetched = await db.execute(
        text(f"""
            SELECT {_BOT_COLS}
            FROM {bots_t} b
            LEFT JOIN {staff_t} s ON s.id = b.owner_staff_id
            WHERE b.id = :id
        """),
        {"id": new_id},
    )
    row = dict(fetched.mappings().first())
    # 作成時のみ平文を返す
    return BotCreatedResponse(**row, api_key=plain_key)


@router.patch("/bots/{bot_id}", response_model=BotResponse,
              dependencies=[Depends(require_permission("bots.update"))])
async def update_bot(bot_id: int, data: BotUpdate,
                     db: AsyncSession = Depends(get_db),
                     tenant_id: int = Depends(get_current_tenant),
                     current_user: User = Depends(get_current_user)):
    bots_t = tenant_table_ref(db, tenant_id, "bots")
    staff_t = tenant_table_ref(db, tenant_id, "staff")
    old = await db.execute(
        text(f"SELECT {_BOT_COLS} FROM {bots_t} b LEFT JOIN {staff_t} s ON s.id = b.owner_staff_id WHERE b.id = :id"),
        {"id": bot_id},
    )
    old_row = old.mappings().first()
    if not old_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Botが見つかりません")

    update_data = data.model_dump(exclude_unset=True, mode="python")
    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="更新するフィールドを少なくとも1つ指定してください")
    update_data = {k: v for k, v in update_data.items() if k in _UPDATABLE}
    for k, v in list(update_data.items()):
        if hasattr(v, "value"):
            update_data[k] = v.value

    set_sql = ", ".join(f"{k} = :{k}" for k in update_data)
    params = {**update_data, "id": bot_id}
    await db.execute(
        text(f"UPDATE {bots_t} SET {set_sql}, updated_at = NOW() WHERE id = :id"),
        params,
    )
    await record_audit_log(
        db=db, tenant_id=tenant_id, user_id=current_user.id,
        action="update", table_name="bots", record_id=bot_id,
        old_data=dict(old_row), new_data=data.model_dump(exclude_unset=True, mode="json"),
    )
    await db.commit()

    fetched = await db.execute(
        text(f"SELECT {_BOT_COLS} FROM {bots_t} b LEFT JOIN {staff_t} s ON s.id = b.owner_staff_id WHERE b.id = :id"),
        {"id": bot_id},
    )
    return BotResponse(**dict(fetched.mappings().first()))


@router.post("/bots/{bot_id}/rotate-key", response_model=BotCreatedResponse,
             dependencies=[Depends(require_permission("bots.update"))])
async def rotate_bot_api_key(bot_id: int, db: AsyncSession = Depends(get_db),
                             tenant_id: int = Depends(get_current_tenant),
                             current_user: User = Depends(get_current_user)):
    """API キーを再発行（旧キーは無効化）。平文は1回のみレスポンスで返す。"""
    bots_t = tenant_table_ref(db, tenant_id, "bots")
    staff_t = tenant_table_ref(db, tenant_id, "staff")
    check = await db.execute(text(f"SELECT id FROM {bots_t} WHERE id = :id"), {"id": bot_id})
    if not check.first():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Botが見つかりません")

    plain_key, key_hash = _generate_api_key()
    await db.execute(
        text(f"UPDATE {bots_t} SET api_key_hash = :kh, updated_at = NOW() WHERE id = :id"),
        {"kh": key_hash, "id": bot_id},
    )
    await record_audit_log(
        db=db, tenant_id=tenant_id, user_id=current_user.id,
        action="rotate_key", table_name="bots", record_id=bot_id,
        new_data={"api_key": "(redacted)"},
    )
    await db.commit()

    fetched = await db.execute(
        text(f"SELECT {_BOT_COLS} FROM {bots_t} b LEFT JOIN {staff_t} s ON s.id = b.owner_staff_id WHERE b.id = :id"),
        {"id": bot_id},
    )
    row = dict(fetched.mappings().first())
    return BotCreatedResponse(**row, api_key=plain_key)


@router.delete("/bots/{bot_id}", status_code=204,
               dependencies=[Depends(require_permission("bots.delete"))])
async def delete_bot(bot_id: int, db: AsyncSession = Depends(get_db),
                     tenant_id: int = Depends(get_current_tenant),
                     current_user: User = Depends(get_current_user)):
    bots_t = tenant_table_ref(db, tenant_id, "bots")
    staff_t = tenant_table_ref(db, tenant_id, "staff")
    old = await db.execute(
        text(f"SELECT {_BOT_COLS} FROM {bots_t} b LEFT JOIN {staff_t} s ON s.id = b.owner_staff_id WHERE b.id = :id"),
        {"id": bot_id},
    )
    old_row = old.mappings().first()
    if not old_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Botが見つかりません")
    try:
        await db.execute(text(f"DELETE FROM {bots_t} WHERE id = :id"), {"id": bot_id})
        await record_audit_log(
            db=db, tenant_id=tenant_id, user_id=current_user.id,
            action="delete", table_name="bots", record_id=bot_id,
            old_data=dict(old_row),
        )
        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        logger.warning("delete_bot IntegrityError: tenant=%d bot=%d err=%s", tenant_id, bot_id, e.orig)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="この Bot は他のレコード（会話ログ・通知ログ等）から参照されているため削除できません",
        )
