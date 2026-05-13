"""
Meta Webhook 受信 router（Phase 1-D Sprint 6 で Instagram 対応 + tenant_meta_config 連携を追加）。

経緯:
  - Phase 2 で Messenger 受信 → meta_messages 記録 + Discord 通知の最小実装が完了
  - Sprint 1 で `tenant_meta_config` テーブルを新設（page_id / instagram_business_account_id を保持）
  - Sprint 4 で `meta_messages` を拡張（recipient_id / messaging_type / 送信者 / エラー / 既読系）
  - **Sprint 6** で:
      1. Instagram object（entry[].messaging[] / entry[].changes[].value.messages[]）の受信に対応
      2. テナント特定を **環境変数 META_PAGE_ID 直読み** から **DB tenant_meta_config 参照** に置換
         （META_PAGE_ID は当時は後方互換 fallback として残置）
      3. Messenger と Instagram の DB 書き込みパスを `_persist_meta_message` ヘルパーに共通化
  - **Phase 1-E F16-S6** で:
      テナント逆引き経路を「全テナント schema 順次切替（N+1）」から
      `public.meta_page_routing` 1 クエリ参照（O(1)）に置換。
      migration 043 + 044 のトリガで tenant_meta_config 変更を public 表へ自動同期。
  - **Phase 1-E F25-S6** で:
      META_PAGE_ID env fallback を削除。F16 routing 表化により本番経路の安定性が
      確保され、後方互換 fallback は不要に。
  - **Phase 1-E F15-S6** で:
      新規 lead 作成時に Graph API `/{psid}?fields=name` を呼び customer_name を
      実名へ置換。失敗時は既定名（"Messenger User" / "Instagram User"）のまま続行。

設計判断:
  - 既存 endpoint `POST /api/v1/webhook/messenger` を Messenger / Instagram 兼用に拡張
    （新規 endpoint を切らない方針。Meta App Review の Webhook URL 一本化 + 既存 GET 検証 URL 流用のため）
  - `entry[].messaging[]` と `entry[].changes[]` 両フォーマットを受理
    （Meta は object='instagram' に対しても messaging[] 形式で送ってくることがある）
  - HMAC 検証は両プラットフォームで同一（X-Hub-Signature-256）
  - tenant_id 特定:
      Messenger: tenant_meta_config.page_id == entry.id
      Instagram: tenant_meta_config.instagram_business_account_id == entry.id
        （見つからなければ tenant_meta_config.page_id == entry.id でも fallback 検索）
      （F25-S6 で META_PAGE_ID env fallback を撤去済）
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
from app.services import encryption, meta_graph

router = APIRouter()


# ─────────────────────────────────────────────
# テナント特定ヘルパー（Sprint 6: tenant_meta_config 参照に置換）
# ─────────────────────────────────────────────


async def _search_tenant_meta_config(
    db: AsyncSession,
    *,
    column: str,
    value: str,
) -> Optional[int]:
    """tenant_meta_config を column=value で逆引きして tenant_id を返す。

    Phase 1-E F16-S6 改修:
      Sprint 6 までは active 全テナントを順次 search_path 切替して検索していた（N+1）。
      本改修で `public.meta_page_routing`（migration 043 + 044 のトリガ同期表）を 1 クエリで
      参照する形に変更。テナント数 N に関わらず O(1) ルックアップ。

    フォールバック順:
      1) PostgreSQL 本番: `public.meta_page_routing` を 1 クエリで検索（O(1)）
      2) SQLite テスト: `public.meta_page_routing` が無いので `tenant_meta_config` を直接検索
         （単一スキーマ・RLS なしのテスト前提）

    column は固定キー（"page_id" / "instagram_business_account_id"）のみ許容。
    SQL injection 防止のためホワイトリストでバリデーションする。
    """
    allowed = {"page_id", "instagram_business_account_id"}
    if column not in allowed:
        raise ValueError(f"unsupported column: {column}")

    # 1) PostgreSQL 本番: 公開ルーティング表で 1-shot 逆引き
    try:
        result = await db.execute(
            text(f"""
                SELECT tenant_id
                FROM public.meta_page_routing
                WHERE {column} = :v AND is_active = TRUE
                ORDER BY tenant_id
                LIMIT 1
            """),
            {"v": value},
        )
        row = result.first()
        if row:
            return int(row[0])
        # routing 表は存在するが該当行なし → トリガで同期されているはずなので None 確定
        return None
    except Exception:
        # routing 表が存在しない（SQLite テスト or migration 043 未適用）
        # → flat フォールバックへ。PG では aborted state を rollback で復帰させる。
        logging.debug(
            "[Meta] meta_page_routing 参照失敗、flat tenant_meta_config へフォールバック",
            exc_info=True,
        )
        try:
            await db.rollback()
        except Exception:
            logging.debug(
                "[Meta] meta_page_routing 参照失敗後の rollback 失敗", exc_info=True
            )

    # 2) SQLite テストパス: フラットな tenant_meta_config を直接検索
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
        logging.debug(
            "[Meta] tenant_meta_config flat 検索失敗", exc_info=True,
        )
        try:
            await db.rollback()
        except Exception:
            logging.debug("[Meta] flat 検索失敗後の rollback 失敗", exc_info=True)

    return None


async def _get_tenant_id_by_page(db: AsyncSession, page_id: str) -> Optional[int]:
    """page_id から tenant_id を取得する（Messenger / Instagram 共通の Page ベース逆引き）。

    Phase 1-E F25-S6 改修:
      これまで `META_PAGE_ID` 環境変数の後方互換 fallback を備えていたが、
      Phase 1-D Sprint 6 で `tenant_meta_config` 主経路 + Phase 1-E F16-S6 で
      `public.meta_page_routing` 高速化が完了したため、env fallback は不要に。
      実装も大幅に簡素化。
    """
    if not page_id:
        return None
    return await _search_tenant_meta_config(db, column="page_id", value=page_id)


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


async def _resolve_page_id_for_ig(
    db: AsyncSession, ig_business_account_id: str,
) -> Optional[str]:
    """Phase 1-E F14-FU1: IG Business Account ID から親 Page ID を逆引きする。

    `tenant_meta_config` の同一行に `page_id` と `instagram_business_account_id` が
    紐づいている前提（migration 040）。受信した IG メッセージに対しても Page フィルタが
    効くように、meta_messages.page_id を Page ID で埋めるための前段処理。

    呼び出し前提:
      - search_path 切替「前」（public.meta_page_routing 経由で 1-shot 解決）
      - 失敗時は None（webhook を落とさず、IG は page_id NULL のまま記録）
    """
    if not ig_business_account_id:
        return None
    # PostgreSQL 本番: public.meta_page_routing で 1 クエリ参照
    try:
        result = await db.execute(
            text(
                "SELECT page_id FROM public.meta_page_routing "
                "WHERE instagram_business_account_id = :ig AND is_active = TRUE "
                "ORDER BY tenant_id LIMIT 1"
            ),
            {"ig": ig_business_account_id},
        )
        row = result.first()
        if row and row[0]:
            return str(row[0])
        return None
    except Exception:
        logging.debug(
            "[Meta] meta_page_routing 参照失敗（IG page_id 解決）", exc_info=True,
        )
        try:
            await db.rollback()
        except Exception:
            pass

    # SQLite テスト: フラット tenant_meta_config を直接検索
    try:
        result = await db.execute(
            text(
                "SELECT page_id FROM tenant_meta_config "
                "WHERE instagram_business_account_id = :ig AND is_active = TRUE "
                "ORDER BY id LIMIT 1"
            ),
            {"ig": ig_business_account_id},
        )
        row = result.first()
        return str(row[0]) if row and row[0] else None
    except Exception:
        logging.debug("[Meta] flat tenant_meta_config 参照失敗（IG page_id 解決）", exc_info=True)
        try:
            await db.rollback()
        except Exception:
            pass
        return None


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


async def _resolve_lead_name_via_graph(
    db: AsyncSession,
    sender_id: str,
    page_id: Optional[str] = None,
) -> Optional[str]:
    """Phase 1-E F15-S6: Page Scoped User ID から Graph API 経由で表示名を取得する。

    Phase 1-E F15-FU1: 複数 Page 接続時の token 取り違えを防ぐため、page_id 指定で
    `tenant_meta_config` を絞り込む。

    呼び出し前提:
      - search_path がテナント schema に設定済み（tenant_meta_config を直接参照）
      - 失敗（権限不足、ネットワーク、復号失敗）は webhook 全体を落とさず None を返す

    Args:
      sender_id: Page Scoped User ID（PSID/IGSID）
      page_id: メッセージ受信元の Page ID。None の場合は最初の active 行を選ぶ
               （旧挙動。複数 Page テナントでは間違える可能性あり）

    フロー:
      1. tenant_meta_config から page_access_token_encrypted を取得
         （page_id 指定なら page_id でフィルタ、なければ ORDER BY id LIMIT 1）
      2. Fernet で復号
      3. Graph API `/{psid}?fields=name` を呼び出し
      4. 取得した name を返す（取れなければ None）
    """
    if not sender_id:
        return None
    try:
        if page_id:
            result = await db.execute(
                text(
                    "SELECT page_access_token_encrypted "
                    "FROM tenant_meta_config "
                    "WHERE page_id = :page_id AND is_active = TRUE "
                    "ORDER BY id LIMIT 1"
                ),
                {"page_id": page_id},
            )
        else:
            result = await db.execute(
                text(
                    "SELECT page_access_token_encrypted "
                    "FROM tenant_meta_config "
                    "WHERE is_active = TRUE "
                    "ORDER BY id LIMIT 1"
                )
            )
        row = result.first()
        if row is None:
            return None
        token_blob = row[0]
        if isinstance(token_blob, (bytes, bytearray, memoryview)):
            token_str = bytes(token_blob).decode("ascii")
        else:
            token_str = str(token_blob)
        page_access_token = encryption.decrypt(token_str)
    except Exception:
        logging.debug("[Meta] page_access_token 取得/復号失敗", exc_info=True)
        return None

    try:
        return await meta_graph.get_user_name(sender_id, page_access_token)
    except Exception:
        logging.debug("[Meta] Graph API user name 取得失敗", exc_info=True)
        return None


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
    page_id: Optional[str] = None,
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
        text("SELECT id, customer_name FROM leads WHERE source = :source LIMIT 1"),
        {"source": source_key},
    )
    row = result.mappings().first()
    lead_id = row["id"] if row else None
    existing_name = row["customer_name"] if row else None

    # F15-S6 follow-up: 既存 lead でデフォルト名のままの場合も Graph API で再解決する。
    # 新規 lead のみ解決していた旧実装の漏れを修正（ADR-016）。
    if lead_id is not None and existing_name in ("Messenger User", "Instagram User"):
        resolved_name = await _resolve_lead_name_via_graph(
            db, sender_id, page_id=page_id,
        )
        if resolved_name:
            await db.execute(
                text("UPDATE leads SET customer_name = :name WHERE id = :id"),
                {"name": resolved_name, "id": lead_id},
            )
            await db.commit()
            await reset_tenant_context(db, tenant_id)

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

            # Phase 1-E F15-S6 + F15-FU1: 新規 lead の customer_name を Graph API 由来の
            # 実名で更新。複数 Page 接続テナントで token を取り違えないよう page_id を渡す。
            # 失敗時はデフォルト名（"Messenger User" / "Instagram User"）のまま続行。
            resolved_name = await _resolve_lead_name_via_graph(
                db, sender_id, page_id=page_id,
            )
            if resolved_name:
                await db.execute(
                    text("UPDATE leads SET customer_name = :name WHERE id = :id"),
                    {"name": resolved_name, "id": lead_id},
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
                message_id, page_id
            )
            VALUES (
                :tenant_id, :lead_id, :platform,
                :sender_id, :message_text, 'inbound', :raw_payload,
                :message_id, :page_id
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
            "page_id": page_id,
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

                # Phase 1-E F14-S5 + F14-FU1: meta_messages.page_id を埋める
                # Messenger: entry.id = Page ID をそのまま使う
                # Instagram: entry.id = IG Business Account ID なので tenant_meta_config
                #            経由で親 Page ID を逆引き（search_path 切替前に実施）
                if platform == "messenger":
                    page_id_for_message: Optional[str] = entry_id
                else:
                    page_id_for_message = await _resolve_page_id_for_ig(db, entry_id)

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
                        page_id=page_id_for_message,
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
