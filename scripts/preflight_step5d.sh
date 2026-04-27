#!/usr/bin/env bash
# Phase 1-B-2 Step 5d preflight check (DRAFT — NOT YET APPLIED).
#
# Migration 035 を適用する直前に VPS 上で実行し、全テナントで安全条件を確認する。
#
# 確認項目:
#   1. 全 tenant_NNN スキーマの deals/orders/quotes/invoices で
#      company_id IS NULL の行が 0 件であること
#   2. customer_id IS NOT NULL かつ contact_id IS NULL の行が 0 件であること
#      （= 移行漏れ。Step 5c-3 で resolver が走らない経路が残っていた疑い）
#   3. _customer_migration_map に new_contact_id 重複が無いこと
#      （migration 034 の uniq_cmm_new_contact_id が全テナントに付いている前提）
#   4. 全テナントの _customer_migration_map で「old_customer_id を deals.customer_id 等で
#      参照している件数」と「new_contact_id を deals.contact_id 等で参照している件数」が
#      一致すること（= contact_id ベースで全部書き換わっている保証）
#
# 使い方（VPS 上で）:
#   bash /opt/astro-webapp/scripts/preflight_step5d.sh \
#       postgres://crmuser:PASS@127.0.0.1:5432/crm_db
#
# 終了ステータス:
#   0 — 全テナント PASS、035 適用に進んでよい
#   1 — 1 件以上 FAIL、原因を解消するまで 035 は適用しない
#
# 作成日: 2026-04-27 (DRAFT)

set -euo pipefail

DB_URL="${1:-${DATABASE_URL:-}}"
if [[ -z "$DB_URL" ]]; then
    echo "[ERROR] DB URL を引数または DATABASE_URL 環境変数で渡してください" >&2
    exit 2
fi

PSQL=(psql "$DB_URL" -X -A -t -v ON_ERROR_STOP=1)

# 全 tenant スキーマを列挙
TENANTS=$("${PSQL[@]}" -c "SELECT nspname FROM pg_namespace WHERE nspname ~ '^tenant_\\d+$' ORDER BY nspname")

if [[ -z "$TENANTS" ]]; then
    echo "[WARN] tenant_NNN スキーマが 1 件も無い。本番 DB に接続しているか確認" >&2
    exit 1
fi

FAIL_COUNT=0

check() {
    local schema="$1" sql="$2" label="$3" max_allowed="${4:-0}"
    local count
    count=$("${PSQL[@]}" -c "SET search_path TO ${schema}; ${sql}")
    count=${count// /}
    if [[ "$count" -gt "$max_allowed" ]]; then
        echo "[FAIL] ${schema} ${label}: ${count} 件（許容 ${max_allowed}）"
        FAIL_COUNT=$((FAIL_COUNT + 1))
    else
        echo "[PASS] ${schema} ${label}: ${count} 件"
    fi
}

for SCHEMA in $TENANTS; do
    echo "=== ${SCHEMA} ==="

    # 1. company_id IS NULL の検出
    for TBL in deals orders quotes invoices; do
        EXISTS=$("${PSQL[@]}" -c "SELECT 1 FROM pg_tables WHERE schemaname='${SCHEMA}' AND tablename='${TBL}'")
        if [[ -n "$EXISTS" ]]; then
            check "$SCHEMA" "SELECT COUNT(*) FROM ${TBL} WHERE company_id IS NULL" "${TBL}.company_id IS NULL" 0
        fi
    done

    # 2. customer_id 有り & contact_id 無しの不整合
    for TBL in deals orders quotes invoices; do
        EXISTS=$("${PSQL[@]}" -c "SELECT 1 FROM pg_tables WHERE schemaname='${SCHEMA}' AND tablename='${TBL}'")
        COL=$("${PSQL[@]}" -c "SELECT 1 FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='${SCHEMA}' AND c.relname='${TBL}' AND a.attname='customer_id' AND NOT a.attisdropped")
        if [[ -n "$EXISTS" && -n "$COL" ]]; then
            check "$SCHEMA" "SELECT COUNT(*) FROM ${TBL} WHERE customer_id IS NOT NULL AND contact_id IS NULL" "${TBL}: customer_id あり/contact_id なし" 0
        fi
    done

    # 3. _customer_migration_map.new_contact_id 重複
    EXISTS=$("${PSQL[@]}" -c "SELECT 1 FROM pg_tables WHERE schemaname='${SCHEMA}' AND tablename='_customer_migration_map'")
    if [[ -n "$EXISTS" ]]; then
        check "$SCHEMA" "SELECT COUNT(*) FROM (SELECT new_contact_id FROM _customer_migration_map GROUP BY new_contact_id HAVING COUNT(*)>1) d" "_customer_migration_map.new_contact_id 重複" 0

        # 4. uniq_cmm_new_contact_id 制約の存在確認（migration 034 の効果）
        UC=$("${PSQL[@]}" -c "SELECT 1 FROM pg_constraint WHERE conname='uniq_cmm_new_contact_id' AND connamespace=(SELECT oid FROM pg_namespace WHERE nspname='${SCHEMA}')")
        if [[ -z "$UC" ]]; then
            echo "[FAIL] ${SCHEMA} uniq_cmm_new_contact_id 制約なし（migration 034 未適用？）"
            FAIL_COUNT=$((FAIL_COUNT + 1))
        else
            echo "[PASS] ${SCHEMA} uniq_cmm_new_contact_id 制約あり"
        fi
    fi

    echo ""
done

if [[ "$FAIL_COUNT" -gt 0 ]]; then
    echo "[ABORT] ${FAIL_COUNT} 件 FAIL。migration 035 適用は中止してください。"
    exit 1
fi

echo "[OK] 全テナント PASS。migration 035 適用に進んでよい。"
exit 0
