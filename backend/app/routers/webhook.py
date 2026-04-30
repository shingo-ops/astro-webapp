"""
Meta Webhook 受信 router（Phase 1-D Sprint 6 で Instagram 対応 + tenant_meta_config 連携を追加）。

経緯:
  - Phase 2 で Messenger 受信 → meta_messages 記録 + Discord 通知の最小実装が完了
  - Sprint 1 で `tenant_meta_config` テーブルを新設（page_id / instagram_business_account_id を保持）
  - Sprint 4 で `meta_messages` を拡張（recipient_id / messaging_type / 送信者 / エラー / 既読系）
  - **Sprint 6（本ファイル）** で:
      1. Instagram object（entry[].messaging[] / entry[].changes[].value.messages[]）の受信に対応
      2. テナント特定を **環境変数 META_PAGE_ID 直読み** から **DB tenant_meta_config 参照** に置換
         （META_PAGE_ID は後方互換 fallback として残す）
      3. Messenger と Instagram の DB 書き込みパスを `_persist_meta_message` ヘルパーに共通化

設計判断:
  - 既存 endpoint `POST /api/v1/webhook/messenger` を Messenger / Instagram 兼用に拡張
    （新規 endpoint を切らない方針。Meta App Review の Webhook URL 一本化 + 既存 GET 検証 URL 流用のため）
  - `entry[].messaging[]` と `entry[].changes[]` 両フォーマットを受理
    （Meta は object='instagram' に対しても messaging[] 形式で送ってくることがある）
  - HMAC 検証は両プラットフォームで同一（X-Hub-Signature-256）
  - tenant_id 特定優先順位:
      1) Messenger: tenant_meta_config.page_id == entry.id
         Instagram: tenant_meta_config.instagram_business_account_id == entry.id
            （見つからなければ tenant_meta_config.page_id == entry.id でも fallback 検索）
      2) META_PAGE_ID env と一致する Messenger イベントのみ env fallback で active tenant 取得
"""

import hashlib
import hmac
import json
import logging
import os
from typing import Any, Iterable, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import reset_tenant_context
from app.database import AsyncSessionLocal
from app.routers.notifications import send_discord_notification

router = APIRouter()


# ─────────────────────────────────────────────
# テナント特定ヘルパー（Sprint 6: tenant_meta_config 参照に置換）
# ─────────────────────────────────────────────


def _meta_page_id_env() -> str:
    """環境変数 META_PAGE_ID を都度読みする。

    Sprint 6 まではモジュールロード時に一度だけ読んでいたが、
    テストや設定変更時に runtime で env を切り替えられる方が運用しやすい。
    後方互換 fallback 専用なので、空文字なら fallback 自体を発動させない。
    """
    return os.getenv("META_PAGE_ID", "")


async def _list_active_tenant_ids(db: AsyncSession) -> list[int]:
    """public.tenants から is_active=TRUE のテナント ID を昇順で返す。

    PostgreSQL 本番では `public.tenants` を直接参照する。テスト（SQLite）では
    schema 概念がないため `public.tenants` ビュー / ATTACH ベースで同名アクセス可能。
    """
    try:
        result = await db.execute(
            text("SELECT id FROM public.tenants WHERE is_active = true ORDER BY id")
        )
        return [int(r[0]) for r in result.all()]
    except Exception:
        logging.debug("[Meta] public.tenants 取得失敗", exc_info=True)
        return []


