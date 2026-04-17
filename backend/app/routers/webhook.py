import logging
import os

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

router = APIRouter()


# ─────────────────────────────────────────────
# GET /webhook/messenger
# Meta Webhook URL検証（Meta Developer Consoleからの呼び出し）
# ─────────────────────────────────────────────
@router.get("/webhook/messenger", response_class=PlainTextResponse)
async def verify_messenger_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    verify_token = os.getenv("META_VERIFY_TOKEN", "jarvis_crm_webhook_2026")
    if hub_mode == "subscribe" and hub_verify_token == verify_token:
        logging.info("[Meta] Webhook検証成功")
        return PlainTextResponse(content=hub_challenge)
    raise HTTPException(status_code=403, detail="Forbidden")


# ─────────────────────────────────────────────
# POST /webhook/messenger
# Metaからのメッセージイベント受信
# ─────────────────────────────────────────────
@router.post("/webhook/messenger")
async def receive_messenger_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
):
    body = await request.json()
    background_tasks.add_task(process_messenger_event, body)
    return {"status": "ok"}


async def process_messenger_event(body: dict):
    # TODO: Phase 2でメッセージ処理を実装
    logging.info(f"[Meta] Webhookイベント受信: {body}")
