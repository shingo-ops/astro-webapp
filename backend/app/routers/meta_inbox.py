from __future__ import annotations

"""
Meta Inbox（Phase 1-D）の OAuth 接続 / 切断 / Channels 一覧 endpoints。

本ルーターのカバー範囲:
- Sprint 2: OAuth 接続 + 切断 + Graph API 経由の subscribed_apps 操作
- Sprint 3: `GET /meta/channels` 接続済み Page 一覧（本コミットで追加）
- 会話 / メッセージ送受信 endpoints は Sprint 4 / 5 で追加
- Instagram webhook 拡張は Sprint 6 で webhook.py を改修

既存 `app/routers/meta.py` は Data Deletion 専用のため、本ルーターは別ファイル
として分離している（spec §8-3）。

参考: spec §5-1, §5-2, §6（OAuth フロー詳細）
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import (
    get_current_tenant,
    get_current_user,
    require_permission,
    reset_tenant_context,
)
from app.database import get_db
from app.models import User
from app.services import encryption, meta_graph, oauth_state
from app.services.audit import record_audit_log
from app.services.meta_graph import (
    MetaGraphAPIError,
    MetaGraphError,
    MetaGraphTimeoutError,
    MetaGraphTransportError,
)


logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# 設定
# ---------------------------------------------------------------------------

# OAuth scope（カンマ区切り、7 permission）
# ADR-041: Business Manager 管理 Page を `/me/businesses` 経由で取得するため
# `business_management` を追加。
_OAUTH_SCOPE = ",".join([
    "pages_show_list",
    "pages_manage_metadata",
    "pages_messaging",
    "pages_read_engagement",
    "instagram_basic",
    "instagram_manage_messages",
    "business_management",
])

# 接続後 frontend に飛ばすパス。Sprint 3 で Frontend を実装するまで
# `auto-redirect` の振る舞いだけ提供する。
_FRONTEND_CHANNELS_PATH = "/channels"


def _frontend_base_url() -> str:
    """Frontend のベース URL。`FRONTEND_BASE_URL` 未設定なら ALLOWED_ORIGINS の先頭を使う。"""
    explicit = os.getenv("FRONTEND_BASE_URL")
    if explicit:
        return explicit.rstrip("/")
    origins = os.getenv("ALLOWED_ORIGINS", "")
    first = next((o.strip() for o in origins.split(",") if o.strip()), "")
    return (first or "https://app.salesanchor.jp").rstrip("/")


def _redirect_uri() -> str:
    value = os.getenv("META_OAUTH_REDIRECT_URI", "")
    if not value:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="META_OAUTH_REDIRECT_URI が未設定です。サーバー設定を確認してください",
        )
    return value


def _app_id() -> str:
    value = os.getenv("META_APP_ID", "")
    if not value:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="META_APP_ID が未設定です。サーバー設定を確認してください",
        )
    return value


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _resolve_staff_id(db: AsyncSession, user: User) -> Optional[int]:
    """User → 現テナントスキーマの staff.id を解決する。

    - テナントスキーマに staff テーブルがない（半作成）場合は None
    - primary_email 一致で取得（leads / teams 等と同パターン）
    - 見つからなければ None（None でも tenant_meta_config の connected_by_staff_id は NULL 許容）
    """
    if not user.email:
        return None
    try:
        result = await db.execute(
            text("SELECT id FROM staff WHERE primary_email = :email ORDER BY id ASC LIMIT 1"),
            {"email": user.email},
        )
    except Exception:
        # staff テーブル未存在のケース。Sprint 1 までに全テナントへ展開予定だが
        # フェイルセーフで握りつぶす（OAuth 接続自体は staff_id NULL でも続行可能）。
        logger.warning("staff 解決失敗、connected_by_staff_id を NULL で続行")
        return None
    row = result.first()
    return int(row[0]) if row else None


def _build_authorize_url(state: str) -> str:
    """Facebook OAuth dialog URL を組み立てる。"""
    version = meta_graph.graph_api_version()
    params = {
        "client_id": _app_id(),
        "redirect_uri": _redirect_uri(),
        "state": state,
        "scope": _OAUTH_SCOPE,
        "response_type": "code",
    }
    return f"https://www.facebook.com/{version}/dialog/oauth?{urlencode(params)}"


def _frontend_callback_url(*, status_code: str, **extra: str) -> str:
    """Frontend `/channels?status=...` リダイレクト URL を組み立てる。"""
    params = {"status": status_code, **{k: v for k, v in extra.items() if v}}
    return f"{_frontend_base_url()}{_FRONTEND_CHANNELS_PATH}?{urlencode(params)}"


async def _record_audit_safely(
    db: AsyncSession,
    *,
    tenant_id: int,
    user_id: int,
    action: str,
    table_name: str,
    record_id: Optional[int],
    new_data: Optional[dict] = None,
    old_data: Optional[dict] = None,
) -> None:
    """audit_log 記録の例外を握りつぶす（OAuth フロー本体を守る）。"""
    try:
        await record_audit_log(
            db=db,
            tenant_id=tenant_id,
            user_id=user_id,
            action=action,
            table_name=table_name,
            record_id=record_id,
            old_data=old_data,
            new_data=new_data,
        )
    except Exception:
        logger.warning("audit_log 記録に失敗（無視して継続）", exc_info=True)


def _jsonb_cast_expr(db: AsyncSession) -> str:
    """PostgreSQL では `CAST(:x AS jsonb)`、それ以外（SQLite テスト時）では素の `:x`。"""
    bind = db.get_bind() if hasattr(db, "get_bind") else getattr(db, "bind", None)
    name = getattr(getattr(bind, "dialect", None), "name", "") or ""
    if name.startswith("postgresql"):
        return "CAST(:fields AS jsonb)"
    return ":fields"


async def _upsert_tenant_meta_config(
    db: AsyncSession,
    *,
    tenant_id: int,
    page_id: str,
    page_name: str,
    page_access_token_plain: str,
    page_token_expires_at: Optional[datetime],
    instagram_business_account_id: Optional[str],
    instagram_username: Optional[str],
    subscribed_fields: list[str],
    connected_by_staff_id: Optional[int],
    granted_scopes: Optional[list[str]] = None,
) -> int:
    """Page 接続情報を tenant_meta_config に UPSERT し、新規 / 既存行の id を返す。

    - `is_active=TRUE` の同じ page_id があれば UPDATE
    - 無ければ INSERT（連続接続時に過去 inactive 行が残ってもユニーク条件は
      partial unique index で衝突しない）
    - Page Access Token は **必ず Fernet 暗号化** してから保存（生 token は DB に置かない）
    - `granted_scopes` (ADR-041): 当該 OAuth フローで付与されたスコープを JSONB で保存。
      `business_management` の有無で再認証要否を判定する
    """
    encrypted_token = encryption.encrypt(page_access_token_plain)
    encrypted_token_bytes = encrypted_token.encode("ascii")

    import json as _json
    fields_json = _json.dumps(subscribed_fields)
    scopes_json = _json.dumps(granted_scopes) if granted_scopes is not None else None

    existing = await db.execute(
        text("""
            SELECT id FROM tenant_meta_config
            WHERE tenant_id = :tenant_id AND page_id = :page_id AND is_active = TRUE
            LIMIT 1
        """),
        {"tenant_id": tenant_id, "page_id": page_id},
    )
    row = existing.first()
    fields_expr = _jsonb_cast_expr(db)
    scopes_expr = "NULL" if scopes_json is None else _jsonb_scopes_expr(db)
    if row:
        record_id = int(row[0])
        update_sql = f"""
            UPDATE tenant_meta_config
            SET page_name = :page_name,
                page_access_token_encrypted = :token,
                page_token_expires_at = :expires_at,
                instagram_business_account_id = :ig_id,
                instagram_username = :ig_username,
                subscribed_fields = {fields_expr},
                connected_by_staff_id = COALESCE(:staff_id, connected_by_staff_id),
                last_token_refreshed_at = NOW(),
                updated_at = NOW()
                {"" if scopes_json is None else f", granted_scopes = {scopes_expr}"}
            WHERE id = :id
        """
        params = {
            "id": record_id,
            "page_name": page_name,
            "token": encrypted_token_bytes,
            "expires_at": page_token_expires_at,
            "ig_id": instagram_business_account_id,
            "ig_username": instagram_username,
            "fields": fields_json,
            "staff_id": connected_by_staff_id,
        }
        if scopes_json is not None:
            params["scopes"] = scopes_json
        await db.execute(text(update_sql), params)
        return record_id

    insert_sql = f"""
        INSERT INTO tenant_meta_config (
            tenant_id, page_id, page_name, page_access_token_encrypted,
            page_token_expires_at, instagram_business_account_id, instagram_username,
            subscribed_fields, connected_by_staff_id, is_active{"" if scopes_json is None else ", granted_scopes"}
        )
        VALUES (
            :tenant_id, :page_id, :page_name, :token,
            :expires_at, :ig_id, :ig_username,
            {fields_expr}, :staff_id, TRUE{"" if scopes_json is None else f", {scopes_expr}"}
        )
        RETURNING id
    """
    params = {
        "tenant_id": tenant_id,
        "page_id": page_id,
        "page_name": page_name,
        "token": encrypted_token_bytes,
        "expires_at": page_token_expires_at,
        "ig_id": instagram_business_account_id,
        "ig_username": instagram_username,
        "fields": fields_json,
        "staff_id": connected_by_staff_id,
    }
    if scopes_json is not None:
        params["scopes"] = scopes_json
    inserted = await db.execute(text(insert_sql), params)
    record_id = int(inserted.scalar_one())
    return record_id


def _jsonb_scopes_expr(db: AsyncSession) -> str:
    """granted_scopes 用 JSONB キャスト表現（_jsonb_cast_expr のパラメータ名違いの分離）。"""
    bind = db.get_bind() if hasattr(db, "get_bind") else getattr(db, "bind", None)
    name = getattr(getattr(bind, "dialect", None), "name", "") or ""
    if name.startswith("postgresql"):
        return "CAST(:scopes AS jsonb)"
    return ":scopes"


# ---------------------------------------------------------------------------
# POST /meta/connect/start
# ---------------------------------------------------------------------------


@router.post(
    "/meta/connect/start",
    dependencies=[Depends(require_permission("channels.manage"))],
)
async def connect_start(
    current_user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """OAuth 認可 URL を発行し state を Redis に保存する（spec §5-1, §6-1）。"""
    staff_id = await _resolve_staff_id(db, current_user)

    try:
        issued = await oauth_state.issue_state(
            tenant_id=tenant_id,
            staff_id=staff_id or current_user.id,
        )
    except oauth_state.OAuthStateError as e:
        logger.error("OAuth state 発行失敗: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="一時的に OAuth 接続を開始できません（Redis 接続失敗）",
        )

    auth_url = _build_authorize_url(issued["state"])  # type: ignore[arg-type]
    return {
        "auth_url": auth_url,
        "state": issued["state"],
        "expires_at": issued["expires_at"],
    }


# ---------------------------------------------------------------------------
# GET /meta/connect/callback
# ---------------------------------------------------------------------------


@router.get(
    "/meta/connect/callback",
    dependencies=[Depends(require_permission("channels.manage"))],
)
async def connect_callback(
    code: str = Query(..., min_length=1),
    state: str = Query(..., min_length=1),
    current_user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """OAuth コールバック（spec §5-1, §6-3）。

    1. state 検証（Redis から GETDEL で one-time）
    2. code → 短期 UAT → 長期 UAT
    3. /me/accounts で Page 一覧 + Page Access Token 取得
    4. 各 Page を subscribed_apps 登録
    5. Page ごとに Instagram Business Account 紐付け確認
    6. tenant_meta_config に Fernet 暗号化保存（UPSERT）
    7. audit_log に記録
    """
    try:
        payload = await oauth_state.consume_state(state)
    except oauth_state.OAuthStateError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="一時的に OAuth state を検証できません（Redis 接続失敗）",
        )
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="state が無効です（期限切れ・改ざん・既消費の可能性）",
        )

    # state を発行したテナントと現リクエストのテナントが一致しないと CSRF 成立
    state_tenant_id = payload.get("tenant_id")
    if state_tenant_id is None or int(state_tenant_id) != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="state のテナント情報が一致しません",
        )

    # --- Graph API: code 交換 ---
    redirect_uri = _redirect_uri()
    try:
        short_token = await meta_graph.exchange_code_for_short_token(code, redirect_uri)
        long_token_info = await meta_graph.exchange_short_token_for_long_token(short_token)
    except MetaGraphAPIError as e:
        await _record_audit_safely(
            db, tenant_id=tenant_id, user_id=current_user.id,
            action="oauth_token_exchange_failed", table_name="tenant_meta_config",
            record_id=None, new_data={"meta_error": e.to_audit_dict()},
        )
        await db.commit()
        await reset_tenant_context(db, tenant_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Meta Graph API エラー: {e.error_type or 'unknown'}",
        )
    except MetaGraphTimeoutError:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Meta Graph API がタイムアウトしました。再度お試しください",
        )
    except MetaGraphTransportError as e:
        logger.error("Meta Graph token exchange transport error: %s", e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Meta Graph API への接続に失敗しました",
        )

    long_token = long_token_info["access_token"]
    expires_in = long_token_info.get("expires_in")
    page_token_expires_at: Optional[datetime] = None
    if isinstance(expires_in, int) and expires_in > 0:
        page_token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

    # --- Graph API: Page 一覧（ADR-041: /me/accounts + Business Manager フォールバック） ---
    try:
        pages = await meta_graph.list_user_pages(long_token)
    except MetaGraphAPIError as e:
        # ADR-041 §3: 全経路エラー時は各経路の HTTP エラーをユーザー向け文言に反映
        logger.error(
            "Meta page list failed (all paths): type=%s code=%s",
            e.error_type, e.error_code,
        )
        if e.status_code == 403:
            user_detail = (
                "Facebook 連携の権限が不足しています。"
                "Business Manager の設定または Facebook 連携の権限状態を確認してください"
            )
        else:
            user_detail = (
                "Page 一覧の取得に失敗しました。"
                f"Meta Graph API エラー: {e.error_type or 'unknown'}"
            )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=user_detail,
        )
    except MetaGraphError as e:
        logger.error("Meta page list failed (transport): %s", e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Page 一覧の取得に失敗しました",
        )

    if not pages:
        # ADR-041 §3: 旧文言「Page を作成して再度お試しください」は Business Manager
        # 管理 Page の取得不能を誤誘導していたため、権限状態を確認させる文言に変更。
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "管理可能な Facebook Page が見つかりませんでした。"
                "Facebook 連携の権限状態を確認してください"
                "（Business Manager 管理ページの場合は business_management 権限の付与状況をご確認ください）"
            ),
        )

    staff_id = await _resolve_staff_id(db, current_user)
    connected_pages: list[dict] = []
    failed_pages: list[dict] = []

    for page in pages:
        page_id = page.get("id")
        page_name = page.get("name") or "(unnamed)"
        page_token = page.get("access_token")
        if not page_id or not page_token:
            failed_pages.append({"page_id": page_id, "reason": "missing_id_or_token"})
            continue

        # subscribed_apps 登録
        try:
            subscribed_fields = await meta_graph.subscribe_page_to_app(page_id, page_token)
        except MetaGraphAPIError as e:
            logger.warning("subscribe failed for page %s: %s (code=%s)", page_id, e.error_type, e.error_code)
            failed_pages.append({
                "page_id": page_id,
                "reason": "subscribe_failed",
                "meta_error": e.to_audit_dict(),
            })
            continue
        except MetaGraphError as e:
            logger.warning("subscribe transport error for page %s: %s", page_id, e)
            failed_pages.append({"page_id": page_id, "reason": "subscribe_transport_error"})
            continue

        # Instagram Business Account 取得
        ig_account = page.get("instagram_business_account") or None
        ig_id: Optional[str] = None
        ig_username: Optional[str] = None
        if isinstance(ig_account, dict) and ig_account.get("id"):
            # /me/accounts レスポンスでは id しか入っていないことがあるので、
            # username を含めて取り直す
            try:
                detail = await meta_graph.get_instagram_business_account(page_id, page_token)
                if detail:
                    ig_id = detail.get("id")
                    ig_username = detail.get("username")
            except MetaGraphError as e:
                logger.warning("IG fetch failed for page %s: %s", page_id, e)
                ig_id = ig_account.get("id")  # 最低限 id だけ保存

        # NOTE: `/{ig_user_id}/subscribed_apps` は IG Business Account では常に #100 エラー。
        # Instagram DM は Page-level subscription（subscribe_page_to_app で登録済みの
        # message_reactions を含む fields）で受信できる。IG 側への個別 subscribe は不要。
        # 2026-05-14 hotfix: subscribe_ig_user_to_app() 呼び出しを除去。
        ig_subscribe_error: Optional[dict] = None

        # ADR-024 AC-2: 登録結果の検証。`GET /{page-id}/subscribed_apps` を叩いて
        # 自 App が含まれるか確認し、結果を audit に残す。失敗しても接続自体は通す
        # （Meta の整合反映タイミング差を許容）。
        verification: dict = {"checked": False}
        try:
            apps = await meta_graph.get_page_subscribed_apps(page_id, page_token)
            our_app_id = os.getenv("META_APP_ID", "")
            app_ids = [str(a.get("id")) for a in apps if a.get("id") is not None]
            verification = {
                "checked": True,
                "subscribed_app_ids": app_ids,
                "self_app_subscribed": our_app_id in app_ids if our_app_id else None,
            }
        except MetaGraphError as e:
            logger.warning("subscribed_apps verification failed for page %s: %s", page_id, e)
            verification = {"checked": False, "error": str(e)[:200]}

        # DB 保存
        # ADR-041: 当該 OAuth フローで付与されたスコープを保存（再認証判定用）
        granted_scopes = _OAUTH_SCOPE.split(",")
        record_id = await _upsert_tenant_meta_config(
            db,
            tenant_id=tenant_id,
            page_id=page_id,
            page_name=page_name,
            page_access_token_plain=page_token,
            page_token_expires_at=page_token_expires_at,
            instagram_business_account_id=ig_id,
            instagram_username=ig_username,
            subscribed_fields=subscribed_fields,
            connected_by_staff_id=staff_id,
            granted_scopes=granted_scopes,
        )

        await _record_audit_safely(
            db, tenant_id=tenant_id, user_id=current_user.id,
            action="meta_page_connected", table_name="tenant_meta_config",
            record_id=record_id,
            new_data={
                "page_id": page_id,
                "page_name": page_name,
                "instagram_business_account_id": ig_id,
                "instagram_username": ig_username,
                "subscribed_fields": subscribed_fields,
                "granted_scopes": granted_scopes,
                "ig_subscribe_error": ig_subscribe_error,
                "subscription_verification": verification,
            },
        )

        connected_pages.append({
            "page_id": page_id,
            "page_name": page_name,
            "instagram_business_account_id": ig_id,
            "instagram_username": ig_username,
        })

    await db.commit()
    await reset_tenant_context(db, tenant_id)

    return {
        "connected_pages": connected_pages,
        "failed_pages": failed_pages,
    }


# ---------------------------------------------------------------------------
# GET /meta/connect/oauth-redirect (Browser-driven flow)
# ---------------------------------------------------------------------------
# Sprint 2 では frontend が未実装。Browser → Meta → frontend 経由を Sprint 3 で
# 仕上げるため、本 endpoint は backend 側のテストと API 互換性確保のみ提供する。


# ---------------------------------------------------------------------------
# DELETE /meta/connect/{page_id}
# ---------------------------------------------------------------------------


@router.delete(
    "/meta/connect/{page_id}",
    dependencies=[Depends(require_permission("channels.manage"))],
)
async def connect_delete(
    page_id: str,
    current_user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Page を切断（subscribed_apps 解除 + is_active=FALSE）。"""
    if not page_id or len(page_id) > 50:
        raise HTTPException(status_code=400, detail="page_id が不正です")

    # 該当 active 行を取得
    result = await db.execute(
        text("""
            SELECT id, page_access_token_encrypted
            FROM tenant_meta_config
            WHERE tenant_id = :tenant_id AND page_id = :page_id AND is_active = TRUE
            LIMIT 1
        """),
        {"tenant_id": tenant_id, "page_id": page_id},
    )
    row = result.first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="該当する接続済 Page が見つかりません",
        )
    record_id = int(row[0])
    encrypted_token = row[1]

    # BYTEA → str → decrypt（DB の BYTEA 取り出し方によっては memoryview / bytes になる）
    if isinstance(encrypted_token, (bytes, bytearray, memoryview)):
        encrypted_token_str = bytes(encrypted_token).decode("ascii")
    else:
        encrypted_token_str = str(encrypted_token)

    try:
        page_token = encryption.decrypt(encrypted_token_str)
    except encryption.EncryptionError as e:
        await _record_audit_safely(
            db, tenant_id=tenant_id, user_id=current_user.id,
            action="meta_token_decrypt_failed", table_name="tenant_meta_config",
            record_id=record_id, new_data={"page_id": page_id, "reason": str(e)},
        )
        await db.commit()
        await reset_tenant_context(db, tenant_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="保存トークンの復号に失敗しました（鍵不一致の可能性）",
        )

    # Meta 側 unsubscribe（失敗しても DB の is_active=FALSE は実行する）
    unsubscribe_ok = False
    meta_error_payload: Optional[dict] = None
    try:
        unsubscribe_ok = await meta_graph.unsubscribe_page_from_app(page_id, page_token)
    except MetaGraphAPIError as e:
        meta_error_payload = e.to_audit_dict()
        logger.warning("Meta unsubscribe API error for page %s: %s", page_id, e.error_type)
    except MetaGraphError as e:
        logger.warning("Meta unsubscribe transport error for page %s: %s", page_id, e)

    # DB は必ず is_active=FALSE
    await db.execute(
        text("""
            UPDATE tenant_meta_config
            SET is_active = FALSE,
                deactivated_at = NOW(),
                updated_at = NOW()
            WHERE id = :id
        """),
        {"id": record_id},
    )

    await _record_audit_safely(
        db, tenant_id=tenant_id, user_id=current_user.id,
        action="meta_page_disconnected", table_name="tenant_meta_config",
        record_id=record_id,
        new_data={
            "page_id": page_id,
            "meta_unsubscribe_ok": unsubscribe_ok,
            "meta_error": meta_error_payload,
        },
    )

    await db.commit()
    await reset_tenant_context(db, tenant_id)

    return {
        "page_id": page_id,
        "is_active": False,
        "meta_unsubscribe_ok": unsubscribe_ok,
    }


