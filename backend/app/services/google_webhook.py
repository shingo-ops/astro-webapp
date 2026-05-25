from __future__ import annotations

"""
Google Calendar Webhook（Push Notification）管理サービス。

担当範囲:
  - Webhook チャンネル登録（google.calendar.events.watch()）
  - Webhook チャンネルの有効期限管理と再登録
  - Webhook 受信時のイベント差分取得と DB 反映

Google Calendar Push Notification の制約:
  - 最大有効期限: ~7日（最大 604800000ms ≈ 7 * 24 * 60 * 60 * 1000）
  - 通知は 100% 保証されない（ドロップあり）→ Polling フォールバックと併用推奨
  - channel_id は UUID（毎回新規生成）
  - チャンネル登録後、最初に 'sync' 状態の通知が届く（無視する）
  - HTTPS 公開エンドポイントが必要（本番: https://api.salesanchor.jp）

環境変数:
  API_BASE_URL - Webhook 受信エンドポイントのベース URL
                 デフォルト: https://api.salesanchor.jp
"""

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_WEBHOOK_PATH = "/api/v1/google-calendar/webhook"
# Google Calendar Webhook の最大有効期限（7日 = 604800000ms）
_MAX_TTL_MS = 604800000
# 更新トリガー: 残り 2 日以下になったら再登録
_RENEW_THRESHOLD_HOURS = 48


def _get_webhook_address() -> str:
    base = os.getenv("API_BASE_URL", "https://api.salesanchor.jp").rstrip("/")
    return f"{base}{_WEBHOOK_PATH}"


# ---------------------------------------------------------------------------
# Webhook チャンネル登録
# ---------------------------------------------------------------------------


async def register_webhook(db: AsyncSession, tenant_id: int) -> Optional[dict]:
    """Google Calendar の Push Notification チャンネルを登録する。

    登録成功時は google_webhook_subscriptions に channel 情報を保存する。
    既存のチャンネルがある場合は stop → 新規登録 の順で更新する。

    Returns:
        成功時: {"channel_id": str, "expiration": str}
        Google 未接続時: None
    """
    from app.services import google_calendar as cal_svc

    try:
        service = await cal_svc._get_service(db, tenant_id)
    except RuntimeError as e:
        logger.info("Google Calendar 未接続のため Webhook 登録スキップ (tenant=%s): %s", tenant_id, e)
        return None

    channel_id = str(uuid.uuid4())
    webhook_address = _get_webhook_address()

    try:
        response = service.events().watch(
            calendarId="primary",
            body={
                "id": channel_id,
                "type": "web_hook",
                "address": webhook_address,
                "expiration": str(int(datetime.now(timezone.utc).timestamp() * 1000) + _MAX_TTL_MS),
            },
        ).execute()
    except Exception as e:
        logger.error("Webhook チャンネル登録に失敗 (tenant=%s): %s", tenant_id, e)
        return None

    expiration_ms = int(response.get("expiration", 0))
    expiration_dt = datetime.fromtimestamp(expiration_ms / 1000, tz=timezone.utc)
    resource_id = response.get("resourceId", "")

    await db.execute(
        text(
            "INSERT INTO google_webhook_subscriptions"
            " (tenant_id, channel_id, resource_id, calendar_id, expiration)"
            " VALUES (:tid, :cid, :rid, 'primary', :exp)"
            " ON CONFLICT (tenant_id) DO UPDATE SET"
            "   channel_id  = EXCLUDED.channel_id,"
            "   resource_id = EXCLUDED.resource_id,"
            "   expiration  = EXCLUDED.expiration,"
            "   created_at  = NOW()"
        ),
        {
            "tid": tenant_id,
            "cid": channel_id,
            "rid": resource_id,
            "exp": expiration_dt,
        },
    )
    await db.commit()
    logger.info(
        "Webhook チャンネル登録完了 (tenant=%s, channel=%s, expiry=%s)",
        tenant_id, channel_id, expiration_dt,
    )
    return {"channel_id": channel_id, "expiration": expiration_dt.isoformat()}


# ---------------------------------------------------------------------------
# Webhook チャンネル停止
# ---------------------------------------------------------------------------


