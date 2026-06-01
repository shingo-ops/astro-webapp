#!/usr/bin/env python3
"""新規テナント作成スクリプト（ADR-034）。

機能:
  1. public.tenants にテナントレコードを作成
  2. tenant_NNN スキーマを作成し、テーブル・RLS・システムロールを適用
  3. 過去の全 migration を catch-up 適用（新旧テナント間のスキーマ差分をゼロにする）
  4. tenant_004 との整合性チェック（ADR-036 Level 2）

使用方法:
  docker compose exec \
    -e TENANT_CODE=new-client-code \
    -e TENANT_NAME="新クライアント株式会社" \
    backend \
    python /app/scripts/setup_tenant.py

環境変数:
  TENANT_CODE  (必須) テナントコード（URL-safe 文字列、例: highlife-jpn）
  TENANT_NAME  (必須) テナント表示名（例: HIGH LIFE JPN）
  DATABASE_URL (必須) postgresql:// または postgresql+asyncpg:// 形式

冪等性:
  同一 TENANT_CODE で複数回実行しても安全。
  テナント・スキーマが既に存在する場合はスキップし、migration のみ再実行する。
  全 migration は ADD COLUMN IF NOT EXISTS / CREATE TABLE IF NOT EXISTS /
  ON CONFLICT 等で冪等に設計されている。

注意:
  - Firebase ユーザーの作成は別途実施すること（このスクリプトは DB 操作のみ）
  - Meta Channels の接続は OAuth フロー経由で別途実施すること
  - 作成後は CLAUDE.md 「新規テナント作成後の必須チェックリスト」を実施すること

変更履歴:
  2026-05-15: ADR-034 初版作成
  2026-05-15: ADR-036 Level 2: _verify_schema_integrity 追加
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parent.parent
if str(_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_ROOT))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = BASE_DIR / "migrations"


# ---------------------------------------------------------------------------
# SQL splitter（repo 内の他 migration runner と同じロジック）
# ---------------------------------------------------------------------------

def _split_sql_preserving_do_blocks(sql: str) -> list[str]:
    """DO $$ ... $$ ブロック内のセミコロンを保ったまま SQL を分割する。"""
    statements: list[str] = []
    buf: list[str] = []
    i = 0
    in_dollar = False
    dollar_tag = ""

    while i < len(sql):
        if sql[i] == "$":
            j = i + 1
            while j < len(sql) and (sql[j].isalnum() or sql[j] == "_"):
                j += 1
            if j < len(sql) and sql[j] == "$":
                tag = sql[i : j + 1]
                if not in_dollar:
                    in_dollar = True
                    dollar_tag = tag
                    buf.append(tag)
                    i = j + 1
                    continue
                elif tag == dollar_tag:
                    in_dollar = False
                    dollar_tag = ""
                    buf.append(tag)
                    i = j + 1
                    continue

        if sql[i] == ";" and not in_dollar:
            statements.append("".join(buf))
            buf = []
        else:
            buf.append(sql[i])
        i += 1

    if buf:
        statements.append("".join(buf))
    return statements


async def _exec(conn, sql: str) -> None:
    for stmt in _split_sql_preserving_do_blocks(sql):
        stmt = stmt.strip()
        if stmt:
            # text() はコメント内の `:word` をバインドパラメータとして誤解釈するため
            # exec_driver_sql でドライバに直接渡す（migration SQL は全て固定値）
            await conn.exec_driver_sql(stmt)


# ---------------------------------------------------------------------------
# Step 1: テナント作成
# ---------------------------------------------------------------------------

async def _ensure_tenant(engine, tenant_code: str, tenant_name: str) -> tuple[int, str]:
    """public.tenants にテナントを作成または取得する（冪等）。

    Returns:
        (tenant_id, schema_name)
    """
    async with engine.begin() as conn:
        row = (await conn.execute(
            text("SELECT id FROM public.tenants WHERE tenant_code = :code"),
            {"code": tenant_code},
        )).first()

        if row:
            tenant_id = int(row[0])
            schema_name = f"tenant_{tenant_id:03d}"
            logger.info("テナント '%s' は既存 (id=%d, schema=%s)", tenant_code, tenant_id, schema_name)
            return tenant_id, schema_name

        row = (await conn.execute(
            text("""
                INSERT INTO public.tenants (tenant_name, tenant_code, is_active)
                VALUES (:name, :code, TRUE)
                RETURNING id
            """),
            {"name": tenant_name, "code": tenant_code},
        )).first()
        tenant_id = int(row[0])
        schema_name = f"tenant_{tenant_id:03d}"
        logger.info("テナント '%s' 新規作成 (id=%d, schema=%s)", tenant_code, tenant_id, schema_name)

        await conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema_name}"))
        logger.info("  スキーマ %s 作成完了", schema_name)

    return tenant_id, schema_name


# ---------------------------------------------------------------------------
# Step 2: スキーマ適用（テーブル・RLS・システムロール）
# ---------------------------------------------------------------------------

async def _apply_base_schema(engine, tenant_id: int, schema_name: str) -> None:
    """テナントスキーマの基底テーブル・RLS・システムロールを適用する（冪等）。"""
    from app.services.tenant import (
        get_tenant_tables_sql,
        get_rls_enable_sql,
        get_rls_policy_sql,
        seed_system_roles,
        split_sql_preserving_do_blocks,
    )

    logger.info("スキーマ %s にテーブル・RLS・ロールを適用中...", schema_name)

    async with engine.begin() as conn:
        tables_sql = get_tenant_tables_sql(schema_name, tenant_id)
        for stmt in split_sql_preserving_do_blocks(tables_sql):
            stmt = stmt.strip()
            if stmt:
                await conn.execute(text(stmt))

        enable_sql = get_rls_enable_sql(schema_name)
        for stmt in enable_sql.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                await conn.execute(text(stmt))

        policy_sql = get_rls_policy_sql(schema_name)
        await conn.execute(text(policy_sql))

        await seed_system_roles(conn, tenant_id, schema_name)

    logger.info("  テーブル + RLS + ロールシード完了")


# ---------------------------------------------------------------------------
# Step 3: catch-up migration 適用
# ---------------------------------------------------------------------------

async def _apply_catchup_migrations(engine, tenant_id: int, schema_name: str) -> None:
    """過去の全 migration を指定テナントに catch-up 適用する（冪等）。

    deploy.yml が全テナントへ定期適用する migration と同じものを、
    新規テナント作成直後にも適用することで次の deploy を待たずにスキーマ差分をゼロにする。
    """
    logger.info("=== catch-up migration 開始 (schema=%s) ===", schema_name)

    # --- 公開スキーマ migration（pg_namespace で全テナントを自動カバーするもの）---
    # 014: public.current_tenant_id() ヘルパ関数（CREATE OR REPLACE で冪等）
    #       047〜050 の RLS ポリシーが参照するため、これらより先に実行必須。
    # 042: Meta Inbox 権限 seed（ON CONFLICT DO NOTHING で冪等）
    # 043: public.meta_page_routing テーブル作成（CREATE TABLE IF NOT EXISTS）
    # これらは新テナントが public スキーマに追加されたあとでも有効。
    public_migrations: list[tuple[str, str]] = [
        ("014_create_current_tenant_id_function.sql", "014: public.current_tenant_id() 関数"),
        ("042_seed_meta_inbox_permissions.sql", "042: Meta inbox permissions seed"),
        ("043_create_meta_page_routing.sql",    "043: public.meta_page_routing 作成"),
    ]
    for sql_file, desc in public_migrations:
        sql_path = MIGRATIONS_DIR / sql_file
        if not sql_path.exists():
            logger.warning("  skip %s: ファイルが存在しない", sql_file)
            continue
        try:
            async with engine.begin() as conn:
                await _exec(conn, sql_path.read_text("utf-8"))
            logger.info("  ✓ %s 適用完了", desc)
        except Exception as e:
            logger.error("  ✗ %s 失敗: %s", desc, e)
            raise

    # --- テナント固有 migration（{schema} / {tenant_id} を展開して実行）---
    # deploy.yml の migration runner 追加順序に合わせる（依存関係を考慮した順）。
    tenant_migrations: list[tuple[str, str]] = [
        # Phase 5: 拡張機能テーブル (shifts / erp_sync_logs)
        # NOTE: 2026-05-20 に catch-up 追加。それ以前に作られたテナントは
        # scripts/migrate_011_phase5_tenant_tables.py で遅延適用される。
        ("011_add_phase5_tenant_tables.sql",               "011: shifts + erp_sync_logs"),
        # Phase 1-D: Meta Inbox
        ("040_create_tenant_meta_config.sql",              "040: tenant_meta_config"),
        ("041_extend_meta_messages.sql",                   "041: meta_messages 9列追加"),
        # Phase 1-E: meta_page_routing trigger（043 の後に実行すること）
        ("044_create_meta_page_routing_trigger.sql",       "044: meta_page_routing トリガ"),
        ("045_add_meta_messages_page_id.sql",              "045: meta_messages.page_id"),
        # ADR-015: leads カラム + lead_playbook
        ("046_adr015_lead_foundation.sql",                 "046: leads + lead_playbook"),
        # ADR-021: 受注詳細
        ("047_create_order_financials.sql",                "047: order_financials"),
        ("048_create_order_shipping_details.sql",          "048: order_shipping_details"),
        ("049_create_order_purchase_details.sql",          "049: order_purchase_details"),
        ("050_add_commissions.sql",                        "050: commissions"),
        ("051_remove_confirmed_status.sql",                "051: confirmed → pending"),
        # ADR-026: message_id 型変更
        ("052_alter_meta_messages_message_id_to_text.sql", "052: message_id → TEXT"),
        # Discord 顧客メッセージング（受信箱連携）
        # pg_namespace ループ形式のため {schema} 置換不要。冪等（IF NOT EXISTS）。
        ("091_add_leads_discord_messaging_columns.sql",    "091: leads Discord DM カラム"),
        ("092_add_meta_messages_discord_index.sql",        "092: meta_messages discord インデックス"),
    ]
    for sql_file, desc in tenant_migrations:
        sql_path = MIGRATIONS_DIR / sql_file
        if not sql_path.exists():
            logger.warning("  skip %s: ファイルが存在しない", sql_file)
            continue
        tmpl = sql_path.read_text("utf-8")
        sql = (
            tmpl
            .replace("{schema}", schema_name)
            .replace("{schema_raw}", schema_name)
            .replace("{tenant_id}", str(tenant_id))
        )
        try:
            async with engine.begin() as conn:
                await _exec(conn, sql)
            logger.info("  ✓ %s 適用完了", desc)
        except Exception as e:
            logger.error("  ✗ %s 失敗: %s", desc, e)
            raise

    logger.info("=== catch-up migration 完了 ===")


# ---------------------------------------------------------------------------
# Step 4: スキーマ整合性検証（ADR-036 Level 2）
# ---------------------------------------------------------------------------

async def _verify_schema_integrity(engine, schema_name: str) -> None:
    """新規テナントのスキーマを tenant_004 と比較して整合性を確認する（非ブロッキング）。

    tenant_004 が存在しない場合はスキップ。
    差分があっても例外は送出せず、警告ログのみ出力する（情報提供目的）。
    """
    logger.info("=== スキーマ整合性チェック (%s vs tenant_004) ===", schema_name)

    if schema_name == "tenant_004":
        logger.info("  基準スキーマ自身のためスキップ")
        return

    try:
        async with engine.connect() as conn:
            # tenant_004 の存在確認
            row = await conn.execute(
                text("SELECT 1 FROM pg_namespace WHERE nspname = 'tenant_004'")
            )
            if not row.first():
                logger.info("  tenant_004 が存在しないためスキップ")
                return

            # カラム数比較
            ref_col_row = await conn.execute(
                text("""
                    SELECT COUNT(*) FROM information_schema.columns
                    WHERE table_schema = 'tenant_004'
                """)
            )
            ref_col_count = int(ref_col_row.scalar())

            tgt_col_row = await conn.execute(
                text("""
                    SELECT COUNT(*) FROM information_schema.columns
                    WHERE table_schema = :schema
                """),
                {"schema": schema_name},
            )
            tgt_col_count = int(tgt_col_row.scalar())

            # テーブル数比較
            ref_tbl_row = await conn.execute(
                text("""
                    SELECT COUNT(DISTINCT table_name)
                    FROM information_schema.columns
                    WHERE table_schema = 'tenant_004'
                """)
            )
            ref_tbl_count = int(ref_tbl_row.scalar())

            tgt_tbl_row = await conn.execute(
                text("""
                    SELECT COUNT(DISTINCT table_name)
                    FROM information_schema.columns
                    WHERE table_schema = :schema
                """),
                {"schema": schema_name},
            )
            tgt_tbl_count = int(tgt_tbl_row.scalar())

            # RLS 有効テーブル数比較
            ref_rls_row = await conn.execute(
                text("""
                    SELECT COUNT(*) FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = 'tenant_004'
                      AND c.relkind = 'r'
                      AND c.relrowsecurity = TRUE
                """)
            )
            ref_rls_count = int(ref_rls_row.scalar())

            tgt_rls_row = await conn.execute(
                text("""
                    SELECT COUNT(*) FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = :schema
                      AND c.relkind = 'r'
                      AND c.relrowsecurity = TRUE
                """),
                {"schema": schema_name},
            )
            tgt_rls_count = int(tgt_rls_row.scalar())

        logger.info(
            "  テーブル数: ref(tenant_004)=%d, new=%d",
            ref_tbl_count, tgt_tbl_count,
        )
        logger.info(
            "  カラム数:   ref(tenant_004)=%d, new=%d",
            ref_col_count, tgt_col_count,
        )
        logger.info(
            "  RLS有効:    ref(tenant_004)=%d, new=%d",
            ref_rls_count, tgt_rls_count,
        )

        issues: list[str] = []
        if tgt_tbl_count < ref_tbl_count:
            issues.append(f"テーブル不足 {ref_tbl_count - tgt_tbl_count} 件")
        if tgt_col_count < ref_col_count:
            issues.append(f"カラム不足 {ref_col_count - tgt_col_count} 件")
        if tgt_rls_count < ref_rls_count:
            issues.append(f"RLS未設定テーブル {ref_rls_count - tgt_rls_count} 件")

        if issues:
            logger.warning("  ⚠ 整合性問題を検出: %s", " / ".join(issues))
            logger.warning(
                "  → scripts/db/sync_tenant_schema.py を実行して差分を確認・適用してください。"
            )
        else:
            logger.info("  ✓ スキーマ整合性 OK")

    except Exception as e:
        logger.warning("  スキーマ整合性チェック中に例外（スキップ）: %s", e)

    logger.info("=== スキーマ整合性チェック完了 ===")


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------

async def main() -> None:
    tenant_code = os.getenv("TENANT_CODE", "").strip()
    tenant_name = os.getenv("TENANT_NAME", "").strip()

    if not tenant_code:
        logger.error("TENANT_CODE 環境変数が未設定です。")
        logger.error(
            "  例: docker compose exec"
            " -e TENANT_CODE=new-client"
            " -e TENANT_NAME='新クライアント株式会社'"
            " backend python /app/scripts/setup_tenant.py"
        )
        sys.exit(1)
    if not tenant_name:
        logger.error("TENANT_NAME 環境変数が未設定です。")
        sys.exit(1)

    db_url = os.getenv("DATABASE_URL", "")
    if not db_url:
        logger.error("DATABASE_URL が未設定です。")
        sys.exit(1)
    if db_url.startswith("postgresql://"):
        db_url = "postgresql+asyncpg://" + db_url[len("postgresql://"):]

    engine = create_async_engine(db_url, echo=False)

    try:
        logger.info("=== ADR-034: 新規テナント作成開始 ===")
        logger.info("  TENANT_CODE : %s", tenant_code)
        logger.info("  TENANT_NAME : %s", tenant_name)

        # 1. テナント作成（冪等）
        tenant_id, schema_name = await _ensure_tenant(engine, tenant_code, tenant_name)

        # 2. スキーマ適用（冪等）
        await _apply_base_schema(engine, tenant_id, schema_name)

        # 3. catch-up migration（冪等）
        await _apply_catchup_migrations(engine, tenant_id, schema_name)

        # 4. スキーマ整合性検証（ADR-036 Level 2）
        await _verify_schema_integrity(engine, schema_name)

        logger.info("=== ADR-034: テナント作成完了 ===")
        logger.info("  tenant_id   : %d", tenant_id)
        logger.info("  schema_name : %s", schema_name)
        logger.info("")
        logger.info("次のステップ（手動実施）:")
        logger.info("  1. Firebase ユーザーを作成する（管理画面または Firebase Console 経由）")
        logger.info("  2. ユーザーアカウントを API または admin UI 経由で作成する")
        logger.info("  3. Meta Channels を接続する（OAuth フロー経由）")
        logger.info("  4. CLAUDE.md「新規テナント作成後の必須チェックリスト」を実施する")
        logger.info("     （特に public.meta_page_routing への自動登録を確認）")

    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
