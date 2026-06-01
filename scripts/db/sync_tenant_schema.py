#!/usr/bin/env python3
"""テナントスキーマ同期スクリプト（ADR-036 Level 1）。

tenant_004 を基準として全テナント（tenant_001〜）のスキーマ差分を検出し、
差分を自動適用する。

使用方法:
  # 差分検出のみ（適用なし）。差分あり=終了コード 1
  docker compose exec -e DATABASE_URL=... backend \\
    python /app/scripts/db/sync_tenant_schema.py --dry-run

  # 差分検出 + 自動適用
  docker compose exec -e DATABASE_URL=... backend \\
    python /app/scripts/db/sync_tenant_schema.py

環境変数:
  DATABASE_URL  (必須) postgresql:// または postgresql+asyncpg:// 形式

冪等性:
  全 catch-up migration は ADD COLUMN IF NOT EXISTS / ON CONFLICT 等で冪等。
  何度実行しても安全。

変更履歴:
  2026-05-15: ADR-036 Level 1 初版
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

# scripts/db/ → scripts/ → project root (= /app in Docker)
_APP_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_ROOT))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

# app.services.tenant の公開 API を再利用（named-tag 対応済み splitter）
from app.services.tenant import split_sql_preserving_do_blocks as _split_sql_preserving_do_blocks  # noqa: E501

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

MIGRATIONS_DIR = _APP_ROOT / "migrations"
REFERENCE_SCHEMA = "tenant_004"


# ---------------------------------------------------------------------------
# データ構造
# ---------------------------------------------------------------------------

@dataclass
class ColumnInfo:
    table_name: str
    column_name: str
    data_type: str
    is_nullable: str
    column_default: str | None
    character_maximum_length: int | None
    numeric_precision: int | None


@dataclass
class SchemaDiff:
    schema_name: str
    missing_tables: list[str] = field(default_factory=list)
    missing_columns: list[ColumnInfo] = field(default_factory=list)
    type_mismatches: list[tuple[str, str, str, str]] = field(default_factory=list)

    def has_diff(self) -> bool:
        return bool(self.missing_tables or self.missing_columns or self.type_mismatches)


# ---------------------------------------------------------------------------
# スキーマ情報取得
# ---------------------------------------------------------------------------

async def _get_schema_columns(
    conn: AsyncConnection, schema_name: str
) -> dict[str, dict[str, ColumnInfo]]:
    """information_schema.columns から {table: {col: ColumnInfo}} を返す。"""
    rows = await conn.execute(
        text("""
            SELECT
                table_name,
                column_name,
                data_type,
                is_nullable,
                column_default,
                character_maximum_length,
                numeric_precision
            FROM information_schema.columns
            WHERE table_schema = :schema
            ORDER BY table_name, ordinal_position
        """),
        {"schema": schema_name},
    )
    result: dict[str, dict[str, ColumnInfo]] = {}
    for row in rows:
        t = row.table_name
        c = ColumnInfo(
            table_name=t,
            column_name=row.column_name,
            data_type=row.data_type,
            is_nullable=row.is_nullable,
            column_default=row.column_default,
            character_maximum_length=row.character_maximum_length,
            numeric_precision=row.numeric_precision,
        )
        result.setdefault(t, {})[row.column_name] = c
    return result


async def _get_trigger_count(conn: AsyncConnection, schema_name: str) -> int:
    """テナントスキーマ内のトリガー数を返す。"""
    row = await conn.execute(
        text("""
            SELECT COUNT(*) FROM information_schema.triggers
            WHERE trigger_schema = :schema
        """),
        {"schema": schema_name},
    )
    return int(row.scalar())


async def _get_rls_enabled_count(conn: AsyncConnection, schema_name: str) -> int:
    """RLS が有効化されているテーブル数を返す。"""
    row = await conn.execute(
        text("""
            SELECT COUNT(*) FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = :schema
              AND c.relkind = 'r'
              AND c.relrowsecurity = TRUE
        """),
        {"schema": schema_name},
    )
    return int(row.scalar())


async def _get_role_permission_count(conn: AsyncConnection, schema_name: str) -> int:
    """テナントスキーマ内の role_permissions 行数（アプリ権限数）を返す。"""
    try:
        row = await conn.execute(
            text(f"SELECT COUNT(*) FROM {schema_name}.role_permissions")
        )
        return int(row.scalar())
    except Exception:
        return -1


# ---------------------------------------------------------------------------
# 差分計算
# ---------------------------------------------------------------------------

def _compute_diff(
    ref_cols: dict[str, dict[str, ColumnInfo]],
    target_cols: dict[str, dict[str, ColumnInfo]],
    schema_name: str,
) -> SchemaDiff:
    """基準スキーマとの差分を計算する。"""
    diff = SchemaDiff(schema_name=schema_name)

    for table, ref_table_cols in ref_cols.items():
        if table not in target_cols:
            diff.missing_tables.append(table)
            continue
        target_table_cols = target_cols[table]
        for col_name, ref_col in ref_table_cols.items():
            if col_name not in target_table_cols:
                diff.missing_columns.append(ref_col)
            else:
                t_col = target_table_cols[col_name]
                if t_col.data_type != ref_col.data_type:
                    diff.type_mismatches.append(
                        (table, col_name, ref_col.data_type, t_col.data_type)
                    )

    return diff


# ---------------------------------------------------------------------------
# DDL ヘルパー
# ---------------------------------------------------------------------------

def _col_type_ddl(col: ColumnInfo) -> str:
    """ColumnInfo から DDL 用の型文字列を生成する。"""
    dt = col.data_type
    if dt == "character varying":
        if col.character_maximum_length:
            return f"VARCHAR({col.character_maximum_length})"
        return "TEXT"
    if dt == "text":
        return "TEXT"
    if dt == "integer":
        return "INTEGER"
    if dt == "bigint":
        return "BIGINT"
    if dt == "smallint":
        return "SMALLINT"
    if dt == "boolean":
        return "BOOLEAN"
    if dt == "numeric":
        return "NUMERIC"
    if dt in ("timestamp with time zone", "timestamp without time zone"):
        return "TIMESTAMPTZ"
    if dt == "date":
        return "DATE"
    if dt == "jsonb":
        return "JSONB"
    if dt == "json":
        return "JSON"
    return dt.upper()


def _is_safe_default(col: ColumnInfo) -> bool:
    """シーケンス・関数呼出し系のデフォルトは ADD COLUMN 時に省略する（安全優先）。"""
    if col.column_default is None:
        return False
    lower = col.column_default.lower()
    return not any(
        kw in lower
        for kw in ("nextval", "now()", "current_timestamp", "gen_random_uuid")
    )


# ---------------------------------------------------------------------------
# 差分適用
# ---------------------------------------------------------------------------

async def _apply_diff(
    conn_or_none: AsyncConnection | None,
    diff: SchemaDiff,
    dry_run: bool,
) -> int:
    """差分を適用する。dry_run=True の場合はログ出力のみ。変更件数を返す。"""
    changes = 0

    # 1. テーブル欠落 → catch-up migration で対応済みのはずだが念のためログ
    for table in diff.missing_tables:
        logger.warning(
            "  ⚠ [%s] テーブル欠落（catch-up 後も残存）: %s",
            diff.schema_name,
            table,
        )
        changes += 1

    # 2. カラム欠落 → ALTER TABLE ADD COLUMN IF NOT EXISTS
    for col in diff.missing_columns:
        col_type = _col_type_ddl(col)
        nullable = "" if col.is_nullable == "YES" else " NOT NULL"
        default = (
            f" DEFAULT {col.column_default}"
            if col.column_default and _is_safe_default(col)
            else ""
        )
        sql = (
            f"ALTER TABLE {diff.schema_name}.{col.table_name} "
            f"ADD COLUMN IF NOT EXISTS {col.column_name} {col_type}{nullable}{default}"
        )
        logger.info(
            "  + [%s] ADD COLUMN: %s.%s %s",
            diff.schema_name,
            col.table_name,
            col.column_name,
            col_type,
        )
        if not dry_run and conn_or_none is not None:
            await conn_or_none.execute(text(sql))
        changes += 1

    # 3. 型不一致
    for table, col_name, ref_type, actual_type in diff.type_mismatches:
        # VARCHAR → TEXT は後退互換のため自動適用
        if actual_type == "character varying" and ref_type == "text":
            sql = (
                f"ALTER TABLE {diff.schema_name}.{table} "
                f"ALTER COLUMN {col_name} TYPE TEXT"
            )
            logger.info(
                "  ~ [%s] TYPE 変更: %s.%s  VARCHAR→TEXT",
                diff.schema_name,
                table,
                col_name,
            )
            if not dry_run and conn_or_none is not None:
                await conn_or_none.execute(text(sql))
            changes += 1
        else:
            logger.warning(
                "  ⚠ [%s] 型不一致（手動確認要）: %s.%s  ref=%s actual=%s",
                diff.schema_name,
                table,
                col_name,
                ref_type,
                actual_type,
            )

    return changes


async def _exec(conn: AsyncConnection, sql: str) -> None:
    for stmt in _split_sql_preserving_do_blocks(sql):
        stmt = stmt.strip()
        if stmt:
            await conn.execute(text(stmt))


# ---------------------------------------------------------------------------
# catch-up migration 適用（setup_tenant.py と同じリスト）
# ---------------------------------------------------------------------------

async def _apply_catchup_to_tenant(
    engine: AsyncEngine, tenant_id: int, schema_name: str
) -> None:
    """catch-up migration を指定テナントに適用する（冪等）。"""
    public_migrations: list[tuple[str, str]] = [
        ("042_seed_meta_inbox_permissions.sql", "042: Meta inbox permissions seed"),
        ("043_create_meta_page_routing.sql", "043: public.meta_page_routing 作成"),
        # ADR-089: customers テーブル廃止（全テナントループ形式・冪等）
        ("20260601_140000_drop_customers_tables.sql", "ADR-089: customers 関連テーブル DROP"),
    ]
    tenant_migrations: list[tuple[str, str]] = [
        ("040_create_tenant_meta_config.sql", "040: tenant_meta_config"),
        ("041_extend_meta_messages.sql", "041: meta_messages 9列追加"),
        ("044_create_meta_page_routing_trigger.sql", "044: meta_page_routing トリガ"),
        ("045_add_meta_messages_page_id.sql", "045: meta_messages.page_id"),
        ("046_adr015_lead_foundation.sql", "046: leads + lead_playbook"),
        ("047_create_order_financials.sql", "047: order_financials"),
        ("048_create_order_shipping_details.sql", "048: order_shipping_details"),
        ("049_create_order_purchase_details.sql", "049: order_purchase_details"),
        ("050_add_commissions.sql", "050: commissions"),
        ("051_remove_confirmed_status.sql", "051: confirmed → pending"),
        ("052_alter_meta_messages_message_id_to_text.sql", "052: message_id → TEXT"),
        # Discord 顧客メッセージング（受信箱連携）
        ("091_add_leads_discord_messaging_columns.sql",    "091: leads Discord DM カラム"),
        ("092_add_meta_messages_discord_index.sql",        "092: meta_messages discord インデックス"),
    ]

    for sql_file, desc in public_migrations:
        sql_path = MIGRATIONS_DIR / sql_file
        if not sql_path.exists():
            logger.debug("    skip %s: ファイル不在", sql_file)
            continue
        async with engine.begin() as conn:
            await _exec(conn, sql_path.read_text("utf-8"))
        logger.info("    ✓ %s", desc)

    for sql_file, desc in tenant_migrations:
        sql_path = MIGRATIONS_DIR / sql_file
        if not sql_path.exists():
            logger.debug("    skip %s: ファイル不在", sql_file)
            continue
        tmpl = sql_path.read_text("utf-8")
        sql = (
            tmpl
            .replace("{schema}", schema_name)
            .replace("{schema_raw}", schema_name)
            .replace("{tenant_id}", str(tenant_id))
        )
        async with engine.begin() as conn:
            await _exec(conn, sql)
        logger.info("    ✓ %s", desc)


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------

async def main(dry_run: bool) -> int:
    """スキーマ同期を実行する。dry_run かつ差分ありなら終了コード 1 を返す。"""
    db_url = os.getenv("DATABASE_URL", "")
    if not db_url:
        logger.error("DATABASE_URL が未設定です。")
        return 2
    if db_url.startswith("postgresql://"):
        db_url = "postgresql+asyncpg://" + db_url[len("postgresql://"):]

    engine = create_async_engine(db_url, echo=False)
    total_diff_count = 0

    try:
        # アクティブテナント一覧
        async with engine.connect() as conn:
            rows = await conn.execute(
                text("SELECT id FROM public.tenants WHERE is_active = TRUE ORDER BY id")
            )
            tenant_ids: list[int] = [row[0] for row in rows]

        if not tenant_ids:
            logger.warning("アクティブなテナントが見つかりません。")
            return 0

        logger.info("アクティブテナント: %s", tenant_ids)

        # 基準スキーマの存在確認
        async with engine.connect() as conn:
            row = await conn.execute(
                text("SELECT 1 FROM pg_namespace WHERE nspname = :s"),
                {"s": REFERENCE_SCHEMA},
            )
            if not row.first():
                logger.error(
                    "基準スキーマ %s が存在しません。"
                    " tenant_004 を先に作成してください。",
                    REFERENCE_SCHEMA,
                )
                return 2

        # 基準スキーマのカラム情報（ループ外で一度だけ取得）
        async with engine.connect() as conn:
            ref_cols = await _get_schema_columns(conn, REFERENCE_SCHEMA)

        ref_table_count = len(ref_cols)
        ref_col_count = sum(len(v) for v in ref_cols.values())
        logger.info("基準スキーマ %s: %d テーブル, %d カラム", REFERENCE_SCHEMA, ref_table_count, ref_col_count)

        for tid in tenant_ids:
            schema = f"tenant_{tid:03d}"
            if schema == REFERENCE_SCHEMA:
                logger.info("[%s] 基準スキーマのためスキップ", schema)
                continue

            logger.info("--- [%s] 差分チェック開始 ---", schema)

            # catch-up migration 適用（dry-run でなければ）
            if not dry_run:
                logger.info("  catch-up migration 適用中...")
                try:
                    await _apply_catchup_to_tenant(engine, tid, schema)
                except Exception as e:
                    logger.error("  catch-up migration 失敗: %s", e)
                    raise

            # カラム差分計算（スキーマ存在確認も兼ねる：空 dict = スキーマ不在）
            async with engine.connect() as conn:
                target_cols = await _get_schema_columns(conn, schema)

                if not target_cols:
                    logger.warning("  スキーマ %s が存在しないか空です。スキップ。", schema)
                    continue

                diff = _compute_diff(ref_cols, target_cols, schema)
                tgt_table_count = len(target_cols)
                tgt_col_count = sum(len(v) for v in target_cols.values())
                trigger_count = await _get_trigger_count(conn, schema)
                rls_count = await _get_rls_enabled_count(conn, schema)
                perm_count = await _get_role_permission_count(conn, schema)

            logger.info(
                "  テーブル: ref=%d target=%d | カラム: ref=%d target=%d"
                " | トリガー: %d | RLS有効: %d | role_permissions: %d",
                ref_table_count,
                tgt_table_count,
                ref_col_count,
                tgt_col_count,
                trigger_count,
                rls_count,
                perm_count,
            )

            if diff.has_diff():
                logger.warning(
                    "  差分あり: missing_tables=%d missing_columns=%d type_mismatches=%d",
                    len(diff.missing_tables),
                    len(diff.missing_columns),
                    len(diff.type_mismatches),
                )
                if dry_run:
                    await _apply_diff(None, diff, dry_run=True)
                else:
                    async with engine.begin() as conn:
                        n = await _apply_diff(conn, diff, dry_run=False)
                    total_diff_count += n
                total_diff_count += (
                    len(diff.missing_tables)
                    + len(diff.missing_columns)
                    + len(diff.type_mismatches)
                ) if dry_run else 0
            else:
                logger.info("  ✓ 差分なし")

        if dry_run:
            if total_diff_count > 0:
                logger.warning(
                    "=== [dry-run] 差分 %d 件を検出（未適用）===", total_diff_count
                )
                return 1
            logger.info("=== [dry-run] 全テナント差分なし ===")
            return 0

        if total_diff_count > 0:
            logger.info("=== 同期完了: %d 件を適用しました ===", total_diff_count)
        else:
            logger.info("=== 全テナント同期済み（差分なし）===")
        return 0

    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="テナントスキーマ同期スクリプト（ADR-036 Level 1）"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="差分検出のみ（適用しない）。差分ありなら終了コード 1。",
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(main(dry_run=args.dry_run)))
