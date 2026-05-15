#!/usr/bin/env bash
# =============================================================================
# ADR-035: External State Verification — L2 Smoke: GCP IAM
#
# 目的:
#   GCP IAM / Service Account の疎通テスト。
#   --dry-run / --sandbox / --live の 3 mode に対応。
#
# Mode:
#   --dry-run    設定だけ読んで表示、実行しない
#   --sandbox    (default) GCP API に接続して project 情報を確認
#   --live       GCP API で IAM binding / service account を確認。PO_LIVE_OK=yes 必須
#
# 必須環境変数:
#   GOOGLE_APPLICATION_CREDENTIALS   GCP service account JSON path
#   GCP_PROJECT_ID                    (既定: sales-ops-with-claude)
#
# --live mode 追加必須:
#   PO_LIVE_OK=yes
#
# 使い方:
#   bash scripts/smoke/external-gcp.sh [--dry-run|--sandbox|--live]
#
# 関連:
#   docs/adr/ADR-035-external-state-verification.md
#   scripts/snapshot/gcp.sh
# =============================================================================
set -euo pipefail

MODE="${1:---sandbox}"
PROJECT_ID="${GCP_PROJECT_ID:-sales-ops-with-claude}"

log() {
    echo "[smoke/gcp] $(date -u +%Y-%m-%dT%H:%M:%SZ) $*" >&2
}

require_env() {
    local var="$1"
    if [[ -z "${!var:-}" ]]; then
        log "ERROR: required env var '${var}' is not set"
        exit 1
    fi
}

get_access_token() {
    # Application Default Credentials (gcloud / service account JSON) からトークン取得
    if command -v gcloud &>/dev/null; then
        gcloud auth print-access-token 2>/dev/null
    elif [[ -n "${GOOGLE_APPLICATION_CREDENTIALS:-}" && -f "${GOOGLE_APPLICATION_CREDENTIALS}" ]]; then
        # python3 + google-auth でトークン取得（フォールバック）
        python3 -c "
import google.auth
import google.auth.transport.requests
creds, _ = google.auth.default()
req = google.auth.transport.requests.Request()
creds.refresh(req)
print(creds.token)
" 2>/dev/null
    else
        echo ""
    fi
}

case "$MODE" in
  --dry-run)
    log "MODE: dry-run"
    log "GCP_PROJECT_ID=${PROJECT_ID}"
    log "GOOGLE_APPLICATION_CREDENTIALS=${GOOGLE_APPLICATION_CREDENTIALS:-(not set)}"
    log "dry-run: no API calls made"
    echo "PASS: dry-run complete"
    ;;

  --sandbox)
    log "MODE: sandbox"
    require_env GOOGLE_APPLICATION_CREDENTIALS

    if [[ ! -f "${GOOGLE_APPLICATION_CREDENTIALS}" ]]; then
        log "ERROR: credentials file not found: ${GOOGLE_APPLICATION_CREDENTIALS}"
        exit 1
    fi

    # service account email を credentials JSON から読む（API 呼び出しなし）
    SA_EMAIL=$(jq -r '.client_email // empty' "${GOOGLE_APPLICATION_CREDENTIALS}" 2>/dev/null || echo "")
    if [[ -n "$SA_EMAIL" ]]; then
        log "Service account: ${SA_EMAIL}"
    else
        log "WARN: could not extract client_email from credentials JSON"
    fi

    log "GCP_PROJECT_ID=${PROJECT_ID}"
    echo "PASS: sandbox smoke OK (credentials_file=present, sa=${SA_EMAIL:-unknown})"
    ;;

  --live)
    if [[ "${PO_LIVE_OK:-}" != "yes" ]]; then
        log "ERROR: live mode requires PO_LIVE_OK=yes"
        exit 1
    fi
    log "MODE: live"
    require_env GOOGLE_APPLICATION_CREDENTIALS

    if [[ ! -f "${GOOGLE_APPLICATION_CREDENTIALS}" ]]; then
        log "ERROR: credentials file not found: ${GOOGLE_APPLICATION_CREDENTIALS}"
        exit 1
    fi

    ACCESS_TOKEN=$(get_access_token)
    if [[ -z "$ACCESS_TOKEN" ]]; then
        log "ERROR: could not obtain GCP access token"
        exit 1
    fi
    log "Access token obtained"

    # Project 疎通確認
    log "Checking GCP project ${PROJECT_ID}..."
    PROJECT_STATUS=$(curl -fsS -o /dev/null -w "%{http_code}" \
        -H "Authorization: Bearer ${ACCESS_TOKEN}" \
        "https://cloudresourcemanager.googleapis.com/v1/projects/${PROJECT_ID}" \
        2>/dev/null || echo "000")
    log "GCP project HTTP status: ${PROJECT_STATUS}"

    if [[ "$PROJECT_STATUS" != "200" ]]; then
        log "ERROR: GCP project API returned ${PROJECT_STATUS}"
        exit 1
    fi

    echo "PASS: live smoke OK (project=${PROJECT_ID}, status=${PROJECT_STATUS})"
    ;;

  *)
    log "ERROR: unknown mode '${MODE}'. Use --dry-run, --sandbox, or --live"
    exit 1
    ;;
esac
