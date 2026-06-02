#!/bin/bash
# run_all_migrations.sh — 全DBマイグレーションを1本で実行する統合ランナー
#
# 目的:
#   deploy.yml の migration ステップ（旧 part 1 / part 2）を統合し、
#   「新マイグレーション追加時は deploy.yml ではなくこのファイルに追記する」を
#   唯一のルール（SSoT）にする。
#
# 使い方（deploy.yml から呼ばれる）:
#   bash scripts/run_all_migrations.sh
#
# 注意:
#   - set -e により途中でエラーが出た時点で即座に停止する
#   - 全マイグレーションは冪等設計（何度実行しても安全）
#   - 新マイグレーションは末尾の「ここから追加」セクションに追加すること
#   - 番号付きログで失敗箇所を特定できる（エラー時に [N/NN] が表示される）
#
# 参考: docs/adr/ADR-082, docs/adr/ADR-045

set -e

REPO_DIR="${REPO_DIR:-/home/ubuntu/salesanchor}"
BACKEND="astro-webapp-backend-1"
POSTGRES="astro-webapp-postgres-1"
PSQL="psql -U jarvis -d jarvis_db -v ON_ERROR_STOP=1"

cd "${REPO_DIR}"

# ── 前処理: scripts / migrations をコンテナにコピー ──────────────────────────
echo ">>> [0] Syncing scripts/ and migrations/ into backend container..."
docker cp scripts "${BACKEND}:/app/"
docker cp migrations "${BACKEND}:/app/"

# ── ヘルパー関数 ──────────────────────────────────────────────────────────────
STEP=0
TOTAL=84

run_py() {
  local script="$1"
  shift
  STEP=$((STEP + 1))
  echo ">>> [${STEP}/${TOTAL}] python ${script} $*"
  docker exec "$@" -w /app "${BACKEND}" python "${script}"
}

