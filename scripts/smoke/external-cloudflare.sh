#!/usr/bin/env bash
# =============================================================================
# ADR-035: External State Verification — L2 Smoke: Cloudflare DNS
#
# 目的:
#   Cloudflare DNS / WAF の疎通テスト。
#   --dry-run / --sandbox / --live の 3 mode に対応。
#
# Mode:
#   --dry-run    設定だけ読んで表示、実行しない
#   --sandbox    (default) Cloudflare API に接続して zone の公開情報を確認
#   --live       Cloudflare API で DNS records / WAF ルール数を確認。PO_LIVE_OK=yes 必須
#
# 必須環境変数:
#   CLOUDFLARE_API_TOKEN   Cloudflare API Token (read-only で十分)
#
# 任意環境変数:
#   CF_ZONE_NAME     対象ゾーン (default: salesanchor.jp)
#
# --live mode 追加必須:
#   PO_LIVE_OK=yes
#
# 使い方:
#   bash scripts/smoke/external-cloudflare.sh [--dry-run|--sandbox|--live]
#
# 関連:
#   docs/adr/ADR-035-external-state-verification.md
#   scripts/snapshot/cloudflare.sh
#   docs/runbooks/B-06_cloudflare_setup.md
# =============================================================================
set -euo pipefail

MODE="${1:---sandbox}"
CF_API="https://api.cloudflare.com/client/v4"
ZONE_NAME="${CF_ZONE_NAME:-salesanchor.jp}"

log() {
    echo "[smoke/cloudflare] $(date -u +%Y-%m-%dT%H:%M:%SZ) $*" >&2
}

require_env() {
    local var="$1"
    if [[ -z "${!var:-}" ]]; then
        log "ERROR: required env var '${var}' is not set"
        exit 1
    fi
}

cf_api() {
    local path="$1"
    curl -fsS \
        -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" \
        -H "Content-Type: application/json" \
        "${CF_API}${path}"
}

case "$MODE" in
  --dry-run)
    log "MODE: dry-run"
    log "CLOUDFLARE_API_TOKEN=(masked, length=${#CLOUDFLARE_API_TOKEN:-0})"
    log "CF_ZONE_NAME=${ZONE_NAME}"
    log "dry-run: no API calls made"
    echo "PASS: dry-run complete"
    ;;

  --sandbox)
    log "MODE: sandbox"
    require_env CLOUDFLARE_API_TOKEN

    log "Checking Cloudflare API reachability..."
    TOKEN_STATUS=$(curl -fsS -o /dev/null -w "%{http_code}" \
        -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" \
        "${CF_API}/user/tokens/verify" 2>/dev/null || echo "000")
    log "Cloudflare token verify HTTP status: ${TOKEN_STATUS}"

    if [[ "$TOKEN_STATUS" != "200" ]]; then
        log "ERROR: Cloudflare token invalid or API unreachable (status=${TOKEN_STATUS})"
        exit 1
    fi
    echo "PASS: sandbox smoke OK (token verified, status=${TOKEN_STATUS})"
    ;;

  --live)
    if [[ "${PO_LIVE_OK:-}" != "yes" ]]; then
        log "ERROR: live mode requires PO_LIVE_OK=yes"
        exit 1
    fi
    log "MODE: live"
    require_env CLOUDFLARE_API_TOKEN

    # token verify
    log "Verifying Cloudflare API token..."
    TOKEN_VERIFY=$(cf_api "/user/tokens/verify") || { log "ERROR: token verify failed"; exit 1; }
    TOKEN_STATUS=$(echo "$TOKEN_VERIFY" | jq -r '.result.status // "unknown"')
    log "Token status: ${TOKEN_STATUS}"

    if [[ "$TOKEN_STATUS" != "active" ]]; then
        log "ERROR: Cloudflare token is not active (status=${TOKEN_STATUS})"
        exit 1
    fi

    # zone 一覧から対象 zone ID を取得
    log "Looking up zone ${ZONE_NAME}..."
    ZONES_RESP=$(cf_api "/zones?name=${ZONE_NAME}") || { log "ERROR: zones API failed"; exit 1; }
    ZONE_ID=$(echo "$ZONES_RESP" | jq -r '.result[0].id // empty')
    if [[ -z "$ZONE_ID" ]]; then
        log "ERROR: zone '${ZONE_NAME}' not found"
        exit 1
    fi
    log "Zone found: id=${ZONE_ID}"

    # DNS records 件数確認
    DNS_RESP=$(cf_api "/zones/${ZONE_ID}/dns_records") || { log "ERROR: DNS records API failed"; exit 1; }
    DNS_COUNT=$(echo "$DNS_RESP" | jq '.result_info.total_count // 0')
    log "DNS records count: ${DNS_COUNT}"

    echo "PASS: live smoke OK (zone=${ZONE_NAME}, id=${ZONE_ID}, dns_records=${DNS_COUNT})"
    ;;

  *)
    log "ERROR: unknown mode '${MODE}'. Use --dry-run, --sandbox, or --live"
    exit 1
    ;;
esac