# ---------------------------------------------------------------------------
# GET /meta/channels — 接続済み Page 一覧（spec §5-2）
# ---------------------------------------------------------------------------


def _format_dt(value) -> Optional[str]:
    """datetime / 文字列 / None を ISO8601 文字列に正規化する。

    SQLite の TIMESTAMP 列は str で返ることがあるためそのまま、
    PostgreSQL は datetime で返るので isoformat() する。
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


@router.get(
    "/meta/channels",
    dependencies=[Depends(require_permission("channels.view"))],
)
async def list_channels(
    include_inactive: bool = Query(False, description="切断済 (is_active=FALSE) を含める"),
    current_user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """接続済み Page / Instagram の一覧を返す（spec §5-2）。

    返却フィールド:
        page_id, page_name, instagram_business_account_id, instagram_username,
        is_active, connected_at, page_token_expires_at,
        connected_by_staff_id, connected_by_staff_name

    **Page Access Token は絶対に返さない**（DB 内で Fernet 暗号化されたまま）。

    並び順: `connected_at DESC`（新しい順）。
    `?include_inactive=true` で切断済も含める（既定 false）。

    tenant 分離は RLS（PostgreSQL 本番）と SQL の WHERE 句（SQLite テスト）の
    両方で実施。SQLite では `tenant_id = :tenant_id` を必須にすることで
    テスト環境でも他テナント行が漏れないようにしている。
    """
    where_clauses = ["tmc.tenant_id = :tenant_id"]
    if not include_inactive:
        where_clauses.append("tmc.is_active = TRUE")
    where_sql = " AND ".join(where_clauses)

    # staff の表示名は `surname_jp` + ' ' + `given_name_jp` を結合（migration 019 のスキーマ）
    # staff テーブルが存在しないテストフィクスチャでも壊れないよう LEFT JOIN + fallback
    # ADR-041: granted_scopes を含めて返却（再認証判定用、未存在カラムでも壊れないように try）
    sql_with_scopes = f"""
        SELECT
            tmc.page_id,
            tmc.page_name,
            tmc.instagram_business_account_id,
            tmc.instagram_username,
            tmc.is_active,
            tmc.connected_at,
            tmc.page_token_expires_at,
            tmc.connected_by_staff_id,
            COALESCE(s.surname_jp || ' ' || s.given_name_jp, s.primary_email) AS staff_name,
            tmc.granted_scopes
        FROM tenant_meta_config tmc
        LEFT JOIN staff s ON s.id = tmc.connected_by_staff_id
        WHERE {where_sql}
        ORDER BY tmc.connected_at DESC, tmc.id DESC
    """
    sql_no_scopes = f"""
        SELECT
            tmc.page_id,
            tmc.page_name,
            tmc.instagram_business_account_id,
            tmc.instagram_username,
            tmc.is_active,
            tmc.connected_at,
            tmc.page_token_expires_at,
            tmc.connected_by_staff_id,
            COALESCE(s.surname_jp || ' ' || s.given_name_jp, s.primary_email) AS staff_name,
            NULL AS granted_scopes
        FROM tenant_meta_config tmc
        LEFT JOIN staff s ON s.id = tmc.connected_by_staff_id
        WHERE {where_sql}
        ORDER BY tmc.connected_at DESC, tmc.id DESC
    """
    rows: list = []
    try:
        result = await db.execute(text(sql_with_scopes), {"tenant_id": tenant_id})
        rows = result.fetchall()
    except Exception:
        # granted_scopes 列が未適用のテナント / テストフィクスチャ
        logger.warning("list_channels: granted_scopes 列なしで再試行")
        try:
            result = await db.execute(text(sql_no_scopes), {"tenant_id": tenant_id})
            rows = result.fetchall()
        except Exception:
            # staff テーブル自体が無いケース
            logger.warning("list_channels: staff JOIN 失敗、staff_name なしで再試行")
            sql_fallback = f"""
                SELECT
                    tmc.page_id,
                    tmc.page_name,
                    tmc.instagram_business_account_id,
                    tmc.instagram_username,
                    tmc.is_active,
                    tmc.connected_at,
                    tmc.page_token_expires_at,
                    tmc.connected_by_staff_id,
                    NULL AS staff_name,
                    NULL AS granted_scopes
                FROM tenant_meta_config tmc
                WHERE {where_sql}
                ORDER BY tmc.connected_at DESC, tmc.id DESC
            """
            result = await db.execute(text(sql_fallback), {"tenant_id": tenant_id})
            rows = result.fetchall()

    channels = []
    for row in rows:
        scopes_raw = row[9]
        granted_scopes: Optional[list[str]] = _parse_scopes(scopes_raw)
        # ADR-041: business_management 不在 → 再認証が必要
        requires_reauth = (
            granted_scopes is not None
            and "business_management" not in granted_scopes
        )
        channels.append({
            "page_id": row[0],
            "page_name": row[1],
            "instagram_business_account_id": row[2],
            "instagram_username": row[3],
            "is_active": bool(row[4]),
            "connected_at": _format_dt(row[5]),
            "page_token_expires_at": _format_dt(row[6]),
            "connected_by_staff_id": row[7],
            "connected_by_staff_name": row[8],
            "granted_scopes": granted_scopes,
            "requires_reauth": requires_reauth,
        })
    return {"channels": channels}


def _parse_scopes(value) -> Optional[list[str]]:
    """granted_scopes 列を list[str] に正規化する（JSONB / TEXT どちらでも処理）。"""
    if value is None:
        return None
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            import json as _json
            parsed = _json.loads(s)
            if isinstance(parsed, list):
                return [str(v) for v in parsed]
        except (ValueError, TypeError):
            return None
    return None


# ---------------------------------------------------------------------------
# GET /conversations — 会話一覧（spec §5-3）
# ---------------------------------------------------------------------------


def _parse_iso_to_aware(value) -> Optional[datetime]:
    """datetime / 文字列 / None → tz-aware datetime（UTC 仮定）に正規化。

    SQLite は TIMESTAMP 列を str で返すことがあるため、両方扱えるようにする。
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    # 文字列パース
    s = str(value).strip()
    if not s:
        return None
    # SQLite の "2026-04-30 12:00:00+00:00" 形式を ISO 形式に寄せる
    s_iso = s.replace(" ", "T", 1)
    try:
        dt = datetime.fromisoformat(s_iso)
    except ValueError:
        # "+00:00" 等が無いケースは UTC 仮定
        try:
            dt = datetime.fromisoformat(s_iso + "+00:00")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _compute_window_expires(last_inbound_at: Optional[datetime]) -> Optional[str]:
    """last_inbound_at + 24h を ISO 文字列で返す（None 入力なら None）。"""
    if last_inbound_at is None:
        return None
    return (last_inbound_at + timedelta(hours=24)).isoformat()