async def _search_tenant_meta_config(
    db: AsyncSession,
    *,
    column: str,
    value: str,
) -> Optional[int]:
    """tenant_meta_config を column=value で逆引きして tenant_id を返す。

    PostgreSQL 本番では tenant_meta_config が per-tenant スキーマに配置されているため、
    public.tenants の active テナントを順に search_path 切替して検索する。
    SQLite テストでは search_path 設定が no-op になり、フラットな
    `tenant_meta_config` テーブルが直接見える前提（RLS なし）。

    column は固定キー（"page_id" / "instagram_business_account_id"）のみ許容。
    SQL injection 防止のためホワイトリストでバリデーションする。
    """
    allowed = {"page_id", "instagram_business_account_id"}
    if column not in allowed:
        raise ValueError(f"unsupported column: {column}")

    # まず単一スキーマ前提（SQLite テスト + 単一テナント運用）で素朴に検索する。
    try:
        result = await db.execute(
            text(f"""
                SELECT tenant_id
                FROM tenant_meta_config
                WHERE {column} = :v AND is_active = TRUE
                ORDER BY id
                LIMIT 1
            """),
            {"v": value},
        )
        row = result.first()
        if row:
            return int(row[0])
    except Exception:
        # 該当 schema にテーブルが見えなければ tenant 横断検索へフォールバック。
        logging.debug(
            "[Meta] tenant_meta_config flat 検索失敗、tenant 横断検索へ",
            exc_info=True,
        )

    # PostgreSQL 本番: 全 active tenant をループしてそれぞれの schema で検索。
    # MVP 期はテナント数 <= 5 を想定、N+1 問題は許容。
    tenant_ids = await _list_active_tenant_ids(db)
    for tid in tenant_ids:
        schema = f"tenant_{tid:03d}"
        try:
            await db.execute(text(f"SET search_path = {schema}, public"))
            await db.execute(text(f"SET app.tenant_id = '{tid}'"))
            result = await db.execute(
                text(f"""
                    SELECT tenant_id
                    FROM tenant_meta_config
                    WHERE {column} = :v AND is_active = TRUE
                    ORDER BY id
                    LIMIT 1
                """),
                {"v": value},
            )
            row = result.first()
            if row:
                return int(row[0])
        except Exception:
            # この schema には tenant_meta_config が無い / アクセス不可 → 次のテナントへ
            logging.debug(
                "[Meta] schema=%s tenant_meta_config 検索失敗", schema, exc_info=True,
            )
            continue
    return None


async def _get_tenant_id_by_page(db: AsyncSession, page_id: str) -> Optional[int]:
    """page_id から tenant_id を取得する（Messenger / Instagram 共通の Page ベース逆引き）。

    優先順位:
      1) tenant_meta_config.page_id（is_active=TRUE）に一致する行があればその tenant_id
         （PostgreSQL では active 全テナントスキーマを順次検索）
      2) META_PAGE_ID env と一致するなら最初の active tenant の id（後方互換 fallback）

    spec §5-7 「既存 META_PAGE_ID 環境変数照合は後方互換 fallback として残す」に対応。

    Phase 1-E F26 fix: `_search_tenant_meta_config` は schema 切替で SET search_path を発行し、
    対象スキーマに `tenant_meta_config` が無いと PostgreSQL session が aborted state に陥る。
    その後で `_list_active_tenant_ids` を呼んでも空 list が返り、env fallback が動かなくなる。
    そのため active tenants の取得は **search_path 切替前**に済ませて値を保持しておく。
    """
    if not page_id:
        return None

    # 0) active tenants を先に取得（schema 切替前なので transaction は clean）。
    #    env fallback で必要だが、_search_tenant_meta_config 実行後は session が
    #    aborted state になっている可能性があり、後から取り直すと空が返ってしまう。
    tenant_ids = await _list_active_tenant_ids(db)

    # 1) DB 由来（Sprint 6 で追加された主経路）
    tid = await _search_tenant_meta_config(db, column="page_id", value=page_id)
    if tid is not None:
        return tid

    # 2) 後方互換 fallback: META_PAGE_ID env と一致した場合のみ
    env_page_id = _meta_page_id_env()
    if env_page_id and page_id == env_page_id and tenant_ids:
        return tenant_ids[0]

    return None


