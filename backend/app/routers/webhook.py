import hashlib
import hmac
import json
import logging
import os

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import reset_tenant_context
from app.database import AsyncSessionLocal
from app.routers.notifications import send_discord_notification

router = APIRouter()

_META_PAGE_ID = os.getenv("META_PAGE_ID", "")


async def _get_tenant_id_by_page(db: AsyncSession, page_id: str) -> int | None:
    """
    page_idからtenant_idを取得する。
    暫定: 環境変数 META_PAGE_ID と一致するページのテナントを返す。
    TODO: Phase 3で設定テーブル（tenant_meta_config）を用意して管理する。
    """
    if not _META_PAGE_ID or page_id != _META_PAGE_ID:
        return None
    result = await db.execute(
        text("SELECT id FROM public.tenants WHERE is_active = true ORDER BY id LIMIT 1")
    )
    row = result.first()
    return row[0] if row else None


# ─────────────────────────────────────────────
# GET /api/v1/webhook/messenger
# Meta Webhook URL検証（認証不要）
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
# Metaメッセージイベント受信（認証不要）
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


async def process_messenger_event(body: dict) -> None:
    """
    Metaから受信したWebhookイベントを処理する
    1. page_idでテナントを特定
    2. メッセージ内容を抽出
    3. 送信者IDでリードを検索
    4. リードが存在しない場合は自動作成
    5. meta_messagesテーブルに記録
    6. Discordに通知
    """
    try:
        if body.get("object") != "page":
            return

        for entry in body.get("entry", []):
            page_id = str(entry.get("id", ""))

            for messaging in entry.get("messaging", []):
                if "message" not in messaging:
                    continue

                sender_id = messaging["sender"]["id"]
                message_text = messaging["message"].get("text", "")
                message_id = messaging["message"].get("mid")

                async with AsyncSessionLocal() as db:
                    # C1: page_idでテナントを特定
                    tenant_id = await _get_tenant_id_by_page(db, page_id)
                    if tenant_id is None:
                        logging.warning(
                            "[Meta] テナント特定失敗: page_id=%s", page_id
                        )
                        continue

                    schema = f"tenant_{tenant_id:03d}"
                    await db.execute(text(f"SET search_path = {schema}, public"))
                    await db.execute(text(f"SET app.tenant_id = '{tenant_id}'"))

                    # 1. 送信者IDでリードを検索
                    source_key = f"messenger:{sender_id}"
                    result = await db.execute(
                        text("SELECT id FROM leads WHERE source = :source LIMIT 1"),
                        {"source": source_key},
                    )
                    row = result.mappings().first()
                    lead_id = row["id"] if row else None

                    # 2. リードが存在しない場合は自動作成
                    #    ON CONFLICT DO NOTHING で並列リクエストの競合状態を防止（C1）
                    if lead_id is None:
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
                                "customer_name": "Messenger User",
                                "source": source_key,
                                "type": "Inbound",
                                "status": "新規",
                            },
                        )
                        new_lead_id = ins.scalar_one_or_none()
                        if new_lead_id is not None:
                            # 新規作成成功：lead_codeを設定
                            lead_id = new_lead_id
                            await db.execute(
                                text("UPDATE leads SET lead_code = :code WHERE id = :id"),
                                {"code": f"LD-{lead_id:05d}", "id": lead_id},
                            )
                            await db.commit()
                            # H1: reset_tenant_context() を使用
                            await reset_tenant_context(db, tenant_id)
                        else:
                            # 競合：並列リクエストが先にINSERTしたため既存リードを取得
                            sel = await db.execute(
                                text("SELECT id FROM leads WHERE source = :source LIMIT 1"),
                                {"source": source_key},
                            )
                            lead_id = sel.scalar_one()

                    # 3. meta_messagesテーブルに記録
                    # H2: raw_payloadから個人情報を除去し最小限の情報のみ保存
                    # TODO: raw_payload は90日後に自動パージする（Phase 3で実装）
                    # ON CONFLICT DO NOTHING でMeta再送による重複挿入を防止（C2）
                    ins = await db.execute(
                        text("""
                            INSERT INTO meta_messages (
                                tenant_id, lead_id, platform,
                                sender_id, message_text, direction, raw_payload,
                                message_id
                            )
                            VALUES (
                                :tenant_id, :lead_id, 'messenger',
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
                            "sender_id": sender_id,
                            "message_text": message_text,
                            "message_id": message_id,
                            "raw_payload": json.dumps({
                                "timestamp": messaging.get("timestamp"),
                                "has_text": bool(
                                    messaging.get("message", {}).get("text")
                                ),
                                "has_attachments": bool(
                                    messaging.get("message", {}).get("attachments")
                                ),
                            }),
                        },
                    )
                    msg_inserted_id = ins.scalar_one_or_none()
                    await db.commit()
                    # H1: reset_tenant_context() を使用
                    await reset_tenant_context(db, tenant_id)

                    if msg_inserted_id is None:
                        logging.info("[Meta] Duplicate message_id skipped: %s", message_id)
                        continue

                    # 4. Discordに通知
                    # C3: メッセージ本文を含めない（個人情報保護）
                    await send_discord_notification(
                        db=db,
                        tenant_id=tenant_id,
                        event_type="meta_message_received",
                        title="📩 新着Messengerメッセージ",
                        message=f"送信者ID: {sender_id[:8]}***\nプラットフォーム: messenger",
                    )

        logging.info(
            "[Meta] 処理完了: object=%s, entry_count=%d",
            body.get("object", "unknown"),
            len(body.get("entry", [])),
        )
    except Exception:
        # M1: logging.exception() でtracebackを含める
        logging.exception("[Meta] Webhookイベント処理エラー")
