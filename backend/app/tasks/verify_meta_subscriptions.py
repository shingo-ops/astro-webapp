"""
Meta 接続レコードの整合性検証 Cron（ADR-024 / Phase 1-D 構造的不整合修正）。

たとえ話:
  「定期券の磁気が消えていないかを毎朝改札で確認する」係。
  - 暗号化トークンが現在の鍵で復号できるか（鍵不一致の早期検知）
  - Meta 側の subscribed_apps に Sales Anchor が本当に登録されているか
  （DB 上は接続済みでも Meta 側で外れている "subscription drift" を検知）
  を毎日 04:30 JST にチェックして audit_logs に記録する。

なぜ必要か（ADR-024 §Why）:
  - tenant_meta_config に「接続済み」レコードがあるが、Meta 側で
    subscribed_apps から外れている／鍵不一致でトークン復号できない、という
    不整合が発覚した。これらは webhook 受信が静かに止まる原因になり、
    Sentry も入っていない現状では発見が遅れる。
  - リフレッシュ Cron（refresh_meta_tokens.py）は「期限が近いもの」しか
    見ないため、接続直後〜中期で起きる drift を検知できない。

実行タイミング:
  - 毎日 04:30 JST（refresh-meta-page-tokens の 03:00 と archive-old-audit-logs
    の 04:00 を踏まないようにずらす）

検知される問題と audit action:
  - `meta_subscription_decrypt_failed`: 暗号化トークンが現在の鍵で復号不能
  - `meta_subscription_drift_detected`: Meta 側 subscribed_apps に自 App が無い
  - `meta_subscription_check_error`: Meta API 呼び出し自体が失敗（transport 等）
  - `meta_subscription_verified`: 正常確認（情報レベル、運用 dashboard 用）

設計判断:
  - is_active=true のみ対象（disconnect 済は無視）
  - 既存の audit_logs スキーマに新 action を追加するだけ。スキーマ変更なし
  - Meta API 呼び出しは順次（並列なし）で rate limit に優しく
  - 失敗しても is_active を倒さない（refresh_meta_tokens の 3 連敗判定と
    競合しないように、本タスクは検知＝記録のみに徹する）

参考:
  - ADR-024 §受け入れ条件 5（不整合の早期検知）
  - backend/app/tasks/refresh_meta_tokens.py（同期 Celery + per-tenant schema パターン）
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
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

DATABASE_URL = os.getenv("DATABASE_URL", "").replace(
    "postgresql+asyncpg://", "postgresql://"
)

# === audit_log アクション名 ===
ACTION_DECRYPT_FAILED = "meta_subscription_decrypt_failed"
ACTION_DRIFT_DETECTED = "meta_subscription_drift_detected"
ACTION_CHECK_ERROR = "meta_subscription_check_error"
ACTION_VERIFIED = "meta_subscription_verified"

# === Beat schedule の定数（celery_app.py から参照される）===
BEAT_SCHEDULE_NAME = "verify-meta-subscriptions"
# 毎日 04:30 JST（refresh-meta-page-tokens=03:00, archive-old-audit-logs=04:00 とずらす）
BEAT_SCHEDULE_CRON = crontab(hour=4, minute=30)


def _get_sync_engine() -> Engine:
    """同期 DB エンジン。"""
    return create_engine(DATABASE_URL, echo=False)


def _select_tenant_ids(session: Session) -> list[int]:
    """アクティブテナントの id を取得。"""
    result = session.execute(
        text("SELECT id FROM tenants WHERE is_active = true")
    )
    return [int(row[0]) for row in result]


def _select_active_configs(session: Session, schema_name: str) -> list[dict[str, Any]]:
    """is_active=true の tenant_meta_config を全件取得する。"""
    sql = text(f"""
        SELECT id, tenant_id, page_id, page_name,
               page_access_token_encrypted, instagram_business_account_id
        FROM {schema_name}.tenant_meta_config
        WHERE is_active = TRUE
    """)
    rows = session.execute(sql).mappings().all()
    return [dict(row) for row in rows]


def _record_audit(
    session: Session,
    schema_name: str,
    *,
    tenant_id: int,
    record_id: int,
    action: str,
    new_data: dict[str, Any] | None = None,
) -> None:
    """tenant_NNN.audit_logs に記録（同期版、refresh_meta_tokens.py と同パターン）。"""
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
            "user_id": 0,
            "action": action,
            "table_name": "tenant_meta_config",
            "record_id": record_id,
            "new_data": new_json,
        },
    )


def _decrypt_token(encrypted_raw: Any) -> str:
    """BYTEA / memoryview / bytes / str を吸収して復号する。

    Raises:
        encryption.EncryptionError: 鍵不一致 / 改ざん
        encryption.EncryptionConfigurationError: 鍵未設定
        TypeError: 想定外型
    """
    if isinstance(encrypted_raw, memoryview):
        encrypted_str = bytes(encrypted_raw).decode("ascii")
    elif isinstance(encrypted_raw, (bytes, bytearray)):
        encrypted_str = bytes(encrypted_raw).decode("ascii")
    elif isinstance(encrypted_raw, str):
        encrypted_str = encrypted_raw
    else:
        raise TypeError(
            f"encrypted_token has unexpected type: {type(encrypted_raw).__name__}"
        )
    return encryption.decrypt(encrypted_str)


def _verify_one_row(
    session: Session,
    schema_name: str,
    row: dict[str, Any],
    *,
    self_app_id: str,
) -> dict[str, Any]:
    """1 行分の整合性確認。戻り値は集計用サマリ。

    戻り値 status:
      - "verified":       Meta 側 subscribed_apps に自 App あり
      - "drift":          Meta 側 subscribed_apps に自 App なし（drift 検知）
      - "decrypt_failed": トークン復号不能（鍵不一致）
      - "check_error":    Meta API 呼び出し失敗（transport / timeout 等）
    """
    record_id = int(row["id"])
    tenant_id = int(row["tenant_id"])
    page_id = row["page_id"]

    # --- 1. トークン復号 ---
    try:
        plaintext_token = _decrypt_token(row["page_access_token_encrypted"])
    except (encryption.EncryptionError, encryption.EncryptionConfigurationError) as e:
        _record_audit(
            session, schema_name,
            tenant_id=tenant_id, record_id=record_id, action=ACTION_DECRYPT_FAILED,
            new_data={"page_id": page_id, "reason": "decrypt_failed",
                      "error": type(e).__name__},
        )
        session.commit()
        return {"status": "decrypt_failed", "page_id": page_id}
    except TypeError as e:
        _record_audit(
            session, schema_name,
            tenant_id=tenant_id, record_id=record_id, action=ACTION_DECRYPT_FAILED,
            new_data={"page_id": page_id, "reason": "encrypted_token_unexpected_type",
                      "detail": str(e)[:200]},
        )
        session.commit()
        return {"status": "decrypt_failed", "page_id": page_id}

    # --- 2. Meta 側 subscribed_apps 取得 ---
    try:
        apps = asyncio.run(
            meta_graph.get_page_subscribed_apps(page_id, plaintext_token)
        )
    except MetaGraphAPIError as e:
        _record_audit(
            session, schema_name,
            tenant_id=tenant_id, record_id=record_id, action=ACTION_CHECK_ERROR,
            new_data={"page_id": page_id, "reason": "meta_api_error",
                      "meta_error": e.to_audit_dict()},
        )
        session.commit()
        return {"status": "check_error", "page_id": page_id, "reason": "meta_api_error"}
    except (MetaGraphTimeoutError, MetaGraphTransportError, MetaGraphError) as e:
        _record_audit(
            session, schema_name,
            tenant_id=tenant_id, record_id=record_id, action=ACTION_CHECK_ERROR,
            new_data={"page_id": page_id, "reason": "meta_transport_error",
                      "error": type(e).__name__, "detail": str(e)[:300]},
        )
        session.commit()
        return {"status": "check_error", "page_id": page_id, "reason": "meta_transport_error"}

    # --- 3. drift 判定 ---
    app_ids = [str(a.get("id")) for a in apps if a.get("id") is not None]
    if self_app_id and self_app_id in app_ids:
        _record_audit(
            session, schema_name,
            tenant_id=tenant_id, record_id=record_id, action=ACTION_VERIFIED,
            new_data={"page_id": page_id, "subscribed_app_ids": app_ids},
        )
        session.commit()
        return {"status": "verified", "page_id": page_id}

    # drift detected
    _record_audit(
        session, schema_name,
        tenant_id=tenant_id, record_id=record_id, action=ACTION_DRIFT_DETECTED,
        new_data={"page_id": page_id, "subscribed_app_ids": app_ids,
                  "expected_app_id": self_app_id or None},
    )
    session.commit()
    return {"status": "drift", "page_id": page_id}


def _process_tenant(session: Session, tenant_id: int, *, self_app_id: str) -> dict[str, Any]:
    """1 テナント分の検証処理。"""
    schema_name = f"tenant_{tenant_id:03d}"
    session.execute(text(f"SET search_path = {schema_name}, public"))
    session.execute(text(f"SET app.tenant_id = '{tenant_id}'"))

    rows = _select_active_configs(session, schema_name)
    summary = {
        "tenant_id": tenant_id,
        "scanned": len(rows),
        "verified": 0,
        "drift": 0,
        "decrypt_failed": 0,
        "check_error": 0,
        "rows": [],
    }
    for row in rows:
        try:
            r = _verify_one_row(session, schema_name, row, self_app_id=self_app_id)
        except Exception as e:  # noqa: BLE001 - safety net、バッチを止めない
            logger.exception(
                "tenant=%s tenant_meta_config.id=%s で予期しないエラー",
                tenant_id, row.get("id"),
            )
            r = {"status": "check_error", "page_id": row.get("page_id"),
                 "reason": "unexpected", "error": str(e)[:300]}
            try:
                session.rollback()
            except Exception:  # noqa: BLE001
                pass
        if r["status"] == "verified":
            summary["verified"] += 1
        elif r["status"] == "drift":
            summary["drift"] += 1
        elif r["status"] == "decrypt_failed":
            summary["decrypt_failed"] += 1
        else:
            summary["check_error"] += 1
        summary["rows"].append(r)
    return summary


@shared_task(name="app.tasks.verify_meta_subscriptions.verify_all_meta_subscriptions")
def verify_all_meta_subscriptions() -> dict[str, Any]:
    """全テナントの Meta 接続レコードを順に検証する（ADR-024 AC-5）。

    Celery Beat により毎日 04:30 JST に実行。

    Returns:
        集計サマリ:
          {
            "tenants_processed": N,
            "rows_scanned": M,
            "verified": V,
            "drift": D,
            "decrypt_failed": F,
            "check_error": E,
            "by_tenant": [<per-tenant summary>, ...],
          }
    """
    self_app_id = os.getenv("META_APP_ID", "")
    if not self_app_id:
        logger.warning(
            "META_APP_ID 未設定のため subscription drift 判定は self_app_subscribed=None で記録のみ"
        )

    engine = _get_sync_engine()
    Session_ = sessionmaker(engine)

    with Session_() as session:
        tenant_ids = _select_tenant_ids(session)

    overall = {
        "tenants_processed": 0,
        "rows_scanned": 0,
        "verified": 0,
        "drift": 0,
        "decrypt_failed": 0,
        "check_error": 0,
        "by_tenant": [],
    }
    for tenant_id in tenant_ids:
        try:
            with Session_() as session:
                summary = _process_tenant(session, tenant_id, self_app_id=self_app_id)
                overall["tenants_processed"] += 1
                overall["rows_scanned"] += summary["scanned"]
                overall["verified"] += summary["verified"]
                overall["drift"] += summary["drift"]
                overall["decrypt_failed"] += summary["decrypt_failed"]
                overall["check_error"] += summary["check_error"]
                overall["by_tenant"].append(summary)
        except Exception:
            logger.exception("テナント %d の subscription 検証に失敗", tenant_id)

    logger.info(
        "Meta subscription verify 完了: tenants=%d scanned=%d verified=%d drift=%d "
        "decrypt_failed=%d check_error=%d",
        overall["tenants_processed"], overall["rows_scanned"],
        overall["verified"], overall["drift"],
        overall["decrypt_failed"], overall["check_error"],
    )
    return overall


__all__ = [
    "ACTION_DECRYPT_FAILED",
    "ACTION_DRIFT_DETECTED",
    "ACTION_CHECK_ERROR",
    "ACTION_VERIFIED",
    "BEAT_SCHEDULE_NAME",
    "BEAT_SCHEDULE_CRON",
    "verify_all_meta_subscriptions",
]