async def _get_tenant_id_by_ig_account(
    db: AsyncSession, ig_business_account_id: str,
) -> Optional[int]:
    """Instagram Business Account ID から tenant_id を取得する（Sprint 6 新規）。

    tenant_meta_config.instagram_business_account_id に登録されている場合のみ返す。
    env fallback は Instagram には用意していない（META_PAGE_ID は Messenger 用のため）。
    """
    if not ig_business_account_id:
        return None
    return await _search_tenant_meta_config(
        db, column="instagram_business_account_id", value=ig_business_account_id,
    )


# ─────────────────────────────────────────────
# GET /api/v1/webhook/messenger
# Meta Webhook URL検証（認証不要、Messenger / Instagram 共用）
# ─────────────────────────────────────────────
@router.get("/webhook/messenger")
async def verify_messenger_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    verify_token = os.getenv("META_VERIFY_TOKEN")
    if not verify_token:
        raise HTTPException(
            status_code=500,
            detail="META_VERIFY_TOKEN is not configured"
        )

    if hub_mode == "subscribe" and hub_verify_token == verify_token:
        logging.info("[Meta] Webhook検証成功")
        return PlainTextResponse(content=hub_challenge)

    raise HTTPException(status_code=403, detail="Forbidden")


# ─────────────────────────────────────────────
# POST /api/v1/webhook/messenger
# Metaメッセージイベント受信（認証不要、Messenger / Instagram 共用）
# ─────────────────────────────────────────────
@router.post("/webhook/messenger")
async def receive_messenger_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
):
    # HMAC-SHA256署名検証
    app_secret = os.getenv("META_APP_SECRET", "")
    signature = request.headers.get("X-Hub-Signature-256", "")
    body_bytes = await request.body()

    expected = "sha256=" + hmac.new(
        app_secret.encode(), body_bytes, hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=403, detail="Invalid signature")

    body = json.loads(body_bytes)

    # TODO: 本格実装時はCeleryタスクに委譲する
    # （BackgroundTasksはワーカーブロックの懸念あり）
    background_tasks.add_task(process_messenger_event, body)
    return {"status": "ok"}


# ─────────────────────────────────────────────
# Webhook event 処理本体
# ─────────────────────────────────────────────


def _iter_inbound_messages(
    entry: dict[str, Any], object_type: str,
) -> Iterable[dict[str, Any]]:
    """entry から inbound message を 1 件ずつ正規化して yield する。

    返却 dict のキー:
      - sender_id:    PSID / IGSID（送信元）
      - message_text: 本文（無ければ空文字）
      - message_id:   Meta の mid（重複防止に使用）
      - timestamp:    raw timestamp（int / None）
      - has_attachments: bool（raw_payload 用）

    対応フォーマット:
      A) entry[].messaging[] (Messenger 標準 + Instagram でも一般的)
      B) entry[].changes[].field='messages' / .value.messages[] (Instagram の旧/別形式)

    Meta は IG webhook を `messaging[]` で配信する場合と `changes[]` で配信する場合があり、
    両方を受理する。
    """
    # ─── A) messaging[] 形式 ───
    for messaging in entry.get("messaging", []) or []:
        if not isinstance(messaging, dict):
            continue
        msg = messaging.get("message")
        if not msg or not isinstance(msg, dict):
            continue
        # echo（自分が送ったメッセージ）はスキップ（is_echo=True）
        if msg.get("is_echo"):
            continue
        sender = messaging.get("sender", {}) or {}
        sender_id = str(sender.get("id", "")) if sender.get("id") is not None else ""
        if not sender_id:
            continue
        yield {
            "sender_id": sender_id,
            "message_text": msg.get("text", "") or "",
            "message_id": msg.get("mid"),
            "timestamp": messaging.get("timestamp"),
            "has_attachments": bool(msg.get("attachments")),
        }

    # ─── B) changes[] 形式（Instagram の field=messages） ───
    if object_type == "instagram":
        for change in entry.get("changes", []) or []:
            if not isinstance(change, dict):
                continue
            if change.get("field") not in (None, "messages"):
                # IG の message 系以外（comments, mentions 等）は MVP では無視
                continue
            value = change.get("value") or {}
            if not isinstance(value, dict):
                continue
            messages = value.get("messages") or []
            if not isinstance(messages, list):
                continue
            for m in messages:
                if not isinstance(m, dict):
                    continue
                from_obj = m.get("from") or {}
                sender_id = str(from_obj.get("id", "")) if isinstance(from_obj, dict) else ""
                if not sender_id:
                    continue
                yield {
                    "sender_id": sender_id,
                    "message_text": m.get("text", "") or "",
                    "message_id": m.get("id") or m.get("mid"),
                    "timestamp": m.get("timestamp") or value.get("timestamp"),
                    "has_attachments": bool(m.get("attachments")),
                }


