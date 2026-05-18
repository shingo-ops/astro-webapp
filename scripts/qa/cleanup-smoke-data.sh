#!/usr/bin/env bash
# =============================================================================
# ADR-038 / QA Smoke Suite: 接頭辞 (qa- / QA-) データの安全クリーンアップ
#
# 目的:
#   スプリント間 / 撮影前 / CI 失敗復旧時に、smoke が残した行 (qa- / QA- 接頭辞)
#   を安全に削除する。tenant_006 (tenant-review) **以外には触らない**。
#
# 設計:
#   - tenant_code='tenant-review' を最初に assert
#   - 接頭辞ルールに一致するレコードのみ DELETE (TRUNCATE は使わない — seed 後の
#     部分削除に対応するため)
#   - FK 依存順 (子 → 親) で削除
#   - DRY_RUN=1 で削除対象件数のみ表示 (CI safe)
#
# 必須環境変数:
#   DATABASE_URL
#
# 任意環境変数:
#   DRY_RUN=1                   削除を実行せず件数だけ表示
#
# 使い方:
#   docker compose exec -T backend bash /app/scripts/qa/cleanup-smoke-data.sh
#   DRY_RUN=1 bash scripts/qa/cleanup-smoke-data.sh   # 件数確認のみ
#
# 関連:
#   docs/adr/ADR-038-qa-smoke-suite.md
#   scripts/qa/seed-tenant.sql
#   scripts/qa/reset-tenant.sh
#
# 変更履歴:
#   2026-05-15: ADR-038 初版
# =============================================================================
set -euo pipefail

log() {
    echo "[cleanup-smoke-data] $(date -u +%Y-%m-%dT%H:%M:%SZ) $*" >&2
}

if [[ -z "${DATABASE_URL:-}" ]]; then
    log "FATAL: DATABASE_URL is not set"
    exit 1
fi

PSQL_URL="${DATABASE_URL/postgresql+asyncpg:/postgresql:}"
DRY="${DRY_RUN:-0}"

# --- tenant_code assert ---
ACTUAL_CODE=$(psql "$PSQL_URL" -At -c "SELECT tenant_code FROM public.tenants WHERE id=6;")
if [[ "$ACTUAL_CODE" != "tenant-review" ]]; then
    log "FATAL: tenant_id=6 maps to tenant_code='$ACTUAL_CODE', expected 'tenant-review'. abort"
    exit 2
fi
log "tenant_code assert OK (tenant_006 = tenant-review)"

if [[ "$DRY" == "1" ]]; then
    log "DRY_RUN=1 — 件数のみ表示, 削除は実行しません"
    psql "$PSQL_URL" -v ON_ERROR_STOP=1 <<'EOSQL'
SET search_path = tenant_006, public;
\echo '--- counts (qa-/QA- prefix in tenant_006) ---'
SELECT 'meta_messages (qa-mid prefix)' AS table_name, COUNT(*) FROM tenant_006.meta_messages WHERE message_id LIKE 'qa-%';
SELECT 'tenant_meta_config (QA- page_id)', COUNT(*) FROM tenant_006.tenant_meta_config WHERE page_id LIKE 'QA-%';
SELECT 'orders (QA- order_number)',        COUNT(*) FROM tenant_006.orders WHERE order_number LIKE 'QA-%';
SELECT 'contacts (QA- contact_code)',      COUNT(*) FROM tenant_006.contacts WHERE contact_code LIKE 'QA-%';
SELECT 'companies (QA- company_code)',     COUNT(*) FROM tenant_006.companies WHERE company_code LIKE 'QA-%';
SELECT 'leads (QA- lead_code)',            COUNT(*) FROM tenant_006.leads WHERE lead_code LIKE 'QA-%';
SELECT 'products (QA- product_code)',      COUNT(*) FROM tenant_006.products WHERE product_code LIKE 'QA-%';
SELECT 'staff (qa- primary_email)',        COUNT(*) FROM tenant_006.staff WHERE primary_email LIKE 'qa-%';
SELECT 'public.users (qa- email)',         COUNT(*) FROM public.users WHERE email LIKE 'qa-%@salesanchor.jp';
SELECT 'public.meta_page_routing (QA- page_id)', COUNT(*) FROM public.meta_page_routing
    WHERE tenant_id = 6 AND (page_id LIKE 'QA-%' OR instagram_business_account_id LIKE 'QA-%');
EOSQL
    exit 0
fi

# --- 削除実行 ---
log "deleting qa-/QA- prefixed rows in tenant_006..."
psql "$PSQL_URL" -v ON_ERROR_STOP=1 <<'EOSQL'
BEGIN;
SET search_path = tenant_006, public;
SELECT set_config('app.tenant_id', '6', false);

-- FK 依存順: 子 → 親
DELETE FROM tenant_006.meta_messages
    WHERE platform IN ('messenger','instagram')
      AND (message_id LIKE 'qa-%' OR sender_id LIKE 'QA-%');

DELETE FROM public.meta_page_routing
    WHERE tenant_id = 6
      AND (page_id LIKE 'QA-%' OR instagram_business_account_id LIKE 'QA-%');

DELETE FROM tenant_006.tenant_meta_config
    WHERE page_id LIKE 'QA-%' OR instagram_business_account_id LIKE 'QA-%';

DELETE FROM tenant_006.orders        WHERE order_number  LIKE 'QA-%';
DELETE FROM tenant_006.contacts      WHERE contact_code  LIKE 'QA-%';
DELETE FROM tenant_006.companies     WHERE company_code  LIKE 'QA-%';
DELETE FROM tenant_006.leads         WHERE lead_code     LIKE 'QA-%';
DELETE FROM tenant_006.products      WHERE product_code  LIKE 'QA-%';

-- staff / users (qa- 接頭辞)
DELETE FROM tenant_006.staff_ui_preferences
    WHERE staff_id IN (SELECT id FROM tenant_006.staff WHERE primary_email LIKE 'qa-%');
DELETE FROM tenant_006.user_roles
    WHERE user_id IN (SELECT id FROM public.users WHERE email LIKE 'qa-%@salesanchor.jp');
DELETE FROM tenant_006.staff WHERE primary_email LIKE 'qa-%';
DELETE FROM public.users WHERE email LIKE 'qa-%@salesanchor.jp';

-- audit_logs (smoke 由来の manual_db_insert 記録) は削除しない
-- → 監査証跡保持のため、cleanup 対象から除外
COMMIT;
EOSQL

log "cleanup completed"
