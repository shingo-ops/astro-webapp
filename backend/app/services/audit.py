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

副テーブル差分を含めたい場合（companies/contacts など）:
    old_subs = {
        "company_addresses": await snapshot_subtable_rows(db, ...),
        "company_sales_channels": await snapshot_simple_list(db, ...),
    }
    # ... _replace_addresses() などを実行 ...
    new_subs = {
        "company_addresses": await snapshot_subtable_rows(db, ...),
        "company_sales_channels": await snapshot_simple_list(db, ...),
    }
    subtable_diff = build_subtable_diff(old_subs, new_subs)

    await record_audit_log(
        db=db, tenant_id=..., user_id=..., action="update",
        table_name="companies", record_id=...,
        old_data=dict(old_row),
        new_data={**data.model_dump(...), "_subtables": subtable_diff} if subtable_diff else data.model_dump(...),
    )

JSON 構造の例（new_data 内）:
    {
      "name": "新会社名",
      "_subtables": {
        "company_addresses": {
          "added":   [{"address_type": "delivery", "branch_name": "London", ...}],
          "removed": [{"address_type": "billing",  "branch_name": "Tokyo",  ...}]
        },
        "company_sales_channels": {"added": ["EC"], "removed": ["実店舗"]}
      }
    }

added/removed のみ（"modified" は出さない）。1 件の編集は「remove + add」として
記録されるが、簡潔さと曖昧さの少なさを優先した（natural key の選定が副テーブル
ごとに異なるため）。
"""

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


# -----------------------------------------------------------------------------
# 副テーブルスナップショット & diff ユーティリティ（PR #145 F9）
# -----------------------------------------------------------------------------


async def snapshot_subtable_rows(
    db: AsyncSession,
    table_name: str,
    fk_column: str,
    fk_value: int,
    columns: list[str] | None = None,
) -> list[dict[str, Any]]:
    """指定 FK で副テーブルの行をスナップショットする（audit log 用）。

    Args:
        db: AsyncSession
        table_name: 副テーブル名（例: "company_addresses"）。識別子としてそのまま埋め込む
            ため、呼び出し側で必ずコード内リテラルから渡すこと（外部入力 NG）。
        fk_column: 親 FK 列名（例: "company_id"）。同上。
        fk_value: FK の値
        columns: 取り出したい列のリスト。None なら "*"。
            "*" でも構わないが、created_at/updated_at など diff に不要な列が混じると
            ノイズになるため、副テーブルごとに必要列を限定するのを推奨。

    Returns:
        list[dict[str, Any]] — 各行は列名→値の辞書。serialize 済み (default=str 想定)。
    """
    if columns:
        # 列名は識別子。:bind ではなくそのまま埋め込む。呼び出し側のリテラル前提で SQLi リスクなし。
        col_sql = ", ".join(columns)
    else:
        col_sql = "*"
    sql = text(f"SELECT {col_sql} FROM {table_name} WHERE {fk_column} = :fk")
    res = await db.execute(sql, {"fk": fk_value})
    return [dict(row) for row in res.mappings().all()]


async def snapshot_subtable_scalars(
    db: AsyncSession,
    table_name: str,
    fk_column: str,
    fk_value: int,
    value_column: str,
) -> list[Any]:
    """副テーブルから単一値カラムの list を取り出す（例: company_sales_channels.channel）。"""
    sql = text(f"SELECT {value_column} FROM {table_name} WHERE {fk_column} = :fk ORDER BY {value_column}")
    res = await db.execute(sql, {"fk": fk_value})
    return [row[0] for row in res.fetchall()]


def _strip_volatile_keys(row: dict[str, Any]) -> dict[str, Any]:
    """diff 比較で意味のない自動列（id / *_at）を除去した辞書を返す。

    `id` は INSERT 時に新採番されるため「全置換」型の副テーブルでは old/new で必ず
    値が変わってしまい、ノイズになる。created_at/updated_at も同様。
    """
    skip = {"id", "created_at", "updated_at"}
    return {k: v for k, v in row.items() if k not in skip}


def _row_to_hashable(row: dict[str, Any]) -> tuple:
    """dict を順序付き tuple に変換し set 操作可能にする。"""
    return tuple(sorted((k, _to_jsonable(v)) for k, v in row.items()))


def _to_jsonable(value: Any) -> Any:
    """date/datetime/Decimal などを JSON 互換 (str) に丸める。"""
    import datetime as _dt
    from decimal import Decimal as _Decimal

    if isinstance(value, (_dt.datetime, _dt.date)):
        return value.isoformat()
    if isinstance(value, _Decimal):
        return str(value)
    if isinstance(value, list):
        return [_to_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _to_jsonable(v) for k, v in value.items()}
    return value


def diff_rows(
    old_rows: list[dict[str, Any]] | None,
    new_rows: list[dict[str, Any]] | None,
) -> dict[str, list[dict[str, Any]]] | None:
    """副テーブルの行リスト（dict のリスト）から added/removed の diff を作る。

    1 行を「全カラムの組」で識別する単純な集合差分（natural key を仮定しない）。
    `id` / `created_at` / `updated_at` は比較対象から除外する。
    どちらも空 or 同一なら None を返す（出力にキー自体を出さない判断は呼び出し側で）。
    """
    old_norm = [_strip_volatile_keys(r) for r in (old_rows or [])]
    new_norm = [_strip_volatile_keys(r) for r in (new_rows or [])]

    old_keys = [_row_to_hashable(r) for r in old_norm]
    new_keys = [_row_to_hashable(r) for r in new_norm]

    old_set = set(old_keys)
    new_set = set(new_keys)
    if old_set == new_set:
        return None

    # 元順序を保ちたいので key→row の辞書を作って added/removed を抽出
    old_lookup: dict[tuple, dict[str, Any]] = {}
    for k, r in zip(old_keys, old_norm):
        old_lookup.setdefault(k, r)
    new_lookup: dict[tuple, dict[str, Any]] = {}
    for k, r in zip(new_keys, new_norm):
        new_lookup.setdefault(k, r)

    added = [_to_jsonable(new_lookup[k]) for k in new_keys if k not in old_set and k in new_lookup]
    removed = [_to_jsonable(old_lookup[k]) for k in old_keys if k not in new_set and k in old_lookup]

    # 重複行の出現回数差はここでは無視（ほぼ全副テーブルが UNIQUE 制約持ちで重複ナシ）
    out: dict[str, list[dict[str, Any]]] = {}
    if added:
        out["added"] = _dedup_preserve_order(added)
    if removed:
        out["removed"] = _dedup_preserve_order(removed)
    return out or None


def diff_scalars(
    old_values: list[Any] | None,
    new_values: list[Any] | None,
) -> dict[str, list[Any]] | None:
    """単一スカラー列の副テーブル（例: company_sales_channels.channel）用の diff。"""
    old_set = set(old_values or [])
    new_set = set(new_values or [])
    if old_set == new_set:
        return None
    added = sorted(new_set - old_set, key=lambda x: (x is None, str(x)))
    removed = sorted(old_set - new_set, key=lambda x: (x is None, str(x)))
    out: dict[str, list[Any]] = {}
    if added:
        out["added"] = [_to_jsonable(v) for v in added]
    if removed:
        out["removed"] = [_to_jsonable(v) for v in removed]
    return out or None


def diff_single_row(
    old_row: dict[str, Any] | None,
    new_row: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """1:1 副テーブル（例: contact_discord）の before/after を返す。

    どちらも None なら None。同一なら None。差異があれば {"old": {...}|None, "new": {...}|None}。
    `id` / `*_at` は比較対象から除外。
    """
    o = _strip_volatile_keys(old_row) if old_row else None
    n = _strip_volatile_keys(new_row) if new_row else None
    if o == n:
        return None
    return {"old": _to_jsonable(o) if o else None, "new": _to_jsonable(n) if n else None}


def _dedup_preserve_order(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """順序を保ちつつ完全一致する dict を重複除去する。"""
    seen: set[tuple] = set()
    out: list[dict[str, Any]] = []
    for it in items:
        key = _row_to_hashable(it)
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def build_subtable_diff(
    old_subs: dict[str, Any],
    new_subs: dict[str, Any],
) -> dict[str, Any] | None:
    """複数副テーブルの diff をまとめる。

    Args:
        old_subs: {副テーブル名: <old スナップショット>} の dict。値の型は副テーブルに応じて
            list[dict] / list[scalar] / dict / None のいずれか。new_subs と同じキー集合・
            同じ値型を渡すこと。
        new_subs: 上と同じ構造で「変更後」のスナップショット。

    Returns:
        差分があった副テーブルだけを含む dict、なければ None。
    """
    keys = set(old_subs.keys()) | set(new_subs.keys())
    out: dict[str, Any] = {}
    for k in keys:
        old_v = old_subs.get(k)
        new_v = new_subs.get(k)
        # 型ごとに分岐
        if isinstance(old_v, list) or isinstance(new_v, list):
            sample = (old_v or new_v or [None])[0]
            if isinstance(sample, dict):
                d = diff_rows(old_v, new_v)
            else:
                d = diff_scalars(old_v, new_v)
        elif isinstance(old_v, dict) or isinstance(new_v, dict) or old_v is None or new_v is None:
            d = diff_single_row(
                old_v if isinstance(old_v, dict) else None,
                new_v if isinstance(new_v, dict) else None,
            )
        else:
            d = None
        if d:
            out[k] = d
    return out or None


# -----------------------------------------------------------------------------
# audit_logs 書き込み本体
# -----------------------------------------------------------------------------


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
            副テーブル差分を含める場合は `_subtables` キーに build_subtable_diff の戻り値を入れる。
    """
    import json

    schema_name = f"tenant_{tenant_id:03d}"

    old_json = json.dumps(old_data, ensure_ascii=False, default=str) if old_data else None
    new_json = json.dumps(new_data, ensure_ascii=False, default=str) if new_data else None

    # Phase 1-E F9-S4: SQLite テスト互換のため CAST(... AS jsonb) を外す。
    # PostgreSQL の jsonb 列は TEXT を自動で jsonb に変換するため安全。
    # SQLite では TEXT として保存される（型は緩い）。
    await db.execute(
        text(f"""
            INSERT INTO {schema_name}.audit_logs
                (tenant_id, user_id, action, table_name, record_id, old_data, new_data)
            VALUES
                (:tenant_id, :user_id, :action, :table_name, :record_id,
                 :old_data, :new_data)
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
