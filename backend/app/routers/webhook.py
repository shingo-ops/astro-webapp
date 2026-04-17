import hashlib
import hmac
import json
import logging
import os
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import text

from app.database import AsyncSessionLocal
from app.routers.notifications import send_discord_notification

router = APIRouter()

_TENANT_ID = 1  # Phase 2: 固定。Phase 3でマルチテナント対応予定。


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
    # C1修正：環境変数未設定時は500エラー（デフォルト値なし）
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
    # C2修正：HMAC-SHA256署名検証
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
    1. メッセージ内容を抽出
    2. 送信者IDでリードを検索
    3. リードが存在しない場合は自動作成
    4. meta_messagesテーブルに記録
    5. Discordに通知
    """
    try:
        if body.get("object") != "page":
            return

        for entry in body.get("entry", []):
            for messaging in entry.get("messaging", []):
                if "message" not in messaging:
                    continue

                sender_id = messaging["sender"]["id"]
                message_text = messaging["message"].get("text", "")

                async with AsyncSessionLocal() as db:
                    schema = f"tenant_{_TENANT_ID:03d}"
                    await db.execute(text(f"SET search_path = {schema}, public"))
                    await db.execute(text(f"SET app.tenant_id = '{_TENANT_ID}'"))

                    # 1. 送信者IDでリードを検索
                    source_key = f"messenger:{sender_id}"
                    result = await db.execute(
                        text("SELECT id FROM leads WHERE source = :source LIMIT 1"),
                        {"source": source_key},
                    )
                    row = result.mappings().first()
                    lead_id = row["id"] if row else None

                    # 2. リードが存在しない場合は自動作成
                    if lead_id is None:
                        ins = await db.execute(
                            text("""
                                INSERT INTO leads (
                                    tenant_id, customer_name, source, type, status
                                )
                                VALUES (:tenant_id, :customer_name, :source, :type, :status)
                                RETURNING id
                            """),
                            {
                                "tenant_id": _TENANT_ID,
                                "customer_name": "Messenger User",
                                "source": source_key,
                                "type": "Inbound",
                                "status": "新規",
                            },
                        )
                        lead_id = ins.scalar_one()
                        today = datetime.utcnow().strftime("%Y%m%d")
                        await db.execute(
                            text("UPDATE leads SET lead_code = :code WHERE id = :id"),
                            {"code": f"META-{today}-{lead_id}", "id": lead_id},
                        )
                        await db.commit()
                        await db.execute(text(f"SET search_path = {schema}, public"))
                        await db.execute(text(f"SET app.tenant_id = '{_TENANT_ID}'"))

                    # 3. meta_messagesテーブルに記録
                    await db.execute(
                        text("""
                            INSERT INTO meta_messages (
                                tenant_id, lead_id, platform,
                                sender_id, message_text, direction, raw_payload
                            )
                            VALUES (
                                :tenant_id, :lead_id, 'messenger',
                                :sender_id, :message_text, 'inbound', :raw_payload
                            )
                        """),
                        {
                            "tenant_id": _TENANT_ID,
                            "lead_id": lead_id,
                            "sender_id": sender_id,
                            "message_text": message_text,
                            "raw_payload": json.dumps(messaging),
                        },
                    )
                    await db.commit()
                    await db.execute(text(f"SET search_path = {schema}, public"))
                    await db.execute(text(f"SET app.tenant_id = '{_TENANT_ID}'"))

                    # 4. Discordに通知
                    await send_discord_notification(
                        db=db,
                        tenant_id=_TENANT_ID,
                        event_type="meta_message_received",
                        title="📩 新着Messengerメッセージ",
                        message=f"送信者: {sender_id}\n内容: {message_text}",
                    )

        logging.info(
            "[Meta] 処理完了: object=%s, entry_count=%d",
            body.get("object", "unknown"),
            len(body.get("entry", [])),
        )
    except Exception as e:
        logging.error("[Meta] Webhookイベント処理エラー: %s", str(e))