async def stop_webhook(db: AsyncSession, tenant_id: int) -> None:
    """Google Calendar の Push Notification チャンネルを停止する。"""
    from app.services import google_calendar as cal_svc

    row = await db.execute(
        text(
            "SELECT channel_id, resource_id FROM google_webhook_subscriptions"
            " WHERE tenant_id = :tid"
        ),
        {"tid": tenant_id},
    )
    record = row.first()
    if not record:
        return

    channel_id, resource_id = record[0], record[1]
    try:
        service = await cal_svc._get_service(db, tenant_id)
        service.channels().stop(
            body={"id": channel_id, "resourceId": resource_id}
        ).execute()
    except Exception as e:
        logger.warning("Webhook チャンネル停止に失敗 (tenant=%s): %s", tenant_id, e)

    await db.execute(
        text("DELETE FROM google_webhook_subscriptions WHERE tenant_id = :tid"),
        {"tid": tenant_id},
    )
    await db.commit()


# ---------------------------------------------------------------------------
# テナント特定（Webhook 受信時）
# ---------------------------------------------------------------------------


async def get_tenant_by_channel(
    db: AsyncSession, channel_id: str
) -> Optional[tuple[int, str]]:
    """channel_id からテナント情報を返す。

    Returns:
        (tenant_id, schema_name) のタプル、見つからない場合は None
    """
    row = await db.execute(
        text(
            "SELECT tenant_id FROM google_webhook_subscriptions"
            " WHERE channel_id = :cid"
        ),
        {"cid": channel_id},
    )
    record = row.first()
    if not record:
        return None
    tenant_id = record[0]
    schema_name = f"tenant_{int(tenant_id):03d}"
    return tenant_id, schema_name


# ---------------------------------------------------------------------------
# Webhook 受信処理
# ---------------------------------------------------------------------------


async def handle_webhook_notification(
    db: AsyncSession,
    channel_id: str,
    resource_state: str,
) -> None:
    """Webhook 通知を受信し、差分イベントを DB に反映する。

    resource_state:
      - 'sync': 初期確認通知（無視する）
      - 'exists': イベントが追加/更新された
      - 'not_exists': イベントが削除された（個別の削除イベントで処理するため同じく exists で処理）
    """
    if resource_state == "sync":
        logger.debug("Webhook 初期確認通知を受信（無視）: channel=%s", channel_id)
        return

    tenant_info = await get_tenant_by_channel(db, channel_id)
    if not tenant_info:
        logger.warning("不明な channel_id: %s", channel_id)
        return

    tenant_id, schema_name = tenant_info

    # テナントスキーマに切り替え
    await db.execute(text(f"SET search_path = {schema_name}, public"))

    from app.services import google_calendar as cal_svc
    from app.services.calendar_service import upsert_from_google

    try:
        service = await cal_svc._get_service(db, tenant_id)
    except RuntimeError as e:
        logger.error("Google Calendar サービス取得失敗 (tenant=%s): %s", tenant_id, e)
        return

    # 直近30分の変更を取得（差分同期）
    from datetime import timedelta

    updated_min = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    try:
        events_result = service.events().list(
            calendarId="primary",
            updatedMin=updated_min,
            singleEvents=True,
            showDeleted=True,
        ).execute()
    except Exception as e:
        logger.error("Google Calendar イベント取得失敗 (tenant=%s): %s", tenant_id, e)
        return

    events = events_result.get("items", [])
    for event in events:
        try:
            await upsert_from_google(db, tenant_id, event)
        except Exception as e:
            logger.error(
                "イベント upsert 失敗 (tenant=%s, event_id=%s): %s",
                tenant_id, event.get("id"), e,
            )

    logger.info(
        "Webhook 処理完了 (tenant=%s, channel=%s, %d件)",
        tenant_id, channel_id, len(events),
    )


# ---------------------------------------------------------------------------
# 有効期限切れチャンネルの自動更新（定期実行用）
# ---------------------------------------------------------------------------


async def renew_expiring_webhooks(db: AsyncSession) -> int:
    """有効期限が 2 日以内のチャンネルを自動更新する。

    Returns:
        更新したチャンネル数
    """
    from datetime import timedelta

    threshold = datetime.now(timezone.utc) + timedelta(hours=_RENEW_THRESHOLD_HOURS)
    row = await db.execute(
        text(
            "SELECT tenant_id FROM google_webhook_subscriptions WHERE expiration < :threshold"
        ),
        {"threshold": threshold},
    )
    tenant_ids = [r[0] for r in row.fetchall()]

    renewed = 0
    for tenant_id in tenant_ids:
        result = await register_webhook(db, tenant_id)
        if result:
            renewed += 1
        else:
            logger.warning("Webhook 更新失敗 (tenant=%s)", tenant_id)

    return renewed
