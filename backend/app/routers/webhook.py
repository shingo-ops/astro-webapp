import hashlib
import hmac
import json
import logging
import os

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

router = APIRouter()


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
    # M1修正：個人情報を含まないログ出力
    logging.info(
        "[Meta] Webhookイベント受信: object=%s, entry_count=%d",
        body.get("object", "unknown"),
        len(body.get("entry", [])),
    )
    # TODO: Phase 2でメッセージ処理を実装
