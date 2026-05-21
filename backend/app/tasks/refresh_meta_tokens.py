"""
Page Access Token 60 日リフレッシュ Cron（Phase 1-E F1-S2）。

たとえ話:
  「定期券の自動更新」。Meta が発行する Page Access Token は約 60 日で失効するので、
  期限が近づいた／最後に更新されてから 50 日以上経った定期券を毎日深夜 3 時に
  まとめて更新窓口（Meta Graph API）に持っていって延長する役。
  失敗が 3 日連続したら「もうこの定期は使えない」とフラグを立てて
  管理者に再接続を促す。

実行タイミング:
  - Celery Beat により毎日 03:00 JST に実行
  - 1 日 1 回で十分。Meta のトークン延長 grant は何度叩いても 60 日延長されるが、
    無駄な API 呼び出しを避けるため「期限まで 10 日 OR 最後の更新から 50 日経過」
    という閾値で絞る。

設計判断:
  - 全テナントの per-tenant スキーマ（`tenant_NNN.tenant_meta_config`）を順に処理
  - Celery ワーカーは同期。Meta Graph API ヘルパは async なので、各 row 処理ごとに
    `asyncio.run()` で 1 回だけイベントループを立てる（`anyio.run` でも可だが標準で十分）
  - 失敗時は audit_logs に記録するが is_active は変更しない（既存トークンで送信は試みる）
  - 連続 3 日失敗の判定は audit_logs を遡って count する。冪等で副作用なし。
  - 並行処理はしない（テナント数が少ない＆Meta の rate limit 安全側）

連続失敗判定の仕様:
  - 直近 3 日間で同じ tenant_meta_config.id に対して
    `action='meta_token_refresh_failed'` が 3 件以上あり、
    その間に `meta_token_refreshed` の成功記録が無ければ「3 日連続失敗」とみなす。

エラー方針:
  - Meta 側エラー → audit_log + count up + 該当 row はスキップ
  - 復号失敗 → audit_log（暗号鍵不一致の運用ミス）+ スキップ
  - DB 書き込み失敗 → ログ + 次の row へ進む（バッチ全体は止めない）

参考:
  - backend/app/tasks/maintenance.py（Celery 同期 task のパターン）
  - backend/app/tasks/dashboard.py（per-tenant schema iteration）
  - backend/app/services/meta_graph.py（Graph API ラッパ）
  - backend/app/services/encryption.py（Fernet）

変更履歴:
  2026-04-30: Phase 1-E F1-S2 初版（しんごさん依頼）
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from celery import shared_task
from celery.schedules import crontab
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.services import encryption, meta_graph
from app.services.meta_graph import (
    MetaGraphAPIError,
    MetaGraphError,
    MetaGraphTimeoutError,
    MetaGraphTransportError,
)

logger = logging.getLogger(__name__)

# Celery ワーカーは同期接続のため asyncpg を psycopg2 に置換
DATABASE_URL = os.getenv("DATABASE_URL", "").replace(
    "postgresql+asyncpg://", "postgresql://"
)

# === 閾値定数 ===
# 期限まで 10 日を切ったら強制リフレッシュ
EXPIRES_WITHIN_DAYS = 10
# 最後の更新から 50 日以上経っていたら念のため再リフレッシュ
LAST_REFRESH_OLDER_THAN_DAYS = 50
# 連続失敗で is_active=false に倒す閾値（日数 = 件数の上限）
CONSECUTIVE_FAILURE_THRESHOLD = 3
# 連続失敗判定の窓（日数）
CONSECUTIVE_FAILURE_WINDOW_DAYS = 3

# audit_log アクション名
ACTION_REFRESHED = "meta_token_refreshed"
ACTION_REFRESH_FAILED = "meta_token_refresh_failed"
ACTION_DEACTIVATED = "meta_token_auto_deactivated"

# Beat schedule の定数（celery_app.py から参照される）
BEAT_SCHEDULE_NAME = "refresh-meta-page-tokens"
# 毎日 03:00 JST（celery_app.timezone=Asia/Tokyo）
BEAT_SCHEDULE_CRON = crontab(hour=3, minute=0)


def _get_sync_engine() -> Engine:
    """同期 DB エンジン。"""
    return create_engine(DATABASE_URL, echo=False)


def _select_tenant_ids(session: Session) -> list[int]:
    """アクティブテナントの id を取得。"""
    result = session.execute(
        text("SELECT id FROM tenants WHERE is_active = true")
    )
    return [int(row[0]) for row in result]


def _select_refresh_targets(session: Session, schema_name: str) -> list[dict[str, Any]]:
    """対象 tenant スキーマからリフレッシュ対象の tenant_meta_config 行を SELECT する。

    対象条件:
      - is_active = true
      - (page_token_expires_at - NOW()) < EXPIRES_WITHIN_DAYS 日 OR
        (NOW() - last_token_refreshed_at) > LAST_REFRESH_OLDER_THAN_DAYS 日 OR
        page_token_expires_at IS NULL

    page_token_expires_at が NULL の場合は「いつ切れるか不明 → 念のためリフレッシュ」
    last_token_refreshed_at が NULL の場合は connected_at を代替に使う（接続から
    50 日以上経っていればリフレッシュ）。
    """
    sql = text(f"""
        SELECT id, tenant_id, page_id, page_name, page_access_token_encrypted,
               page_token_expires_at, last_token_refreshed_at, connected_at
        FROM {schema_name}.tenant_meta_config
        WHERE is_active = TRUE
          AND (
            page_token_expires_at IS NULL
            OR page_token_expires_at - NOW() < INTERVAL '{EXPIRES_WITHIN_DAYS} days'
            OR COALESCE(last_token_refreshed_at, connected_at)
               < NOW() - INTERVAL '{LAST_REFRESH_OLDER_THAN_DAYS} days'
          )
    """)
    rows = session.execute(sql).mappings().all()
    return [dict(row) for row in rows]


def _count_recent_failures(session: Session, schema_name: str, record_id: int) -> int:
    """直近の連続失敗件数をカウント。

    直近 CONSECUTIVE_FAILURE_WINDOW_DAYS 日以内の audit_logs を見て、
    該当 record_id（tenant_meta_config.id）の `meta_token_refresh_failed` を数える。
    途中に `meta_token_refreshed` が混じったら「リセット」する仕様（カウントを 0 に戻す）。
    """
    sql = text(f"""
        SELECT action
        FROM {schema_name}.audit_logs
        WHERE table_name = 'tenant_meta_config'
          AND record_id = :record_id
          AND action IN (:failed_action, :success_action)
          AND created_at > NOW() - INTERVAL '{CONSECUTIVE_FAILURE_WINDOW_DAYS} days'
        ORDER BY created_at DESC
    """)
    result = session.execute(
        sql,
        {
            "record_id": record_id,
            "failed_action": ACTION_REFRESH_FAILED,
            "success_action": ACTION_REFRESHED,
        },
    )
    count = 0
    for row in result:
        action = row[0]
        if action == ACTION_REFRESHED:
            # 直近で成功があればそれ以前は連続とみなさない
            break
        if action == ACTION_REFRESH_FAILED:
            count += 1
    return count


def _record_audit(
    session: Session,
    schema_name: str,
    *,
    tenant_id: int,
    record_id: int | None,
    action: str,
    new_data: dict[str, Any] | None = None,
) -> None:
    """tenant_NNN.audit_logs に記録（同期版）。

    Cron 実行 user は存在しないので user_id は 0 で固定。
    backend/app/services/audit.py は AsyncSession 専用なので別実装。
    """
    new_json = (
        json.dumps(new_data, ensure_ascii=False, default=str) if new_data else None
    )
    sql = text(f"""
        INSERT INTO {schema_name}.audit_logs
            (tenant_id, user_id, action, table_name, record_id, old_data, new_data)
        VALUES
            (:tenant_id, :user_id, :action, :table_name, :record_id,
             NULL, CAST(:new_data AS jsonb))
    """)
    session.execute(
        sql,
        {
            "tenant_id": tenant_id,
            "user_id": 0,  # cron 実行は user を持たない
            "action": action,
            "table_name": "tenant_meta_config",
            "record_id": record_id,
            "new_data": new_json,
        },
    )


def _update_token(
    session: Session,
    schema_name: str,
    *,
    record_id: int,
    encrypted_token_bytes: bytes,
    new_expires_at: datetime | None,
) -> None:
    """新しい暗号化トークンと有効期限を保存し、last_token_refreshed_at を NOW() に更新。"""
    sql = text(f"""
        UPDATE {schema_name}.tenant_meta_config
        SET page_access_token_encrypted = :token,
            page_token_expires_at = :expires_at,
            last_token_refreshed_at = NOW(),
            updated_at = NOW()
        WHERE id = :id
    """)
    session.execute(
        sql,
        {
            "id": record_id,
            "token": encrypted_token_bytes,
            "expires_at": new_expires_at,
        },
    )


def _deactivate_config(session: Session, schema_name: str, record_id: int) -> None:
    """連続失敗で is_active=false に倒す。"""
    sql = text(f"""
        UPDATE {schema_name}.tenant_meta_config
        SET is_active = FALSE,
            deactivated_at = NOW(),
            updated_at = NOW()
        WHERE id = :id
    """)
    session.execute(sql, {"id": record_id})


def _refresh_one_row(
    session: Session,
    schema_name: str,
    row: dict[str, Any],
) -> dict[str, Any]:
    """1 行分のリフレッシュ処理。戻り値は集計用のサマリ。

    戻り値 status:
      - "refreshed": 正常更新
      - "failed": Meta API or 復号失敗 → audit に記録（is_active 変更なし）
      - "deactivated": 連続 3 日失敗で is_active=false に倒した
      - "skipped": 既に何らかの理由で対象外（呼び出し側で起きないはず）
    """
    record_id = int(row["id"])
    tenant_id = int(row["tenant_id"])
    page_id = row["page_id"]
    encrypted_token_raw = row["page_access_token_encrypted"]

    # encrypted カラムは BYTEA。psycopg2 は bytes/memoryview を返すので str に直す
    if isinstance(encrypted_token_raw, memoryview):
        encrypted_str = bytes(encrypted_token_raw).decode("ascii")
    elif isinstance(encrypted_token_raw, (bytes, bytearray)):
        encrypted_str = bytes(encrypted_token_raw).decode("ascii")
    elif isinstance(encrypted_token_raw, str):
        encrypted_str = encrypted_token_raw
    else:
        # 想定外型: 失敗扱い
        _record_audit(
            session, schema_name,
            tenant_id=tenant_id, record_id=record_id, action=ACTION_REFRESH_FAILED,
            new_data={"page_id": page_id, "reason": "encrypted_token_unexpected_type",
                      "type": type(encrypted_token_raw).__name__},
        )
        session.commit()
        return {"status": "failed", "page_id": page_id, "reason": "encrypted_token_unexpected_type"}

    # 復号
    try:
        plaintext_token = encryption.decrypt(encrypted_str)
    except Exception as e:  # EncryptionError / EncryptionConfigurationError 等
        _record_audit(
            session, schema_name,
            tenant_id=tenant_id, record_id=record_id, action=ACTION_REFRESH_FAILED,
            new_data={"page_id": page_id, "reason": "decrypt_failed",
                      "error": type(e).__name__},
        )
        session.commit()
        return {"status": "failed", "page_id": page_id, "reason": "decrypt_failed"}

    # Meta Graph API 呼び出し（async → sync ブリッジ）
    try:
        result = asyncio.run(
            meta_graph.refresh_page_access_token(plaintext_token)
        )
    except MetaGraphAPIError as e:
        _record_audit(
            session, schema_name,
            tenant_id=tenant_id, record_id=record_id, action=ACTION_REFRESH_FAILED,
            new_data={"page_id": page_id, "reason": "meta_api_error",
                      "meta_error": e.to_audit_dict()},
        )
        # 連続失敗チェック（このコミット前にカウントすると今の失敗が含まれない）
        # → 一旦 commit してから count → 必要なら deactivate を別 commit
        session.commit()
        # この commit 後に直近失敗をカウント。今回の失敗も含まれる。
        failure_count = _count_recent_failures(session, schema_name, record_id)
        if failure_count >= CONSECUTIVE_FAILURE_THRESHOLD:
            _deactivate_config(session, schema_name, record_id)
            _record_audit(
                session, schema_name,
                tenant_id=tenant_id, record_id=record_id, action=ACTION_DEACTIVATED,
                new_data={"page_id": page_id, "consecutive_failure_count": failure_count},
            )
            session.commit()
            return {"status": "deactivated", "page_id": page_id,
                    "consecutive_failure_count": failure_count}
        return {"status": "failed", "page_id": page_id, "reason": "meta_api_error"}
    except (MetaGraphTimeoutError, MetaGraphTransportError, MetaGraphError) as e:
        _record_audit(
            session, schema_name,
            tenant_id=tenant_id, record_id=record_id, action=ACTION_REFRESH_FAILED,
            new_data={"page_id": page_id, "reason": "meta_transport_error",
                      "error": type(e).__name__, "detail": str(e)[:500]},
        )
        session.commit()
        failure_count = _count_recent_failures(session, schema_name, record_id)
        if failure_count >= CONSECUTIVE_FAILURE_THRESHOLD:
            _deactivate_config(session, schema_name, record_id)
            _record_audit(
                session, schema_name,
                tenant_id=tenant_id, record_id=record_id, action=ACTION_DEACTIVATED,
                new_data={"page_id": page_id, "consecutive_failure_count": failure_count},
            )
            session.commit()
            return {"status": "deactivated", "page_id": page_id,
                    "consecutive_failure_count": failure_count}
        return {"status": "failed", "page_id": page_id, "reason": "meta_transport_error"}

    # 成功: 暗号化 → DB 更新
    new_token_plain = result["access_token"]
    expires_in = result.get("expires_in")
    new_expires_at: datetime | None = None
    if isinstance(expires_in, int) and expires_in > 0:
        new_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

    new_encrypted_str = encryption.encrypt(new_token_plain)
    new_encrypted_bytes = new_encrypted_str.encode("ascii")

    _update_token(
        session, schema_name,
        record_id=record_id,
        encrypted_token_bytes=new_encrypted_bytes,
        new_expires_at=new_expires_at,
    )
    _record_audit(
        session, schema_name,
        tenant_id=tenant_id, record_id=record_id, action=ACTION_REFRESHED,
        new_data={"page_id": page_id,
                  "expires_in": expires_in,
                  "new_expires_at": new_expires_at.isoformat() if new_expires_at else None},
    )
    session.commit()
    return {"status": "refreshed", "page_id": page_id, "expires_in": expires_in}


def _process_tenant(
    session: Session,
    tenant_id: int,
) -> dict[str, Any]:
    """1 テナント分のリフレッシュ処理。戻り値は集計サマリ。"""
    schema_name = f"tenant_{tenant_id:03d}"
    # search_path はこの session 内だけに適用
    session.execute(text(f"SET search_path = {schema_name}, public"))
    session.execute(text(f"SET app.tenant_id = '{tenant_id}'"))

    targets = _select_refresh_targets(session, schema_name)
    summary = {
        "tenant_id": tenant_id,
        "scanned": len(targets),
        "refreshed": 0,
        "failed": 0,
        "deactivated": 0,
        "rows": [],
    }
    for row in targets:
        try:
            r = _refresh_one_row(session, schema_name, row)
        except Exception as e:  # noqa: BLE001 - safety net、バッチを止めないため
            logger.exception(
                "tenant=%s tenant_meta_config.id=%s で予期しないエラー",
                tenant_id, row.get("id"),
            )
            r = {"status": "failed", "page_id": row.get("page_id"),
                 "reason": "unexpected", "error": str(e)[:500]}
            try:
                session.rollback()
            except Exception:  # noqa: BLE001
                pass
        if r["status"] == "refreshed":
            summary["refreshed"] += 1
        elif r["status"] == "deactivated":
            summary["deactivated"] += 1
        else:
            summary["failed"] += 1
        summary["rows"].append(r)
    return summary


@shared_task(
    name="app.tasks.refresh_meta_tokens.refresh_all_meta_page_tokens",
    max_retries=3,
)
def refresh_all_meta_page_tokens() -> dict[str, Any]:
    """全テナントの Page Access Token を必要に応じてリフレッシュする。

    Celery Beat により毎日 03:00 JST に実行される。

    Returns:
        集計サマリ:
          {
            "tenants_processed": N,
            "rows_scanned": M,
            "refreshed": X,
            "failed": Y,
            "deactivated": Z,
            "by_tenant": [<per-tenant summary>, ...],
          }
    """
    engine = _get_sync_engine()
    Session_ = sessionmaker(engine)

    with Session_() as session:
        tenant_ids = _select_tenant_ids(session)

    overall = {
        "tenants_processed": 0,
        "rows_scanned": 0,
        "refreshed": 0,
        "failed": 0,
        "deactivated": 0,
        "by_tenant": [],
    }
    for tenant_id in tenant_ids:
        try:
            with Session_() as session:
                summary = _process_tenant(session, tenant_id)
                overall["tenants_processed"] += 1
                overall["rows_scanned"] += summary["scanned"]
                overall["refreshed"] += summary["refreshed"]
                overall["failed"] += summary["failed"]
                overall["deactivated"] += summary["deactivated"]
                overall["by_tenant"].append(summary)
        except Exception:
            logger.exception("テナント %d のトークンリフレッシュに失敗", tenant_id)
            overall["tenants_processed"] += 1
            overall["failed"] += 1
            overall["by_tenant"].append({
                "tenant_id": tenant_id,
                "scanned": 0,
                "refreshed": 0,
                "failed": 1,
                "deactivated": 0,
                "error": "tenant_process_failed",
            })

    logger.info(
        "Meta token refresh 完了: tenants=%d scanned=%d refreshed=%d failed=%d deactivated=%d",
        overall["tenants_processed"], overall["rows_scanned"],
        overall["refreshed"], overall["failed"], overall["deactivated"],
    )
    return overall


__all__ = [
    "EXPIRES_WITHIN_DAYS",
    "LAST_REFRESH_OLDER_THAN_DAYS",
    "CONSECUTIVE_FAILURE_THRESHOLD",
    "CONSECUTIVE_FAILURE_WINDOW_DAYS",
    "ACTION_REFRESHED",
    "ACTION_REFRESH_FAILED",
    "ACTION_DEACTIVATED",
    "BEAT_SCHEDULE_NAME",
    "BEAT_SCHEDULE_CRON",
    "refresh_all_meta_page_tokens",
]
