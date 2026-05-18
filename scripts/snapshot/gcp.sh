#!/usr/bin/env bash
# =============================================================================
# ADR-035: External State Verification — L3 Snapshot: GCP IAM
#
# 目的:
#   GCP IAM bindings / Service accounts / Enabled APIs を JSON に保存し、
#   前回スナップショットとの diff で drift を検出する。
#
# SECRET SCRUB ルール（MANDATORY）:
#   - private_key / client_secret → del() で削除
#   - service account JSON の private_key は snapshot に書かない
#   - IAM binding の member (email) は保存対象（ユーザー識別子として必要）
#   Reviewer は merge 前に本スクリプトの scrub ロジックを目視確認すること。
#
# 必須環境変数:
#   GOOGLE_APPLICATION_CREDENTIALS   GCP service account JSON path
#   GCP_PROJECT_ID                    (既定: sales-ops-with-claude)
#
# 任意環境変数:
#   SNAPSHOT_DIR   出力ルートディレクトリ (default: external-state-snapshots)
#   SPRINT_TAG     スナップショットのディレクトリ名サフィックス (default: manual)
#
# 使い方:
#   bash scripts/snapshot/gcp.sh
#
# 出力:
#   ${SNAPSHOT_DIR}/${DATE}-${SPRINT_TAG}/gcp_iam_policy.json
#   ${SNAPSHOT_DIR}/${DATE}-${SPRINT_TAG}/gcp_service_accounts.json
#   ${SNAPSHOT_DIR}/${DATE}-${SPRINT_TAG}/gcp_enabled_apis.json
#
# 関連:
#   docs/adr/ADR-035-external-state-verification.md
#   scripts/smoke/external-gcp.sh
# =============================================================================
set -euo pipefail

SNAPSHOT_ROOT="${SNAPSHOT_DIR:-external-state-snapshots}"
SPRINT_TAG="${SPRINT_TAG:-manual}"
DATE_TAG="$(date +%Y-%m-%d)"
OUT="${SNAPSHOT_ROOT}/${DATE_TAG}-${SPRINT_TAG}"
PROJECT_ID="${GCP_PROJECT_ID:-sales-ops-with-claude}"

log() {
    echo "[snapshot/gcp] $(date -u +%Y-%m-%dT%H:%M:%SZ) $*" >&2
}

require_env() {
    local var="$1"
    if [[ -z "${!var:-}" ]]; then
        log "ERROR: required env var '${var}' is not set"
        exit 1
    fi
}

require_env GOOGLE_APPLICATION_CREDENTIALS

if [[ ! -f "${GOOGLE_APPLICATION_CREDENTIALS}" ]]; then
    log "ERROR: credentials file not found: ${GOOGLE_APPLICATION_CREDENTIALS}"
    exit 1
fi

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

mkdir -p "$OUT"
log "Output dir: ${OUT}"
log "GCP_PROJECT_ID: ${PROJECT_ID}"

ACCESS_TOKEN=$(get_access_token || echo "")
if [[ -z "$ACCESS_TOKEN" ]]; then
    log "ERROR: could not obtain GCP access token"
    exit 1
fi
log "Access token obtained"

# --- 1. IAM policy ---
log "Fetching IAM policy..."
curl -fsS \
    -H "Authorization: Bearer ${ACCESS_TOKEN}" \
    -X POST \
    "https://cloudresourcemanager.googleapis.com/v1/projects/${PROJECT_ID}:getIamPolicy" \
    | jq '{
        project_id: "'"$PROJECT_ID"'",
        bindings: [.bindings[] | {role: .role, member_count: (.members | length), members: .members}]
      }' \
    > "${OUT}/gcp_iam_policy.json"
log "Saved: ${OUT}/gcp_iam_policy.json"

# --- 2. Service accounts ---
log "Fetching service accounts..."
curl -fsS \
    -H "Authorization: Bearer ${ACCESS_TOKEN}" \
    "https://iam.googleapis.com/v1/projects/${PROJECT_ID}/serviceAccounts" \
    | jq '{
        project_id: "'"$PROJECT_ID"'",
        count: (.accounts | length),
        accounts: [.accounts[] | {
          email: .email,
          displayName: .displayName,
          disabled: .disabled
        }]
      }' \
    > "${OUT}/gcp_service_accounts.json"
log "Saved: ${OUT}/gcp_service_accounts.json"

# --- 3. Enabled APIs ---
log "Fetching enabled APIs..."
curl -fsS \
    -H "Authorization: Bearer ${ACCESS_TOKEN}" \
    "https://serviceusage.googleapis.com/v1/projects/${PROJECT_ID}/services?filter=state:ENABLED&pageSize=100" \
    | jq '{
        project_id: "'"$PROJECT_ID"'",
        count: (.services | length),
        services: [.services[] | .name | split("/") | last]
      }' \
    > "${OUT}/gcp_enabled_apis.json"
log "Saved: ${OUT}/gcp_enabled_apis.json"

# --- 4. prev snapshot との diff ---
PREV=$(ls -td "${SNAPSHOT_ROOT}"/*/ 2>/dev/null | grep -v "^${OUT}/$" | head -1 || echo "")
if [[ -n "$PREV" && -f "${PREV}gcp_iam_policy.json" ]]; then
    log "Diffing against prev snapshot: ${PREV}"
    for fname in gcp_iam_policy.json gcp_service_accounts.json gcp_enabled_apis.json; do
        if [[ -f "${PREV}${fname}" ]]; then
            if ! diff <(jq -S . "${PREV}${fname}") <(jq -S . "${OUT}/${fname}") > /dev/null 2>&1; then
                DIFF_OUT=$(diff <(jq -S . "${PREV}${fname}") <(jq -S . "${OUT}/${fname}") || true)
                log "DRIFT DETECTED in ${fname}:"
                echo "$DIFF_OUT" >&2
                echo "$DIFF_OUT" > "${OUT}/${fname%.json}.diff"
            fi
        fi
    done
else
    log "No previous snapshot found — this is the baseline"
fi

log "Snapshot complete: ${OUT}"
echo "DONE: ${OUT}"
