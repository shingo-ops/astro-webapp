from __future__ import annotations

"""
スタッフ管理 API。Phase 1 再設計版。

テナントスキーマの staff / staff_emails / staff_ui_preferences に対する
CRUD を提供する。UI設定は ネストで含めて返す/更新する。

変更履歴:
  2026-04-23: 初版作成（Phase 1 再設計 スプリント C）
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
from app.database import get_db
from app.models import User
from app.schemas.staff import StaffCreate, StaffEmailInput, StaffResponse, StaffUIPreferences, StaffUpdate
from app.services.audit import record_audit_log

logger = logging.getLogger(__name__)
router = APIRouter()

_STAFF_COLS = """
    s.id, s.tenant_id, s.user_id, s.staff_code, s.surname_jp, s.given_name_jp,
    s.surname_kana, s.given_name_kana, s.surname_en, s.given_name_en,
    s.primary_email, s.discord_user_id, s.role_id, s.status, s.firebase_uid,
    s.is_employee,
    s.created_at, s.updated_at,
    r.name AS role_name
"""

_UPDATABLE = {
    "surname_jp", "given_name_jp", "surname_kana", "given_name_kana",
    "surname_en", "given_name_en", "primary_email", "discord_user_id",
    "role_id", "status", "firebase_uid", "user_id", "is_employee",
}


async def _fetch_emails(db: AsyncSession, staff_id: int) -> list[str]:
    res = await db.execute(
        text("SELECT email FROM staff_emails WHERE staff_id = :sid ORDER BY id"),
        {"sid": staff_id},
    )
    return [row.email for row in res.fetchall()]


async def _fetch_ui_prefs(db: AsyncSession, staff_id: int) -> StaffUIPreferences | None:
    res = await db.execute(
        text("""
            SELECT dark_mode, show_chat_menu, show_sales_menu, show_settings_menu,
                   show_admin_menu, show_sidebar
            FROM staff_ui_preferences WHERE staff_id = :sid
        """),
        {"sid": staff_id},
    )
    row = res.mappings().first()
    return StaffUIPreferences(**row) if row else None


async def _fetch_locale(db: AsyncSession, primary_email: str) -> str:
    """public.users の locale カラムを取得（ADR-027）。"""
    result = await db.execute(
        text("SELECT locale FROM public.users WHERE email = :email LIMIT 1"),
        {"email": primary_email},
    )
    row = result.mappings().first()
    return row["locale"] if row and row["locale"] else "ja"


async def _fetch_theme(db: AsyncSession, primary_email: str) -> str:
    """public.users の theme カラムを取得（ADR-033）。"""
    result = await db.execute(
        text("SELECT theme FROM public.users WHERE email = :email LIMIT 1"),
        {"email": primary_email},
    )
    row = result.mappings().first()
    return row["theme"] if row and row["theme"] else "light"


async def _compose(db: AsyncSession, main_row: dict) -> StaffResponse:
    sid = main_row["id"]
    return StaffResponse(
        **main_row,
        emails=await _fetch_emails(db, sid),
        ui_preferences=await _fetch_ui_prefs(db, sid),
        locale=await _fetch_locale(db, main_row["primary_email"]),
        theme=await _fetch_theme(db, main_row["primary_email"]),
    )


async def _upsert_ui_prefs(db: AsyncSession, staff_id: int, prefs: StaffUIPreferences | None) -> None:
    """UI設定を upsert。prefs=None なら StaffUIPreferences のデフォルト値で行を作る。

    migration 019 の design は「役割権限 AND 本人のUI設定」で最終表示を決めるため、
    staff_ui_preferences 行は全スタッフに存在すべき。POST /staff で ui_preferences
    省略時もデフォルト値で行を作成する。
    """
    if prefs is None:
        prefs = StaffUIPreferences()  # pydantic デフォルト値
    await db.execute(
        text("""
            INSERT INTO staff_ui_preferences (
                staff_id, dark_mode, show_chat_menu, show_sales_menu,
                show_settings_menu, show_admin_menu, show_sidebar
            ) VALUES (:sid, :dm, :chat, :sales, :settings, :admin, :sidebar)
            ON CONFLICT (staff_id) DO UPDATE SET
                dark_mode = EXCLUDED.dark_mode,
                show_chat_menu = EXCLUDED.show_chat_menu,
                show_sales_menu = EXCLUDED.show_sales_menu,
                show_settings_menu = EXCLUDED.show_settings_menu,
                show_admin_menu = EXCLUDED.show_admin_menu,
                show_sidebar = EXCLUDED.show_sidebar,
                updated_at = NOW()
        """),
        {
            "sid": staff_id, "dm": prefs.dark_mode,
            "chat": prefs.show_chat_menu, "sales": prefs.show_sales_menu,
            "settings": prefs.show_settings_menu, "admin": prefs.show_admin_menu,
            "sidebar": prefs.show_sidebar,
        },
    )


async def _replace_additional_emails(
    db: AsyncSession, staff_id: int, emails: list[StaffEmailInput]
) -> None:
    """副メール群を全削除 → 全 INSERT で置換（冪等）"""
    await db.execute(
        text("DELETE FROM staff_emails WHERE staff_id = :sid"),
        {"sid": staff_id},
    )
    for e in emails:
        await db.execute(
            text("""
                INSERT INTO staff_emails (staff_id, email, purpose)
                VALUES (:sid, :email, :purpose)
                ON CONFLICT (staff_id, email) DO NOTHING
            """),
            {"sid": staff_id, "email": e.email, "purpose": e.purpose},
        )


@router.get("/staff/me", response_model=StaffResponse)
async def get_my_staff(
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """
    現在ログイン中ユーザの staff レコードを返す。

    ロジック:
      users.email と staff.primary_email の一致で staff を引く。
      共有メール運用（migration 019: primary_email に UNIQUE 制約なし）に対応するため
      `ORDER BY s.id ASC` で決定性を担保し、最も古い staff レコードを返す。
      見つからなければ 404 を返す。

    実装メモ:
      当初は firebase_uid 経路を主、email を fallback として設計したが、
      `User` モデル（app/models.py）に `firebase_uid` カラムが無いため
      `getattr(current_user, "firebase_uid", None)` は常に None を返し、
      firebase_uid 経路は dead code になっていた（PR #166 review F1）。
      `User` モデル側に firebase_uid を追加する改修は本 PR スコープ外のため、
      経路を削除して email 一意路線に揃え、決定性は `ORDER BY` で確保する。
      将来 `users.firebase_uid` を実装する場合は別 PR でこのエンドポイントに
      経路を再導入する（その際は `ORDER BY` も維持）。

    アクセス制御:
      自分の情報を取得する API なので staff.view 権限は不要。
      get_current_user / get_current_tenant のみで十分。
      （B-1 軽量スコープ: ui_preferences 反映のため全ユーザがアクセスできる必要がある）
    """
    user_email = getattr(current_user, "email", None)

    row = None
    if user_email:
        # primary_email の一致で staff を引く。
        # primary_email は UNIQUE 制約なし（共有アドレス運用許容）のため、
        # ORDER BY s.id ASC で決定性を担保する（最も古い staff を返す）。
        result = await db.execute(
            text(f"""
                SELECT {_STAFF_COLS}
                FROM staff s
                LEFT JOIN roles r ON r.id = s.role_id
                WHERE s.primary_email = :email
                ORDER BY s.id ASC
                LIMIT 1
            """),
            {"email": user_email},
        )
        row = result.mappings().first()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="現在のユーザに紐づく staff レコードが見つかりません",
        )
    return await _compose(db, dict(row))


@router.patch("/staff/me/locale", status_code=200)
async def update_my_locale(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    現在ログイン中ユーザの locale を更新する（ADR-027）。
    payload: { "locale": "ja" | "en" }
    """
    locale = payload.get("locale", "ja")
    if locale not in ("ja", "en"):
        raise HTTPException(status_code=400, detail="locale は 'ja' または 'en' のみ有効です")
    user_email = getattr(current_user, "email", None)
    if not user_email:
        raise HTTPException(status_code=401, detail="認証されていません")
    await db.execute(
        text("UPDATE public.users SET locale = :locale WHERE email = :email"),
        {"locale": locale, "email": user_email},
    )
    await db.commit()
    return {"locale": locale}


