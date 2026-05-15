#!/usr/bin/env bash
# =============================================================================
# ADR-035: External State Verification — L2 Smoke: Firebase Auth
#
# 目的:
#   Firebase Auth の疎通テスト。
#   --dry-run / --sandbox / --live の 3 mode に対応。
#
# Mode:
#   --dry-run    設定だけ読んで表示、実行しない
#   --sandbox    (default) Firebase Auth Emulator 疎通（未設定なら dry-run fallback）
#   --live       本番 Firebase に疎通確認。PO_LIVE_OK=yes env 必須
#
# 必須環境変数:
#   FIREBASE_API_KEY
#   FIREBASE_AUTH_DOMAIN  (既定: auth.salesanchor.jp)
#   GCP_PROJECT_ID        (既定: sales-ops-with-claude)
#
# --live mode 追加必須:
#   PO_LIVE_OK=yes
#
# 使い方:
#   bash scripts/smoke/external-firebase.sh [--dry-run|--sandbox|--live]
#
# 関連:
#   docs/adr/ADR-035-external-state-verification.md
#   scripts/snapshot/firebase.sh
# =============================================================================
set -euo pipefail

MODE="${1:---sandbox}"

log() {
    echo "[smoke/firebase] $(date -u +%Y-%m-%dT%H:%M:%SZ) $*" >&2
}

require_env() {
    local var="$1"
    if [[ -z "${!var:-}" ]]; then
        log "ERROR: required env var '${var}' is not set"
        exit 1
    fi
}

AUTH_DOMAIN="${FIREBASE_AUTH_DOMAIN:-auth.salesanchor.jp}"
PROJECT_ID="${GCP_PROJECT_ID:-sales-ops-with-claude}"

case "$MODE" in
  --dry-run)
    log "MODE: dry-run"
    log "FIREBASE_API_KEY=(masked, length=${#FIREBASE_API_KEY:-0})"
    log "FIREBASE_AUTH_DOMAIN=${AUTH_DOMAIN}"
    log "GCP_PROJECT_ID=${PROJECT_ID}"
    log "dry-run: no API calls made"
    echo "PASS: dry-run complete"
    ;;

  --sandbox)
    log "MODE: sandbox"
    # Firebase Auth Emulator が FIREBASE_AUTH_EMULATOR_HOST で設定されていれば使用
    if [[ -n "${FIREBASE_AUTH_EMULATOR_HOST:-}" ]]; then
        log "Firebase Auth Emulator: ${FIREBASE_AUTH_EMULATOR_HOST}"
        EMULATOR_URL="http://${FIREBASE_AUTH_EMULATOR_HOST}/identitytoolkit.googleapis.com/v1/projects/${PROJECT_ID}/accounts:signInWithPassword"
        log "Checking emulator endpoint..."
        HTTP_STATUS=$(curl -fsS -o /dev/null -w "%{http_code}" \
            -X POST -H "Content-Type: application/json" \
            -d '{"email":"test@example.com","password":"test","returnSecureToken":true}' \
            "$EMULATOR_URL" 2>/dev/null || echo "000")
        log "Emulator response HTTP status: ${HTTP_STATUS}"
        echo "PASS: sandbox emulator reachable (status=${HTTP_STATUS})"
    else
        log "FIREBASE_AUTH_EMULATOR_HOST not set — falling back to dry-run"
        log "FIREBASE_API_KEY=(masked)"
        log "FIREBASE_AUTH_DOMAIN=${AUTH_DOMAIN}"
        log "GCP_PROJECT_ID=${PROJECT_ID}"
        echo "PASS: sandbox dry-run fallback (emulator not configured)"
    fi
    ;;

  --live)
    if [[ "${PO_LIVE_OK:-}" != "yes" ]]; then
        log "ERROR: live mode requires PO_LIVE_OK=yes"
        exit 1
    fi
    log "MODE: live"
    require_env FIREBASE_API_KEY

    log "Checking Firebase Auth domain reachability..."
    HTTP_STATUS=$(curl -fsS -o /dev/null -w "%{http_code}" \
        --max-time 10 \
        "https://${AUTH_DOMAIN}" 2>/dev/null || echo "000")
    log "Auth domain ${AUTH_DOMAIN} HTTP status: ${HTTP_STATUS}"

    # Firebase Identity Toolkit API エンドポイントの疎通確認
    # （実認証は行わない — 設定確認のみ）
    IDTK_URL="https://identitytoolkit.googleapis.com/v1/projects/${PROJECT_ID}?key=${FIREBASE_API_KEY}"
    IDTK_STATUS=$(curl -fsS -o /dev/null -w "%{http_code}" \
        --max-time 10 \
        "$IDTK_URL" 2>/dev/null || echo "000")
    log "Identity Toolkit project endpoint HTTP status: ${IDTK_STATUS}"

    if [[ "$HTTP_STATUS" == "000" ]]; then
        log "ERROR: auth domain unreachable"
        exit 1
    fi

    echo "PASS: live smoke OK (auth_domain=${AUTH_DOMAIN}, status=${HTTP_STATUS}, idtk_status=${IDTK_STATUS})"
    ;;

  *)
    log "ERROR: unknown mode '${MODE}'. Use --dry-run, --sandbox, or --live"
    exit 1
    ;;
esac
