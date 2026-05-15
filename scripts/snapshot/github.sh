#!/usr/bin/env bash
# =============================================================================
# ADR-035: External State Verification — L3 Snapshot: GitHub
#
# 目的:
#   GitHub Secrets 一覧（存在確認のみ） / Branch protection 設定を JSON に保存し、
#   前回スナップショットとの diff で drift を検出する。
#
# SECRET SCRUB ルール（MANDATORY）:
#   - GitHub Secrets API は secret の値を返さない仕様（API で値は見えない）
#   - PAT 自体は snapshot に書かない
#   Reviewer は merge 前に本スクリプトの scrub ロジックを目視確認すること。
#
# 必須環境変数:
#   PIPELINE_PAT     GitHub Personal Access Token
#
# 任意環境変数:
#   GITHUB_REPO      対象リポジトリ (default: shingo-ops/salesanchor)
#   SNAPSHOT_DIR     出力ルートディレクトリ (default: external-state-snapshots)
#   SPRINT_TAG       スナップショットのディレクトリ名サフィックス (default: manual)
#
# 使い方:
#   bash scripts/snapshot/github.sh
#
# 出力:
#   ${SNAPSHOT_DIR}/${DATE}-${SPRINT_TAG}/github_secrets.json
#   ${SNAPSHOT_DIR}/${DATE}-${SPRINT_TAG}/github_branch_protection_develop.json
#   ${SNAPSHOT_DIR}/${DATE}-${SPRINT_TAG}/github_branch_protection_main.json
#
# 関連:
#   docs/adr/ADR-035-external-state-verification.md
#   scripts/smoke/external-github.sh
# =============================================================================
set -euo pipefail

SNAPSHOT_ROOT="${SNAPSHOT_DIR:-external-state-snapshots}"
SPRINT_TAG="${SPRINT_TAG:-manual}"
DATE_TAG="$(date +%Y-%m-%d)"
OUT="${SNAPSHOT_ROOT}/${DATE_TAG}-${SPRINT_TAG}"
REPO="${GITHUB_REPO:-shingo-ops/salesanchor}"
GH_API="https://api.github.com"

log() {
    echo "[snapshot/github] $(date -u +%Y-%m-%dT%H:%M:%SZ) $*" >&2
}

require_env() {
    local var="$1"
    if [[ -z "${!var:-}" ]]; then
        log "ERROR: required env var '${var}' is not set"
        exit 1
    fi
}

require_env PIPELINE_PAT

gh_api() {
    local path="$1"
    curl -fsS \
        -H "Authorization: token ${PIPELINE_PAT}" \
        -H "Accept: application/vnd.github+json" \
        "${GH_API}${path}"
}

mkdir -p "$OUT"
log "Output dir: ${OUT}"
log "Repo: ${REPO}"

# --- 1. Secrets 一覧（名前・updated_at のみ、値は API から返らない） ---
log "Fetching repository secrets list..."
SECRETS_RESP=$(gh_api "/repos/${REPO}/actions/secrets" 2>/dev/null \
    || echo '{"error":"secrets_api_failed","total_count":0,"secrets":[]}')
echo "$SECRETS_RESP" \
    | jq '{
        total_count: .total_count,
        secrets: [.secrets[] | {name: .name, updated_at: .updated_at, created_at: .created_at}]
      }' \
    > "${OUT}/github_secrets.json"
log "Saved: ${OUT}/github_secrets.json"

# --- 2. Branch protection: develop ---
log "Fetching branch protection for develop..."
BP_DEVELOP=$(gh_api "/repos/${REPO}/branches/develop/protection" 2>/dev/null \
    || echo '{"error":"branch_protection_api_failed_or_not_set"}')
echo "$BP_DEVELOP" \
    | jq 'del(.url) | if .required_status_checks then . else . end' \
    > "${OUT}/github_branch_protection_develop.json"
log "Saved: ${OUT}/github_branch_protection_develop.json"

# --- 3. Branch protection: main ---
log "Fetching branch protection for main..."
BP_MAIN=$(gh_api "/repos/${REPO}/branches/main/protection" 2>/dev/null \
    || echo '{"error":"branch_protection_api_failed_or_not_set"}')
echo "$BP_MAIN" \
    | jq 'del(.url) | if .required_status_checks then . else . end' \
    > "${OUT}/github_branch_protection_main.json"
log "Saved: ${OUT}/github_branch_protection_main.json"

# --- 4. prev snapshot との diff ---
PREV=$(ls -td "${SNAPSHOT_ROOT}"/*/ 2>/dev/null | grep -v "^${OUT}/$" | head -1 || echo "")
if [[ -n "$PREV" && -f "${PREV}github_secrets.json" ]]; then
    log "Diffing against prev snapshot: ${PREV}"
    for fname in github_secrets.json github_branch_protection_develop.json github_branch_protection_main.json; do
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
