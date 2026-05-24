"""
受信箱 顧客アバター画像 取得・キャッシュ Cron（Phase 1 Avatar）。

たとえ話:
  「名刺フォルダを定期的に最新版に差し替える係」。
  Meta Messenger / Instagram DM で連絡してきた顧客のプロフィール画像URLを
  Meta Graph API から取得し、Redis の冷蔵庫に23時間だけ保管する。
  毎日深夜2時に全顧客分をまとめて最新化するほか、
  Webhook でメッセージが届いたタイミングでも1件ずつバックグラウンドで更新する。

実行タイミング:
  - Celery Beat により毎日 02:00 JST に refresh_all_avatars が実行
  - Webhook 受信時に fetch_avatar_for_lead.delay() で個別取得

Meta Platform Terms 準拠:
  - プロフィール画像URL は DB に永続保存しない
  - Redis TTL = 82800秒(23h) で自動削除（Meta の24h規制内）

設計判断:
  - Celery ワーカーは同期。Meta Graph API ヘルパは async なので asyncio.run() でブリッジ
    （refresh_meta_tokens.py と同一パターン）
  - page_access_token は Celery 引数に含めず DB から再取得
    （Celery result backend の Redis にトークンが残らない）
  - Redis 書き込みは同期クライアント（dashboard.py と同一パターン）
  - API 失敗時は Redis に書かない（既存キャッシュを維持）
  - eBay / Cardmarket はアバターAPI 未提供のためスキップ

エラー方針:
  - Meta API エラー → ログ + スキップ（Redis には書かない）
  - 復号失敗 → ログ + スキップ
  - DB 接続失敗 → ログ + スキップ
  - バッチ全体は止めない（per-row try/except）
  - MetaGraphRateLimitError → バッチ中断（Rate Limit セーフガード）

参考:
  - backend/app/tasks/refresh_meta_tokens.py（Celery 同期タスクのパターン）
  - backend/app/services/meta_graph.py（Graph API ラッパ）
  - backend/app/services/encryption.py（Fernet 復号）
  - backend/app/cache.py（Redis キャッシュ TTL 定数）

変更履歴:
  2026-05-25: Phase 1 Avatar 初版（しんごさん依頼）
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

import redis as redis_sync
from celery import shared_task
from celery.schedules import crontab
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.cache import AVATAR_TTL_META
from app.services import encryption, meta_graph
from app.services.meta_graph import (
    MetaGraphError,
    MetaGraphRateLimitError,
)

logger = logging.getLogger(__name__)

# Celery ワーカーは同期接続のため asyncpg を psycopg2 に置換
DATABASE_URL = os.getenv("DATABASE_URL", "").replace(
    "postgresql+asyncpg://", "postgresql://"
)
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

# 過去 N 日以内にメッセージのあった sender を対象とする
ACTIVE_SENDER_WINDOW_DAYS = 30

# テナント間スロットリング（Meta API Rate Limit セーフガード）
INTER_TENANT_SLEEP_SECONDS = 0.5

# Beat schedule の定数（celery_app.py から参照される）
BEAT_SCHEDULE_NAME = "refresh-all-avatars"
# 毎日 02:00 JST（celery_app.timezone=Asia/Tokyo）
BEAT_SCHEDULE_CRON = crontab(hour=2, minute=0)


def _get_sync_engine() -> Engine:
    """同期 DB エンジン。"""
    return create_engine(DATABASE_URL, echo=False)


def _get_sync_redis() -> redis_sync.Redis:
    """同期 Redis クライアント。DB0（アプリキャッシュ）に接続。"""
    return redis_sync.from_url(REDIS_URL, decode_responses=True)


def _select_tenant_ids(session: Session) -> list[int]:
    """アクティブテナントの id を取得。"""
    result = session.execute(
        text("SELECT id FROM tenants WHERE is_active = true")
    )
    return [int(row[0]) for row in result]


def _get_page_access_token(
    session: Session, schema_name: str, page_id: str
) -> str | None:
    """tenant_meta_config から page_id に対応する page_access_token を取得・復号する。

    Returns:
        復号済みトークン文字列。取得・復号失敗時は None。
    """
    row = session.execute(
        text(f"""
            SELECT page_access_token_encrypted
            FROM {schema_name}.tenant_meta_config
            WHERE page_id = :page_id
              AND is_active = TRUE
            LIMIT 1
        """),
        {"page_id": page_id},
    ).fetchone()

    if row is None:
        logger.warning("tenant_meta_config: page_id=%s の行が見つからない", page_id)
        return None

    encrypted_raw = row[0]
    if isinstance(encrypted_raw, memoryview):
        encrypted_str = bytes(encrypted_raw).decode("ascii")
    elif isinstance(encrypted_raw, (bytes, bytearray)):
        encrypted_str = bytes(encrypted_raw).decode("ascii")
    elif isinstance(encrypted_raw, str):
        encrypted_str = encrypted_raw
    else:
        logger.warning("page_access_token_encrypted の型が不正: %s", type(encrypted_raw))
        return None

    try:
        return encryption.decrypt(encrypted_str)
    except Exception:
        logger.warning("page_access_token の復号失敗: page_id=%s", page_id)
        return None


def _fetch_and_cache_avatar(
    r: redis_sync.Redis,
    session: Session,
    schema_name: str,
    platform: str,
    sender_id: str,
    page_id: str,
) -> str:
    """1件分のアバター画像URLを取得してRedisにキャッシュする。

    Returns:
        "cached"   - 取得・保存成功
        "skipped"  - アバターAPI未対応プラットフォーム
        "no_token" - page_access_token 取得失敗
        "no_pic"   - APIがprofile_picを返さなかった
        "api_error"- Meta API エラー（rate_limit以外）
    """
    if platform not in ("messenger", "instagram"):
        return "skipped"

    token = _get_page_access_token(session, schema_name, page_id)
    if not token:
        return "no_token"

    try:
        url = asyncio.run(
            meta_graph.get_user_profile_pic(sender_id, token)
        )
    except MetaGraphRateLimitError:
        raise  # 呼び出し元でバッチ中断
    except MetaGraphError as e:
        logger.warning(
            "avatar取得失敗: platform=%s sender_id=%s error=%s",
            platform, sender_id, e,
        )
        return "api_error"
    except Exception as e:
        logger.warning(
            "avatar取得で予期しないエラー: platform=%s sender_id=%s error=%s",
            platform, sender_id, e,
        )
        return "api_error"

    if not url:
        return "no_pic"

    try:
        r.setex(f"avatar:{platform}:{sender_id}", AVATAR_TTL_META, url)
    except Exception:
        logger.warning("Redis書き込み失敗: avatar:%s:%s", platform, sender_id)
        return "api_error"

    return "cached"


@shared_task(
    name="app.tasks.avatar.fetch_avatar_for_lead",
    max_retries=2,
    default_retry_delay=60,
)
def fetch_avatar_for_lead(
    lead_id: int,
    platform: str,
    sender_id: str,
    page_id: str,
    tenant_id: int,
) -> dict[str, Any]:
    """Webhook受信時に1件のアバター画像URLを取得してRedisにキャッシュする。

    Webhook ハンドラから .delay() で非同期投入される。
    失敗しても Webhook 本体に影響しない（呼び出し元で握り潰し）。

    Returns:
        {"status": "cached"|"skipped"|"no_token"|"no_pic"|"api_error", ...}
    """
    if platform not in ("messenger", "instagram"):
        return {"status": "skipped", "reason": "platform_no_api", "platform": platform}

    schema_name = f"tenant_{tenant_id:03d}"
    engine = _get_sync_engine()
    Session_ = sessionmaker(engine)
    r = _get_sync_redis()

    try:
        with Session_() as session:
            session.execute(text(f"SET search_path = {schema_name}, public"))
            status = _fetch_and_cache_avatar(
                r, session, schema_name, platform, sender_id, page_id
            )
    except MetaGraphRateLimitError:
        logger.warning(
            "Meta rate limit: lead_id=%d platform=%s sender_id=%s",
            lead_id, platform, sender_id,
        )
        return {"status": "api_error", "reason": "rate_limit", "lead_id": lead_id}
    except Exception:
        logger.exception("fetch_avatar_for_lead 予期しないエラー: lead_id=%d", lead_id)
        return {"status": "api_error", "reason": "unexpected", "lead_id": lead_id}
    finally:
        r.close()

    logger.debug(
        "avatar fetch: lead_id=%d platform=%s status=%s", lead_id, platform, status
    )
    return {"status": status, "lead_id": lead_id, "platform": platform}


@shared_task(
    name="app.tasks.avatar.refresh_all_avatars",
    max_retries=1,
)
def refresh_all_avatars() -> dict[str, Any]:
    """全テナントの過去30日アクティブ顧客のアバター画像URLを一括更新する。

    Celery Beat により毎日 02:00 JST に実行される。
    MetaGraphRateLimitError が発生したテナントはスキップして次のテナントへ。

    Returns:
        集計サマリ:
          {
            "tenants_processed": N,
            "total_cached": X,
            "total_skipped": Y,
            "total_failed": Z,
            "by_tenant": [...],
          }
    """
    engine = _get_sync_engine()
    Session_ = sessionmaker(engine)
    r = _get_sync_redis()

    with Session_() as session:
        tenant_ids = _select_tenant_ids(session)

    overall: dict[str, Any] = {
        "tenants_processed": 0,
        "total_cached": 0,
        "total_skipped": 0,
        "total_failed": 0,
        "by_tenant": [],
    }

    try:
        for tenant_id in tenant_ids:
            schema_name = f"tenant_{tenant_id:03d}"
            tenant_summary: dict[str, Any] = {
                "tenant_id": tenant_id,
                "cached": 0,
                "skipped": 0,
                "failed": 0,
            }

            try:
                with Session_() as session:
                    session.execute(text(f"SET search_path = {schema_name}, public"))

                    # 過去30日にメッセージのあった (sender_id, platform, page_id) を取得
                    rows = session.execute(
                        text(f"""
                            SELECT DISTINCT sender_id, platform, page_id
                            FROM {schema_name}.meta_messages
                            WHERE direction = 'inbound'
                              AND sender_id IS NOT NULL
                              AND platform IN ('messenger', 'instagram')
                              AND created_at > NOW() - INTERVAL '{ACTIVE_SENDER_WINDOW_DAYS} days'
                        """)
                    ).fetchall()

                    for row in rows:
                        sender_id, platform, page_id = row[0], row[1], row[2]
                        if not sender_id or not platform or not page_id:
                            continue
                        try:
                            status = _fetch_and_cache_avatar(
                                r, session, schema_name, platform, sender_id, page_id
                            )
                        except MetaGraphRateLimitError:
                            logger.warning(
                                "Meta rate limit に到達: tenant_id=%d でバッチ中断", tenant_id
                            )
                            tenant_summary["failed"] += 1
                            break  # このテナントの処理を中断（次テナントへ）
                        except Exception:
                            logger.exception(
                                "avatar取得で予期しないエラー: tenant=%d sender=%s",
                                tenant_id, sender_id,
                            )
                            tenant_summary["failed"] += 1
                            continue

                        if status == "cached":
                            tenant_summary["cached"] += 1
                        elif status == "skipped":
                            tenant_summary["skipped"] += 1
                        else:
                            tenant_summary["failed"] += 1

            except Exception:
                logger.exception("テナント %d のアバター更新に失敗", tenant_id)
                tenant_summary["failed"] += 1

            overall["tenants_processed"] += 1
            overall["total_cached"] += tenant_summary["cached"]
            overall["total_skipped"] += tenant_summary["skipped"]
            overall["total_failed"] += tenant_summary["failed"]
            overall["by_tenant"].append(tenant_summary)

            # テナント間スロットリング（Meta API Rate Limit セーフガード）
            time.sleep(INTER_TENANT_SLEEP_SECONDS)

    finally:
        r.close()

    logger.info(
        "アバター一括更新完了: tenants=%d cached=%d skipped=%d failed=%d",
        overall["tenants_processed"],
        overall["total_cached"],
        overall["total_skipped"],
        overall["total_failed"],
    )
    return overall


__all__ = [
    "BEAT_SCHEDULE_NAME",
    "BEAT_SCHEDULE_CRON",
    "fetch_avatar_for_lead",
    "refresh_all_avatars",
]
