"""
Data Deletion 非同期タスク (B1-B6)

Meta Data Deletion Callback で受領した削除リクエストを非同期に処理する。
仕様書: data_deletion_instructions.docx v1.0 §2.2 + §3.2

実行内容:
1. data_deletion_logs を status='processing' / started_at=NOW() に更新
2. 全テナントスキーマを列挙し、各テナントの meta_messages を sender_id でフィルタして削除
3. 削除実績（件数）を data_items_deleted JSONB に記録
4. status='completed' / completed_at=NOW() に更新
5. 完了通知メールを送信（しんごさん設定の SMTP 経由、未設定なら idle）

注意:
- lead_channels / raw_webhook_events テーブルは Phase 3 で実装予定（仕様書 §4.2）。
  現状は meta_messages のみ削除対象。実装され次第拡張。
"""

from __future__ import annotations

import json
import logging
import os

from celery import shared_task
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "").replace(
    "postgresql+asyncpg://", "postgresql://"
)

# F8: モジュールレベル singleton で再利用（呼び出しごとに作成しない）
_engine = create_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
_SessionLocal = sessionmaker(_engine)


def _get_sync_engine():
    """互換性維持用（既存の他モジュールで参照されている場合に備えて残す）。"""
    return _engine


def _list_tenant_schemas(session) -> list[str]:
    """tenant_NNN スキーマを一覧。アクティブテナントのみ。"""
    result = session.execute(text("SELECT id FROM public.tenants WHERE is_active = true"))
    return [f"tenant_{row[0]:03d}" for row in result]


def _delete_meta_messages_in_tenant(session, schema: str, sender_id: str) -> int:
    """
    指定テナントスキーマの meta_messages から sender_id 一致行を削除。
    テーブルが存在しない場合は 0 を返す（ENOENT 等で落とさない）。
    """
    # テーブル存在確認（meta_messages 未作成のテナントは skip）
    exists = session.execute(
        text(
            "SELECT to_regclass(:qualified) IS NOT NULL"
        ),
        {"qualified": f"{schema}.meta_messages"},
    ).scalar()
    if not exists:
        return 0

    result = session.execute(
        text(f"DELETE FROM {schema}.meta_messages WHERE sender_id = :sender_id"),
        {"sender_id": sender_id},
    )
    return result.rowcount or 0


@shared_task(
    name="app.tasks.data_deletion.process_data_deletion",
    max_retries=3,
    default_retry_delay=60,
    # autoretry_for は意図的に設定しない:
    # process_data_deletion は status='processing' への更新→削除→完了の状態遷移を持ち、
    # 途中失敗後の自動リトライは二重削除のリスクがある（冪等性未保証）。
    # 再試行はオペレーターが手動で行うか、status ガードを追加した後に有効化すること。
)
def process_data_deletion(request_id: str) -> dict:
    """
    data_deletion_logs.request_id に対応する削除リクエストを処理する。

    Returns:
        dict: 処理サマリ {request_id, status, deleted_counts: {tenant: count}, ...}
    """
    Session = _SessionLocal

    # 1) ログを取得 + status='processing' に更新
    with Session() as session:
        row = session.execute(
            text("""
                SELECT identifier_value, channel, user_type
                FROM public.data_deletion_logs
                WHERE request_id = :rid
                LIMIT 1
            """),
            {"rid": request_id},
        ).first()

        if row is None:
            logger.error(f"[data_deletion] request_id={request_id} not found in logs")
            return {"request_id": request_id, "status": "not_found"}

        identifier_value, _, user_type = row[0], row[1], row[2]

        session.execute(
            text("""
                UPDATE public.data_deletion_logs
                SET status='processing', started_at=NOW()
                WHERE request_id = :rid AND status='received'
            """),
            {"rid": request_id},
        )
        session.commit()

    # 2) end_user (Meta) なら全テナントの meta_messages を sender_id で削除
    deleted_counts: dict[str, int] = {}
    total_tenants_searched = 0
    error_message: str | None = None

    if user_type == "end_user" and identifier_value:
        with Session() as session:
            try:
                schemas = _list_tenant_schemas(session)
                total_tenants_searched = len(schemas)
                for schema in schemas:
                    count = _delete_meta_messages_in_tenant(
                        session, schema, identifier_value
                    )
                    if count > 0:
                        deleted_counts[schema] = count
                session.commit()
            except Exception as e:  # noqa: BLE001
                session.rollback()
                error_message = f"deletion error: {type(e).__name__}: {e}"
                logger.error(f"[data_deletion] {error_message}", exc_info=True)
    elif user_type == "user":
        # 利用者削除: メール経由のみ（手動オペレーション）。Celery 経由では到達しない想定。
        logger.info(f"[data_deletion] user_type=user request handled manually: {request_id}")

    # 3) ログを完了状態に更新
    # F4: data_items_deleted のスキーマを SQL コメントと整合させる
    #     {"meta_messages": <total>, "tenants_searched": <total>, "by_tenant": {...}}
    final_status = "failed" if error_message else "completed"
    total_messages = sum(deleted_counts.values())
    with Session() as session:
        session.execute(
            text("""
                UPDATE public.data_deletion_logs
                SET
                    status = :status,
                    completed_at = NOW(),
                    data_items_deleted = :data_items,
                    error_message = :err
                WHERE request_id = :rid
            """),
            {
                "status": final_status,
                "data_items": json.dumps({
                    "meta_messages": total_messages,
                    "tenants_searched": total_tenants_searched,
                    "by_tenant": deleted_counts,
                }),
                "err": error_message,
                "rid": request_id,
            },
        )
        session.commit()

    # 4) 完了通知メール（Celery タスクとして非同期送信）
    # SMTP タイムアウト（最大15秒）をこのタスクに含めないよう、別タスクに分離する。
    try:
        from app.tasks.email_tasks import send_deletion_completion_email_task
        send_deletion_completion_email_task.delay(request_id)
        logger.info("[data_deletion] deletion email task queued for %s", request_id)
    except Exception as e:  # noqa: BLE001
        # キュー失敗は致命ではない（log のみ）
        logger.warning("[data_deletion] failed to queue email task: %s", e)

    return {
        "request_id": request_id,
        "status": final_status,
        "deleted_counts": deleted_counts,
        "error": error_message,
    }