@router.patch("/staff/me/theme", status_code=200)
async def update_my_theme(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    現在ログイン中ユーザの theme を更新する（ADR-033）。
    payload: { "theme": "light" | "dark" }
    """
    theme = payload.get("theme", "light")
    if theme not in ("light", "dark"):
        raise HTTPException(status_code=400, detail="theme は 'light' または 'dark' のみ有効です")
    user_email = getattr(current_user, "email", None)
    if not user_email:
        raise HTTPException(status_code=401, detail="認証されていません")
    await db.execute(
        text("UPDATE public.users SET theme = :theme WHERE email = :email"),
        {"theme": theme, "email": user_email},
    )
    await db.commit()
    return {"theme": theme}


@router.get("/staff", response_model=list[StaffResponse],
            dependencies=[Depends(require_permission("staff.view"))])
async def list_staff(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None, max_length=255),
    status_filter: str | None = Query(default=None, alias="status"),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    offset = (page - 1) * per_page
    conds: list[str] = []
    params: dict = {"limit": per_page, "offset": offset}
    if search:
        conds.append("(s.staff_code ILIKE :search OR s.surname_jp ILIKE :search OR s.given_name_jp ILIKE :search OR s.primary_email ILIKE :search)")
        params["search"] = f"%{search}%"
    if status_filter:
        conds.append("s.status = :st")
        params["st"] = status_filter
    where = f"WHERE {' AND '.join(conds)}" if conds else ""
    result = await db.execute(
        text(f"""
            SELECT {_STAFF_COLS}
            FROM staff s
            LEFT JOIN roles r ON r.id = s.role_id
            {where}
            ORDER BY s.staff_code
            LIMIT :limit OFFSET :offset
        """),
        params,
    )
    rows = result.mappings().all()
    return [await _compose(db, dict(row)) for row in rows]


@router.get("/staff/{staff_id}", response_model=StaffResponse,
            dependencies=[Depends(require_permission("staff.view"))])
async def get_staff(staff_id: int, db: AsyncSession = Depends(get_db),
                    tenant_id: int = Depends(get_current_tenant),
                    current_user: User = Depends(get_current_user)):
    result = await db.execute(
        text(f"""
            SELECT {_STAFF_COLS}
            FROM staff s
            LEFT JOIN roles r ON r.id = s.role_id
            WHERE s.id = :id
        """),
        {"id": staff_id},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="スタッフが見つかりません")
    return await _compose(db, dict(row))


@router.post("/staff", response_model=StaffResponse, status_code=201,
             dependencies=[Depends(require_permission("staff.create"))])
async def create_staff(data: StaffCreate, db: AsyncSession = Depends(get_db),
                       tenant_id: int = Depends(get_current_tenant),
                       current_user: User = Depends(get_current_user)):
    # role_id 存在検証（同一テナント内）
    check = await db.execute(
        text("SELECT id FROM roles WHERE id = :rid AND tenant_id = :tid"),
        {"rid": data.role_id, "tid": tenant_id},
    )
    if not check.first():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="指定の role_id はこのテナントに存在しません")

    explicit_code = data.staff_code and data.staff_code.strip()
    staff_code = explicit_code if explicit_code else f"EMP-PENDING-{uuid.uuid4().hex}"
    try:
        result = await db.execute(
            text("""
                INSERT INTO staff (
                    tenant_id, user_id, staff_code,
                    surname_jp, given_name_jp, surname_kana, given_name_kana,
                    surname_en, given_name_en, primary_email, discord_user_id,
                    role_id, status, firebase_uid, is_employee
                ) VALUES (
                    :tid, :uid, :code,
                    :sjp, :gjp, :sk, :gk,
                    :sen, :gen, :email, :did,
                    :rid, :st, :fbuid, :is_emp
                )
                RETURNING id
            """),
            {
                "tid": tenant_id, "uid": data.user_id, "code": staff_code,
                "sjp": data.surname_jp, "gjp": data.given_name_jp,
                "sk": data.surname_kana, "gk": data.given_name_kana,
                "sen": data.surname_en, "gen": data.given_name_en,
                "email": data.primary_email, "did": data.discord_user_id,
                "rid": data.role_id, "st": data.status.value,
                "fbuid": data.firebase_uid,
                "is_emp": bool(data.is_employee),
            },
        )
        new_id = result.scalar_one()
        if not explicit_code:
            await db.execute(
                text("UPDATE staff SET staff_code = :code WHERE id = :id"),
                {"code": f"EMP-{new_id:05d}", "id": new_id},
            )
        await _upsert_ui_prefs(db, new_id, data.ui_preferences)
        await _replace_additional_emails(db, new_id, data.additional_emails)
        await record_audit_log(
            db=db, tenant_id=tenant_id, user_id=current_user.id,
            action="create", table_name="staff", record_id=new_id,
            new_data=data.model_dump(exclude_none=True, mode="json"),
        )
        await db.commit()
        await reset_tenant_context(db, tenant_id)  # ADR-072 Phase 2
    except IntegrityError as e:
        await db.rollback()
        logger.warning("create_staff IntegrityError: tenant=%d err=%s", tenant_id, e.orig)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="スタッフの登録に失敗しました（staff_code / discord_user_id / firebase_uid 重複の可能性）",
        )
    fetched = await db.execute(
        text(f"""
            SELECT {_STAFF_COLS}
            FROM staff s
            LEFT JOIN roles r ON r.id = s.role_id
            WHERE s.id = :id
        """),
        {"id": new_id},
    )
    return await _compose(db, dict(fetched.mappings().first()))


@router.patch("/staff/{staff_id}", response_model=StaffResponse,
              dependencies=[Depends(require_permission("staff.update"))])
async def update_staff(staff_id: int, data: StaffUpdate,
                       db: AsyncSession = Depends(get_db),
                       tenant_id: int = Depends(get_current_tenant),
                       current_user: User = Depends(get_current_user)):
    old = await db.execute(
        text(f"SELECT {_STAFF_COLS} FROM staff s LEFT JOIN roles r ON r.id = s.role_id WHERE s.id = :id"),
        {"id": staff_id},
    )
    old_row = old.mappings().first()
    if not old_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="スタッフが見つかりません")

    update_data = data.model_dump(exclude_unset=True, mode="python")
    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="更新するフィールドを少なくとも1つ指定してください")

    ui_prefs = update_data.pop("ui_preferences", None)
    additional_emails = update_data.pop("additional_emails", None)
    update_data = {k: v for k, v in update_data.items() if k in _UPDATABLE}
    for k, v in list(update_data.items()):
        if hasattr(v, "value"):
            update_data[k] = v.value

    if update_data:
        set_sql = ", ".join(f"{k} = :{k}" for k in update_data)
        params = {**update_data, "id": staff_id}
        await db.execute(
            text(f"UPDATE staff SET {set_sql}, updated_at = NOW() WHERE id = :id"),
            params,
        )

    if ui_prefs is not None:
        prefs = StaffUIPreferences(**ui_prefs) if isinstance(ui_prefs, dict) else ui_prefs
        await _upsert_ui_prefs(db, staff_id, prefs)

    # additional_emails: None=触らない、[]=全削除、[...]=置換
    if additional_emails is not None:
        email_models = [StaffEmailInput(**e) if isinstance(e, dict) else e for e in additional_emails]
        await _replace_additional_emails(db, staff_id, email_models)

    await record_audit_log(
        db=db, tenant_id=tenant_id, user_id=current_user.id,
        action="update", table_name="staff", record_id=staff_id,
        old_data=dict(old_row), new_data=data.model_dump(exclude_unset=True, mode="json"),
    )
    await db.commit()
    await reset_tenant_context(db, tenant_id)  # ADR-072 Phase 2: commit 後の SELECT で search_path 喪失を防ぐ

    fetched = await db.execute(
        text(f"SELECT {_STAFF_COLS} FROM staff s LEFT JOIN roles r ON r.id = s.role_id WHERE s.id = :id"),
        {"id": staff_id},
    )
    return await _compose(db, dict(fetched.mappings().first()))


@router.delete("/staff/{staff_id}", status_code=204,
               dependencies=[Depends(require_permission("staff.delete"))])
async def delete_staff(staff_id: int, db: AsyncSession = Depends(get_db),
                       tenant_id: int = Depends(get_current_tenant),
                       current_user: User = Depends(get_current_user)):
    old = await db.execute(
        text(f"SELECT {_STAFF_COLS} FROM staff s LEFT JOIN roles r ON r.id = s.role_id WHERE s.id = :id"),
        {"id": staff_id},
    )
    old_row = old.mappings().first()
    if not old_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="スタッフが見つかりません")
    try:
        # 副テーブルは ON DELETE CASCADE で消える
        await db.execute(text("DELETE FROM staff WHERE id = :id"), {"id": staff_id})
        await record_audit_log(
            db=db, tenant_id=tenant_id, user_id=current_user.id,
            action="delete", table_name="staff", record_id=staff_id,
            old_data=dict(old_row),
        )
        await db.commit()
        await reset_tenant_context(db, tenant_id)  # ADR-072 Phase 2
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="このスタッフは他のレコード（bots.owner_staff_id, customers.sales_rep_id 等）から参照されているため削除できません",
        )
