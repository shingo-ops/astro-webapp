#!/usr/bin/env bash
# =============================================================================
# ADR-035: External State Verification — L3 Snapshot: Firebase Auth
#
# 目的:
#   Firebase Auth の設定（providers / authorized_domains）を JSON に保存し、
#   前回スナップショットとの diff で drift を検出する。
#
# SECRET SCRUB ルール（MANDATORY）:
#   - raw secret は絶対に snapshot json に書かない
#   - private_key / client_secret → del() で削除
#   - 存在の有無は *_present: true/false
#   Reviewer は merge 前に本スクリプトの scrub ロジックを目視確認すること。
#
# 必須環境変数:
#   GOOGLE_APPLICATION_CREDENTIALS   GCP service account JSON path
#   GCP_PROJECT_ID                    (既定: sales-ops-with-claude)
#   FIREBASE_API_KEY
#
# 任意環境変数:
#   SNAPSHOT_DIR   出力ルートディレクトリ (default: external-state-snapshots)
#   SPRINT_TAG     スナップショットのディレクトリ名サフィックス (default: manual)
#
# 使い方:
#   bash scripts/snapshot/firebase.sh
#
# 出力:
#   ${SNAPSHOT_DIR}/${DATE}-${SPRINT_TAG}/firebase_config.json
#   ${SNAPSHOT_DIR}/${DATE}-${SPRINT_TAG}/firebase_authorized_domains.json
#
# 関連:
#   docs/adr/ADR-035-external-state-verification.md
#   scripts/smoke/external-firebase.sh
# =============================================================================
set -euo pipefail

SNAPSHOT_ROOT="${SNAPSHOT_DIR:-external-state-snapshots}"
SPRINT_TAG="${SPRINT_TAG:-manual}"
DATE_TAG="$(date +%Y-%m-%d)"
OUT="${SNAPSHOT_ROOT}/${DATE_TAG}-${SPRINT_TAG}"
PROJECT_ID="${GCP_PROJECT_ID:-sales-ops-with-claude}"

log() {
    echo "[snapshot/firebase] $(date -u +%Y-%m-%dT%H:%M:%SZ) $*" >&2
}

require_env() {
    local var="$1"
    if [[ -z "${!var:-}" ]]; then
        log "ERROR: required env var '${var}' is not set"
        exit 1
    fi
}

require_env GOOGLE_APPLICATION_CREDENTIALS
require_env FIREBASE_API_KEY

if [[ ! -f "${GOOGLE_APPLICATION_CREDENTIALS}" ]]; then
    log "ERROR: credentials file not found: ${GOOGLE_APPLICATION_CREDENTIALS}"
    exit 1
fi

mkdir -p "$OUT"
log "Output dir: ${OUT}"
log "GCP_PROJECT_ID: ${PROJECT_ID}"

# --- Access Token 取得 ---
get_access_token() {
    if command -v gcloud &>/dev/null; then
        gcloud auth print-access-token 2>/dev/null
    else
        python3 -c "
import google.auth, google.auth.transport.requests
creds, _ = google.auth.default(scopes=['https://www.googleapis.com/auth/cloud-platform'])
req = google.auth.transport.requests.Request()
creds.refresh(req)
print(creds.token)
" 2>/dev/null
    fi
}

ACCESS_TOKEN=$(get_access_token || echo "")
if [[ -z "$ACCESS_TOKEN" ]]; then
    log "WARN: could not obtain GCP access token — using credentials file metadata only"
fi

# --- 1. credentials.json から scrub 済み config を保存 ---
log "Saving Firebase credentials metadata (scrubbed)..."
jq '(.private_key_id // "" | if . != "" then (.[0:8] + "...") else "empty" end) as $kid_sha
    | del(.private_key, .private_key_id)
    | .private_key_present = true
    | .private_key_id_sha256 = $kid_sha' \
    "${GOOGLE_APPLICATION_CREDENTIALS}" \
    > "${OUT}/firebase_config.json"
log "Saved: ${OUT}/firebase_config.json"

# --- 2. Firebase Auth authorized domains（Identity Toolkit API 経由） ---
if [[ -n "$ACCESS_TOKEN" ]]; then
    log "Fetching Firebase Auth config (authorized domains)..."
    FIREBASE_AUTH_RESP=$(curl -fsS \
        -H "Authorization: Bearer ${ACCESS_TOKEN}" \
        "https://identitytoolkit.googleapis.com/v2/projects/${PROJECT_ID}/config" \
        2>/dev/null || echo '{"error":"api_call_failed"}')
    echo "$FIREBASE_AUTH_RESP" \
        | jq 'del(.client.api_key, .mfa.enabled_providers // empty)' \
        > "${OUT}/firebase_authorized_domains.json"
    log "Saved: ${OUT}/firebase_authorized_domains.json"
else
    log "WARN: skipping authorized domains fetch (no access token)"
    echo '{"error":"no_access_token","authorized_domains":null}' \
        > "${OUT}/firebase_authorized_domains.json"
fi

# --- 3. prev snapshot との diff ---
PREV=$(ls -td "${SNAPSHOT_ROOT}"/*/ 2>/dev/null | grep -v "^${OUT}/$" | head -1 || echo "")
if [[ -n "$PREV" && -f "${PREV}firebase_config.json" ]]; then
    log "Diffing against prev snapshot: ${PREV}"
    if ! diff <(jq -S . "${PREV}firebase_config.json") <(jq -S . "${OUT}/firebase_config.json") > /dev/null 2>&1; then
        DIFF_OUT=$(diff <(jq -S . "${PREV}firebase_config.json") <(jq -S . "${OUT}/firebase_config.json") || true)
        log "DRIFT DETECTED in firebase_config.json:"
        echo "$DIFF_OUT" >&2
        echo "$DIFF_OUT" > "${OUT}/firebase_config.diff"
    fi
else
    log "No previous snapshot found — this is the baseline"
fi

log "Snapshot complete: ${OUT}"
echo "DONE: ${OUT}"
