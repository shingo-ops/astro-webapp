from __future__ import annotations

"""
spec.md v1.1 F4 / Sprint 4: 中央 admin への Discord webhook 通知サービス。

LLM 予算超過 (`tenant_llm_budgets.hard_stop` 発火) 時に Jarvis 運用 admin
(しんごさん / ひとしさん) へ Discord webhook 経由で通知する薄い service。

設計:
  - **webhook URL は env (`ADMIN_NOTIFICATION_DISCORD_WEBHOOK`)** (Generator 判断 2)
    既存の `DISCORD_WEBHOOK_PLAN_REVIEW` / `DISCORD_WEBHOOK_PR` は claude-pipeline
    用で、admin 通知とは性質が違う。専用 env を追加し別 channel に分離する設計。
  - **未設定なら no-op + warning ログ**: AC4.5 と同じ思想で、通知 chain が壊れても
    LLM 解析自体は止めない。
  - **httpx で POST**: 既存サービスで httpx 使用しており、追加依存なし。
  - **冪等性**: 同一 tenant に対し短時間に何度も発火しないよう、
    呼び出し側 (parse_inventory_message) が「初めて hard_stop 状態になった呼び出し
    1 回だけ」呼ぶ責務を持つ。本サービス内では rate limit を入れない。

参照:
  - spec F4 AC4.3
  - memory: project_jarvis_llm_gemini.md (Gemini 2.5 Flash 確定)
"""

import logging
import os
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Discord webhook の payload size 制限 (Discord 仕様: 6000 chars / embed total)
_MAX_MESSAGE_CHARS = 1800


def _get_webhook_url() -> str | None:
    url = os.getenv("ADMIN_NOTIFICATION_DISCORD_WEBHOOK", "").strip()
    return url or None


async def _post_discord_webhook(url: str, content: str) -> bool:
    """Discord webhook へ POST。成否を返すだけ、例外は握り潰す。"""
    payload: dict[str, Any] = {
        "content": content[:_MAX_MESSAGE_CHARS],
        # Discord 側で username override したい場合に使う
        "username": "Jarvis CRM 在庫管理 LLM 予算アラート",
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
        if resp.status_code >= 400:
            logger.warning(
                "[discord_notifier] webhook returned %s: %s",
                resp.status_code,
                resp.text[:200],
            )
            return False
        return True
    except Exception as exc:  # noqa: BLE001 - 通知失敗で本処理を止めない
        logger.warning("[discord_notifier] webhook POST failed: %s", exc)
        return False


# Sprint 5 (F5) で追加: 連投抑止の de-bounce ウィンドウ (1 時間)。
# migration 066 で追加した `last_hard_stop_notified_at` を参照。
_HARD_STOP_NOTIFY_DEBOUNCE_SECONDS = 60 * 60  # 1h


async def notify_budget_exhausted(
    db: AsyncSession,
    tenant_id: int,
    *,
    monthly_budget_usd: Decimal,
    current_month_usd: Decimal,
) -> bool:
    """LLM 月次予算超過時に admin へ通知。

    Returns:
        True : webhook が正常に POST された
        False: webhook 未設定 / 1h de-bounce で skip / POST 失敗 (log のみ)

    AC4.3: budget 超過後の 1 件目で 1 回通知。
    Sprint 5 申し送り対応: 1h 以内の再通知は skip (PR #517 Reviewer 指摘)。
        migration 066 で `last_hard_stop_notified_at` 列を追加し、
        UPDATE ... WHERE last_hard_stop_notified_at IS NULL
                       OR last_hard_stop_notified_at < NOW() - INTERVAL '1 hour'
        RETURNING tenant_id で「row が返ったら今回が通知タイミング」と判定。
        並列実行されても DB レベルで 1 行だけ RETURNING されるため race-free。
    """
    url = _get_webhook_url()
    if not url:
        logger.info(
            "[discord_notifier] ADMIN_NOTIFICATION_DISCORD_WEBHOOK 未設定、"
            "tenant_id=%s の予算超過通知を skip",
            tenant_id,
        )
        return False

    # 1h de-bounce: 行を UPDATE して RETURNING で「今回通知すべきか」を判定
    debounce_ok = await _try_debounce_acquire(db, tenant_id)
    if not debounce_ok:
        logger.info(
            "[discord_notifier] tenant_id=%s の予算超過通知は de-bounce 内 (1h) で skip",
            tenant_id,
        )
        return False

    tenant_code = await _resolve_tenant_code(db, tenant_id)
    msg = (
        f":warning: **LLM 月次予算超過** :warning:\n"
        f"- テナント: `{tenant_code}` (tenant_id={tenant_id})\n"
        f"- 月次予算: ${monthly_budget_usd:.2f}\n"
        f"- 現在使用量: ${current_month_usd:.4f}\n"
        f"- 状態: hard_stop=true により以降の LLM 呼び出しは "
        f"`parse_status=budget_exhausted` で抑止されます。\n"
        f"- 必要なら `/super-admin/masters` → LLM 設定で予算を引き上げてください。"
    )
    ok = await _post_discord_webhook(url, msg)
    if ok:
        logger.info(
            "[discord_notifier] budget exhausted notification sent for tenant_id=%s",
            tenant_id,
        )
    else:
        # POST 失敗時は de-bounce ロックを解除（次回再試行可能にする）
        await _release_debounce(db, tenant_id)
    return ok


async def _try_debounce_acquire(db: AsyncSession, tenant_id: int) -> bool:
    """1h de-bounce の lock 取得を atomic に試みる。

    成功すると `last_hard_stop_notified_at = NOW()` で UPDATE され True を返す。
    1h 以内に既に通知済の場合は WHERE 条件で更新されず False を返す。
    """
    try:
        result = await db.execute(
            text(
                """
                UPDATE public.tenant_llm_budgets
                   SET last_hard_stop_notified_at = NOW()
                 WHERE tenant_id = :tid
                   AND (last_hard_stop_notified_at IS NULL
                        OR last_hard_stop_notified_at <
                           NOW() - make_interval(secs => :secs))
                RETURNING tenant_id
                """
            ),
            {"tid": tenant_id, "secs": _HARD_STOP_NOTIFY_DEBOUNCE_SECONDS},
        )
        row = result.first()
        await db.commit()
        return row is not None
    except Exception as exc:  # noqa: BLE001
        # 列未マイグレーション (migration 066 適用前) は素通しにして従来動作維持
        logger.warning(
            "[discord_notifier] de-bounce lookup failed, fallthrough: %s", exc
        )
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass
        return True


async def _release_debounce(db: AsyncSession, tenant_id: int) -> None:
    """POST 失敗時に de-bounce ロックを解除（次回再試行可能にする）。"""
    try:
        await db.execute(
            text(
                """
                UPDATE public.tenant_llm_budgets
                   SET last_hard_stop_notified_at = NULL
                 WHERE tenant_id = :tid
                """
            ),
            {"tid": tenant_id},
        )
        await db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[discord_notifier] de-bounce release failed: %s", exc)
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass


async def _resolve_tenant_code(db: AsyncSession, tenant_id: int) -> str:
    """tenant_id から tenant_code を取得（log 用）。"""
    try:
        result = await db.execute(
            text("SELECT tenant_code FROM public.tenants WHERE id = :id"),
            {"id": tenant_id},
        )
        row = result.first()
        if row:
            return str(row[0])
    except Exception as exc:  # noqa: BLE001
        logger.debug("[discord_notifier] tenant_code lookup failed: %s", exc)
    return f"tenant_{tenant_id:03d}"


__all__ = ["notify_budget_exhausted"]