run_sql() {
  local file="$1"
  STEP=$((STEP + 1))
  echo ">>> [${STEP}/${TOTAL}] psql < ${file}"
  docker exec -i "${POSTGRES}" ${PSQL} < "${REPO_DIR}/${file}"
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# マイグレーション一覧（順序厳守・冪等必須）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Meta Webhook Phase 2
run_py  scripts/migrate_meta.py
run_sql migrations/013_add_meta_webhook_idempotency.sql

# Phase 1 再設計
run_sql migrations/014_create_current_tenant_id_function.sql
run_sql migrations/018_extend_permissions_with_menu_grain.sql
run_sql migrations/023_fix_system_admin_is_system_flag.sql
run_sql migrations/024_add_staff_bots_permissions.sql
run_sql migrations/025_resync_owner_admin_all_permissions.sql

# Phase 1-B-1: customer_contact_channels
run_sql migrations/026_create_customer_contact_channels.sql
run_sql migrations/027_backfill_customer_contact_channels.sql

# Phase 1-B-2: companies / contacts
run_sql migrations/028_create_companies.sql
run_sql migrations/029_create_contacts.sql
run_sql migrations/030_create_company_contact_subtables.sql
run_sql migrations/031_create_customer_migration_map.sql
run_sql migrations/032_add_company_contact_to_downstream.sql
run_sql migrations/033_drop_companies_is_individual.sql
run_sql migrations/034_add_unique_new_contact_id_to_customer_migration_map.sql
run_sql migrations/035_drop_customer_id_from_downstream.sql
run_sql migrations/036_drop_customer_migration_map.sql
run_sql migrations/037_add_pending_dedup_review_to_contacts_check.sql
run_sql migrations/038_add_products_phase1c_columns.sql

# Meta App Review
run_sql migrations/039_create_data_deletion_logs.sql

# Phase 1-D
run_py  scripts/migrate_meta_inbox_phase1d.py
run_py  scripts/migrate_meta_inbox_phase1d_sprint4.py
run_py  scripts/migrate_meta_page_routing.py
run_py  scripts/migrate_meta_messages_page_id.py

# ADR-015 leads
run_py  scripts/migrate_adr015_lead_foundation.py  -e TENANT_CODE=highlife-jpn

# ロール移行
run_py  scripts/migrate_roles_gas_compat.py

# ADR-021
run_py  scripts/migrate_adr021_sprint2_financials.py
run_py  scripts/migrate_adr021_sprint3_shipping.py
run_py  scripts/migrate_adr021_sprint4_purchase.py
run_py  scripts/migrate_adr021_sprint5_commissions.py
run_py  scripts/migrate_adr021_remove_confirmed_status.py

# ADR-026 / ADR-027 / ADR-033
run_py  scripts/migrate_meta_messages_message_id_to_text.py
run_sql migrations/053_add_users_locale.sql
run_sql migrations/054_add_users_theme.sql

# ADR-041 / ADR-045
run_py  scripts/migrate_adr041_granted_scopes.py

# Phase 4 / Phase 5 テナントテーブル
run_py  scripts/migrate_009_phase4_tenant_tables.py
run_py  scripts/migrate_011_phase5_tenant_tables.py

# Inventory Sprint 1〜9
run_py  scripts/migrate_inventory_sprint1.py
run_py  scripts/migrate_inventory_sprint2.py
run_py  scripts/migrate_inventory_sprint5_to_7.py
run_py  scripts/migrate_inventory_sprint8.py
run_py  scripts/migrate_inventory_sprint9.py

# Security Hardening
run_sql migrations/071_create_data_access_events.sql
run_sql migrations/072_add_retention_indexes.sql

# CRM
run_py  scripts/migrate_073_lead_status.py
run_py  scripts/migrate_074_rename_english_name_to_nickname.py
run_sql migrations/075_create_goals.sql
run_sql migrations/076_add_google_calendar_config.sql
run_sql migrations/077_calendar_sync_mode_and_webhook_subscriptions.sql
run_sql migrations/078_create_calendar_events_tenant.sql
run_sql migrations/080_phase_b_migration.sql

# Inventory 拡張
run_sql migrations/081_create_inventory.sql
run_sql migrations/082_extend_products_box_attributes.sql
run_sql migrations/083_add_staff_phone.sql
run_sql migrations/084_add_unit_to_inventory.sql
run_sql migrations/085_create_tcg_type_master.sql
run_sql migrations/086_seed_additional_tcg_types.sql
run_sql migrations/087_create_supplier_prompts.sql

# Lead / Discord / Meta 拡張
run_sql migrations/090_add_lead_contact_links.sql
run_sql migrations/091_add_leads_discord_messaging_columns.sql
run_sql migrations/092_add_meta_messages_discord_index.sql
run_sql migrations/093_rename_order_statuses.sql
run_sql migrations/094_create_message_translations.sql
run_sql migrations/095_add_lead_social_links.sql
run_sql migrations/096_add_deal_lead_source.sql

# ADR-089 Discord 顧客管理
run_sql migrations/097_create_company_discord.sql
run_sql migrations/098_migrate_customer_discord_to_company_discord.sql
run_sql migrations/099_add_discord_guild_config.sql

# 受信箱画像送信
run_sql migrations/100_add_meta_messages_image_columns.sql

# タイムスタンプ形式（101番以降）
run_sql migrations/20260601_140000_drop_customers_tables.sql
run_sql migrations/20260602_000000_add_products_central_columns.sql
run_sql migrations/20260602_010000_repoint_downstream_fk_to_public_products.sql
run_sql migrations/20260602_020000_add_products_tcg_type.sql
run_sql migrations/20260602_030000_add_products_unit.sql
run_sql migrations/20260602_040000_backfill_products_unit_condition_from_inbound.sql
run_sql migrations/20260602_120000_add_discord_ticket_config.sql

# ADR-091 KPI5: テナントごとの Discord チャンネル設定（小口/大口）
run_sql migrations/20260602_150000_add_discord_scale_channels.sql

# ADR-091 KPI7: Discord ロール名カラム追加
run_sql migrations/20260602_160000_add_discord_role_names.sql

# ADR-093 PR1: 商品マスタ 発送ラベル/検索/分類用 7 列追加
run_sql migrations/20260602_170000_add_products_master_label_columns.sql

# ADR-093 Phase 3a: inventory offer_type / ship_timing + UNIQUE キー拡張
run_sql migrations/20260602_180000_add_inventory_offer_type_ship_timing.sql

# ADR-093 Phase 4: 在庫表ユーザー別フィルタ設定テーブル
run_sql migrations/20260602_190000_create_user_inventory_filters.sql

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# >>> 新マイグレーションはここより下に追加してください <<<
# 形式:
#   run_sql migrations/YYYYMMDD_HHMMSS_description.sql
#   run_py  scripts/migrate_description.py
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

echo ""
echo "============================================"
echo "✅ 全マイグレーション完了 (${TOTAL}ステップ)"
echo "============================================"
