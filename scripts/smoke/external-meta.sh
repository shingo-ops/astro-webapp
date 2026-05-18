#!/usr/bin/env bash
# =============================================================================
# ADR-035: External State Verification — L2 Smoke: Meta App
#
# 目的:
#   Meta App (Graph API) の疎通テスト。
#   --dry-run / --sandbox / --live の 3 mode に対応。
#
# NOTE (Phase 0):
#   --sandbox mode は Meta sandbox app 未整備のため dry-run 相当として動作する。
#   sandbox app の正式整備（META_SANDBOX_APP_ID 等）は別 ADR で扱う（ADR-035 Scope OUT）。
#
# Mode:
#   --dry-run    設定だけ読んで表示、実行しない
#   --sandbox    (default) sandbox mode = Phase 0 では dry-run 相当
#   --live       本番 API に投げる。PO_LIVE_OK=yes env 必須
#
# 必須環境変数:
#   META_APP_ID
#   META_APP_SECRET
#   META_PAGE_ID
#   META_GRAPH_API_VERSION  (任意、既定 v19.0)
#
# --live mode 追加必須:
#   PO_LIVE_OK=yes
#
# 使い方:
#   bash scripts/smoke/external-meta.sh [--dry-run|--sandbox|--live]
#
# 関連:
#   docs/adr/ADR-035-external-state-verification.md
#   scripts/snapshot/meta.sh
# =============================================================================
set -euo pipefail

MODE="${1:---sandbox}"

log() {
    echo "[smoke/meta] $(date -u +%Y-%m-%dT%H:%M:%SZ) $*" >&2
}

require_env() {
    local var="$1"
    if [[ -z "${!var:-}" ]]; then
        log "ERROR: required env var '${var}' is not set"
        exit 1
    fi
}

GRAPH_VERSION="${META_GRAPH_API_VERSION:-v19.0}"

case "$MODE" in
  --dry-run)
    log "MODE: dry-run"
    log "META_APP_ID=${META_APP_ID:-(not set)}"
    log "META_PAGE_ID=${META_PAGE_ID:-(not set)}"
    log "META_GRAPH_API_VERSION=${GRAPH_VERSION}"
    log "META_APP_SECRET=(masked)"
    log "META_PAGE_TOKEN=(masked)"
    log "dry-run: no API calls made"
    echo "PASS: dry-run complete"
    ;;

  --sandbox)
    # Phase 0: sandbox app 未整備のため dry-run 相当で動作
    echo "WARN: sandbox app は未整備のため dry-run 動作（ADR-035 Scope OUT）" >&2
    log "MODE: sandbox (dry-run fallback — Meta sandbox app not yet provisioned)"
    log "META_APP_ID=${META_APP_ID:-(not set)}"
    log "META_PAGE_ID=${META_PAGE_ID:-(not set)}"
    log "META_GRAPH_API_VERSION=${GRAPH_VERSION}"
    log "META_APP_SECRET=(masked)"
    log "META_PAGE_TOKEN=(masked)"
    log "sandbox: no API calls made (scaffold only)"
    echo "PASS: sandbox scaffold (dry-run equivalent)"
    ;;

  --live)
    if [[ "${PO_LIVE_OK:-}" != "yes" ]]; then
        log "ERROR: live mode requires PO_LIVE_OK=yes"
        exit 1
    fi
    log "MODE: live"
    require_env META_APP_ID
    require_env META_APP_SECRET
    require_env META_PAGE_ID

    META_APP_ACCESS_TOKEN="${META_APP_ID}|${META_APP_SECRET}"

    log "Checking Meta App via Graph API ${GRAPH_VERSION}..."
    APP_RESP=$(curl -fsS \
        "https://graph.facebook.com/${GRAPH_VERSION}/${META_APP_ID}?access_token=${META_APP_ACCESS_TOKEN}" \
        2>&1) || { log "ERROR: Meta Graph API call failed"; exit 1; }

    # id フィールドで疎通確認
    APP_ID_FROM_API=$(echo "$APP_RESP" | jq -r '.id // empty')
    if [[ -z "$APP_ID_FROM_API" ]]; then
        log "ERROR: Meta API response missing .id field. Response: ${APP_RESP}"
        exit 1
    fi
    log "Meta App confirmed: id=${APP_ID_FROM_API}"

    log "Checking Meta Page subscriptions..."
    SUB_RESP=$(curl -fsS \
        "https://graph.facebook.com/${GRAPH_VERSION}/${META_APP_ID}/subscriptions?access_token=${META_APP_ACCESS_TOKEN}" \
        2>&1) || { log "ERROR: Meta subscriptions API call failed"; exit 1; }

    SUB_COUNT=$(echo "$SUB_RESP" | jq '.data | length // 0')
    log "Subscriptions count: ${SUB_COUNT}"

    echo "PASS: live smoke OK (app_id=${APP_ID_FROM_API}, subscriptions=${SUB_COUNT})"
    ;;

  *)
    log "ERROR: unknown mode '${MODE}'. Use --dry-run, --sandbox, or --live"
    exit 1
    ;;
esac