async def _persist_meta_message(
    db: AsyncSession,
    *,
    tenant_id: int,
    platform: str,
    sender_id: str,
    message_text: str,
    message_id: Optional[str],
    timestamp: Any,
    has_attachments: bool,
) -> Optional[int]:
    """leads upsert + meta_messages INSERT を共通化する Sprint 6 ヘルパー。

    既存 Messenger ロジックの構造をそのまま踏襲（ON CONFLICT DO NOTHING で並列防止 +
    Meta 再送による重複 message_id を弾く）。Instagram も同じパターンで動く。

    Returns:
        新規 INSERT された meta_messages.id、重複（既存 message_id）なら None
    """
    if platform not in ("messenger", "instagram"):
        raise ValueError(f"unsupported platform: {platform}")

    # source_key: spec §3-1 の `messenger:<PSID>` / `instagram:<IGSID>` 形式
    source_key = f"{platform}:{sender_id}"

    # 1) leads 検索 → 無ければ自動作成
    result = await db.execute(
        text("SELECT id FROM leads WHERE source = :source LIMIT 1"),
        {"source": source_key},
    )
    row = result.mappings().first()
    lead_id = row["id"] if row else None

    if lead_id is None:
        customer_name = (
            "Messenger User" if platform == "messenger" else "Instagram User"
        )
        ins = await db.execute(
            text("""
                INSERT INTO leads (
                    tenant_id, customer_name, source, type, status
                )
                VALUES (:tenant_id, :customer_name, :source, :type, :status)
                ON CONFLICT (source)
                    WHERE source LIKE 'messenger:%' OR source LIKE 'instagram:%'
                DO NOTHING
                RETURNING id
            """),
            {
                "tenant_id": tenant_id,
                "customer_name": customer_name,
                "source": source_key,
                "type": "Inbound",
                "status": "新規",
            },
        )
        new_lead_id = ins.scalar_one_or_none()
        if new_lead_id is not None:
            lead_id = new_lead_id
            await db.execute(
                text("UPDATE leads SET lead_code = :code WHERE id = :id"),
                {"code": f"LD-{lead_id:05d}", "id": lead_id},
            )
            await db.commit()
            await reset_tenant_context(db, tenant_id)
        else:
            sel = await db.execute(
                text("SELECT id FROM leads WHERE source = :source LIMIT 1"),
                {"source": source_key},
            )
            lead_id = sel.scalar_one()

    # 2) meta_messages INSERT（Meta 再送で同じ message_id が来たら静かに弾く）
    raw_payload = json.dumps({
        "timestamp": timestamp,
        "has_text": bool(message_text),
        "has_attachments": has_attachments,
    })
    ins = await db.execute(
        text("""
            INSERT INTO meta_messages (
                tenant_id, lead_id, platform,
                sender_id, message_text, direction, raw_payload,
                message_id
            )
            VALUES (
                :tenant_id, :lead_id, :platform,
                :sender_id, :message_text, 'inbound', :raw_payload,
                :message_id
            )
            ON CONFLICT (message_id) WHERE message_id IS NOT NULL
            DO NOTHING
            RETURNING id
        """),
        {
            "tenant_id": tenant_id,
            "lead_id": lead_id,
            "platform": platform,
            "sender_id": sender_id,
            "message_text": message_text,
            "message_id": message_id,
            "raw_payload": raw_payload,
        },
    )
    msg_inserted_id = ins.scalar_one_or_none()
    await db.commit()
    await reset_tenant_context(db, tenant_id)
    return msg_inserted_id


