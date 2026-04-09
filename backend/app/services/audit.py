from __future__ import annotations

"""
監査ログ（audit_logs）記録サービス。

「誰が・いつ・何を・どう変更したか」をテナントスキーマ内のaudit_logsテーブルに記録する。
データ改ざんの追跡・法的証拠・セキュリティ監査に必須。

使い方:
    from app.services.audit import record_audit_log

    await record_audit_log(
        db=db,
        tenant_id=tenant_id,
        user_id=current_user.id,
        action="create",
        table_name="customers",
        record_id=new_customer.id,
        new_data={"name": "山田太郎", "email": "yamada@example.com"},
    )
"""

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def record_audit_log(
    db: AsyncSession,
    tenant_id: int,
    user_id: int,
    action: str,
    table_name: str,
    record_id: int | None = None,
    old_data: dict[str, Any] | None = None,
    new_data: dict[str, Any] | None = None,
) -> None:
    """
    操作履歴をaudit_logsテーブルに記録する。

    Args:
        db: データベースセッション
        tenant_id: テナントID
        user_id: 操作したユーザーのID
        action: 操作の種類（"create", "update", "delete"）
        table_name: 操作対象のテーブル名（例: "customers"）
        record_id: 操作対象のレコードID
        old_data: 変更前のデータ（updateとdeleteの場合）
        new_data: 変更後のデータ（createとupdateの場合）
    """
    import json

    schema_name = f"tenant_{tenant_id:03d}"

    old_json = json.dumps(old_data, ensure_ascii=False, default=str) if old_data else None
    new_json = json.dumps(new_data, ensure_ascii=False, default=str) if new_data else None

    await db.execute(
        text(f"""
            INSERT INTO {schema_name}.audit_logs
                (tenant_id, user_id, action, table_name, record_id, old_data, new_data)
            VALUES
                (:tenant_id, :user_id, :action, :table_name, :record_id,
                 :old_data::jsonb, :new_data::jsonb)
        """),
        {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "action": action,
            "table_name": table_name,
            "record_id": record_id,
            "old_data": old_json,
            "new_data": new_json,
        },
    )