@router.get(
    "/conversations",
    dependencies=[Depends(require_permission("messaging.view"))],
)
async def list_conversations(
    platform: str = Query("all", pattern="^(all|messenger|instagram)$"),
    unread_only: bool = Query(False),
    page_id: Optional[str] = Query(None, max_length=50),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """会話一覧（lead 単位で集約）を返す（spec §5-3）。

    返却フィールド:
        lead_id, lead_code, customer_name, platform, page_id,
        last_message_text, last_message_at, last_message_direction,
        unread_count, messaging_window_expires_at

    並び順: `last_message_at DESC`（最新会話が先）。
    pagination: limit/offset。Spec §5-3 では cursor も触れるが、MVP は offset 方式で十分。

    tenant 分離は RLS（PostgreSQL 本番）と SQL の WHERE 句（SQLite テスト）の
    両方で実施。

    フィルタ:
        - `unread_only=true`: unread_count > 0 の会話のみ
        - `platform`: messenger / instagram / all（既定 all）
        - `page_id`: Phase 1-E F14-S5 で追加。指定すると meta_messages.page_id 一致のみ
          （Messenger 限定。IG メッセージは page_id NULL のため除外される）

    実装メモ:
        - CTE + ROW_NUMBER() OVER (PARTITION BY lead_id) で lead ごとの最新メッセージを
          1 パスで取得する（SQLite 3.25+ / PostgreSQL 両対応）。
        - 旧実装の 3 重相関サブクエリ（N×2+1 回実行）から 3 回の GROUP BY/集計に削減。
        - latest CTE: platform/page_id フィルタを適用（表示する会話を絞る）
        - agg CTE: フィルタなし（全プラットフォームの未読数・最終受信日を集計、旧実装と同じ挙動）
        - leads は LEFT JOIN（leads が削除済みの場合 customer_name=NULL で出すため）。
    """
    params: dict = {"tenant_id": tenant_id, "limit": limit, "offset": offset}

    # latest CTE に適用する追加フィルタ（platform / page_id）
    latest_extra = ""
    if platform != "all":
        latest_extra += " AND mm.platform = :platform"
        params["platform"] = platform
    if page_id:
        latest_extra += " AND mm.page_id = :page_id"
        params["page_id"] = page_id

    # CTE + ROW_NUMBER() で lead ごとの最新メッセージを 1 パスで取得。
    # SQLite 3.25+（プロジェクト使用 3.51.0）および PostgreSQL 12+ で動作。
    sql = f"""
        WITH latest AS (
            SELECT
                mm.lead_id,
                mm.platform,
                mm.page_id,
                mm.message_text,
                mm.direction,
                mm.created_at,
                ROW_NUMBER() OVER (
                    PARTITION BY mm.lead_id
                    ORDER BY mm.created_at DESC, mm.id DESC
                ) AS rn
            FROM meta_messages mm
            WHERE mm.tenant_id = :tenant_id
              AND mm.lead_id IS NOT NULL
              {latest_extra}
        ),
        agg AS (
            SELECT
                mm.lead_id,
                COUNT(CASE WHEN mm.direction = 'inbound' AND mm.seen_at IS NULL THEN 1 END)
                    AS unread_count,
                MAX(CASE WHEN mm.direction = 'inbound' THEN mm.created_at END)
                    AS last_inbound_at
            FROM meta_messages mm
            WHERE mm.tenant_id = :tenant_id
              AND mm.lead_id IS NOT NULL
            GROUP BY mm.lead_id
        )
        SELECT
            l.id                    AS lead_id,
            l.lead_code             AS lead_code,
            l.customer_name         AS customer_name,
            l.status                AS lead_status,
            lat.platform            AS platform,
            lat.page_id             AS page_id,
            lat.message_text        AS last_message_text,
            lat.direction           AS last_message_direction,
            lat.created_at          AS last_message_at,
            COALESCE(agg.unread_count, 0) AS unread_count,
            agg.last_inbound_at     AS last_inbound_at
        FROM latest lat
        LEFT JOIN leads l
            ON l.id = lat.lead_id
           AND l.tenant_id = :tenant_id
        LEFT JOIN agg
            ON agg.lead_id = lat.lead_id
        WHERE lat.rn = 1
        ORDER BY lat.created_at DESC, lat.lead_id DESC
        LIMIT :limit OFFSET :offset
    """

    try:
        result = await db.execute(text(sql), params)
        rows = result.mappings().all()
    except Exception as e:
        logger.error("list_conversations 失敗: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="会話一覧の取得に失敗しました",
        )

    conversations: list[dict] = []
    for row in rows:
        unread_count = int(row.get("unread_count") or 0)
        if unread_only and unread_count <= 0:
            continue
        last_inbound_at = _parse_iso_to_aware(row.get("last_inbound_at"))
        conversations.append({
            "lead_id": row["lead_id"],
            "lead_code": row["lead_code"],
            "customer_name": row["customer_name"],
            "lead_status": row.get("lead_status"),
            "platform": row["platform"],
            "page_id": row.get("page_id"),
            "last_message_text": row["last_message_text"],
            "last_message_at": _format_dt(row["last_message_at"]),
            "last_message_direction": row["last_message_direction"],
            "unread_count": unread_count,
            "messaging_window_expires_at": _compute_window_expires(last_inbound_at),
        })

    return {"conversations": conversations, "next_cursor": None}


# ---------------------------------------------------------------------------
# GET /conversations/stream — SSE リアルタイム通知（Phase 2）
# ---------------------------------------------------------------------------
import asyncio

from starlette.requests import Request
from starlette.responses import StreamingResponse

_SSE_HEARTBEAT_SEC = 30  # nginx proxy_read_timeout(3600s) より十分短く


@router.get(
    "/conversations/stream",
    dependencies=[Depends(require_permission("messages.read"))],
)
async def stream_inbox_updates(
    request: Request,
    tenant_id: int = Depends(get_current_tenant),
) -> StreamingResponse:
    """
    SSE で Inbox 更新を通知する。
    - delta は送らず「変更あり」通知のみ（フロントが loadConversations() で再取得）
    - 30 秒ごとにハートビート ping
    - テナントあたり SSE_MAX_CONN_PER_TENANT 接続まで（超過時 503）
    """
    from app.services.sse_pubsub import (
        decrement_connection,
        increment_connection,
        subscribe_inbox,
    )

    if not await increment_connection(tenant_id):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SSE接続数が上限に達しています",
        )

    async def event_generator():
        gen = subscribe_inbox(tenant_id)
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    await asyncio.wait_for(gen.__anext__(), timeout=_SSE_HEARTBEAT_SEC)
                    yield "event: update\ndata: {}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"  # ハートビート（コメント行）
                except StopAsyncIteration:
                    break
        finally:
            await gen.aclose()
            await decrement_connection(tenant_id)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # nginx バッファリング無効化（二重防御）
            "Connection": "keep-alive",
        },
    )