async def process_messenger_event(body: dict) -> None:
    """Meta から受信した Webhook イベントを処理する（Messenger + Instagram 兼用）。

    spec §3-1 のフロー:
      1. body.object で `'page'` (Messenger) / `'instagram'` (IG) を判定
      2. entry[].id でテナント特定（tenant_meta_config 参照、env fallback あり）
      3. _iter_inbound_messages で messaging[] / changes[] 両形式を正規化
      4. _persist_meta_message で leads upsert + meta_messages INSERT
      5. Discord 通知（PII 除去済）
    """
    try:
        object_type = body.get("object")
        if object_type not in ("page", "instagram"):
            # Sprint 5 までは page のみ受理。それ以外（user, etc.）は無視する。
            return

        platform = "messenger" if object_type == "page" else "instagram"

        for entry in body.get("entry", []) or []:
            if not isinstance(entry, dict):
                continue
            entry_id = str(entry.get("id", ""))
            if not entry_id:
                continue

            messages = list(_iter_inbound_messages(entry, object_type))
            if not messages:
                continue

            async with AsyncSessionLocal() as db:
                # テナント特定: entry.id を Messenger は page_id、IG は ig_business_account_id として解釈
                if platform == "messenger":
                    tenant_id = await _get_tenant_id_by_page(db, entry_id)
                else:
                    tenant_id = await _get_tenant_id_by_ig_account(db, entry_id)
                    # IG webhook が page_id 由来で発火するケースがあるため、
                    # IG account 検索で見つからなければ Page ID としても引いてみる。
                    if tenant_id is None:
                        tenant_id = await _get_tenant_id_by_page(db, entry_id)

                if tenant_id is None:
                    logging.warning(
                        "[Meta] テナント特定失敗: object=%s entry_id=%s",
                        object_type, entry_id,
                    )
                    continue

                schema = f"tenant_{tenant_id:03d}"
                await db.execute(text(f"SET search_path = {schema}, public"))
                await db.execute(text(f"SET app.tenant_id = '{tenant_id}'"))

                for m in messages:
                    msg_id = await _persist_meta_message(
                        db,
                        tenant_id=tenant_id,
                        platform=platform,
                        sender_id=m["sender_id"],
                        message_text=m["message_text"],
                        message_id=m["message_id"],
                        timestamp=m["timestamp"],
                        has_attachments=m["has_attachments"],
                    )
                    if msg_id is None:
                        logging.info(
                            "[Meta] Duplicate message_id skipped: %s",
                            m["message_id"],
                        )
                        continue

                    # Discord 通知（個人情報を載せない: 送信者 ID は先頭 8 文字 + ***）
                    sender_id = m["sender_id"]
                    title = (
                        "📩 新着Messengerメッセージ"
                        if platform == "messenger"
                        else "📩 新着Instagram DM"
                    )
                    await send_discord_notification(
                        db=db,
                        tenant_id=tenant_id,
                        event_type="meta_message_received",
                        title=title,
                        message=(
                            f"送信者ID: {sender_id[:8]}***\n"
                            f"プラットフォーム: {platform}"
                        ),
                    )

        logging.info(
            "[Meta] 処理完了: object=%s, entry_count=%d",
            body.get("object", "unknown"),
            len(body.get("entry", []) or []),
        )
    except Exception:
        # M1: logging.exception() でtracebackを含める
        logging.exception("[Meta] Webhookイベント処理エラー")
