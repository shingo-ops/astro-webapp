#!/usr/bin/env bash
# =============================================================================
# ADR-035: External State Verification — L3 Snapshot: Meta App
#
# 目的:
#   Meta App (Graph API) の状態を JSON にスナップショット保存し、
#   前回スナップショットとの diff で drift を検出する。
#
# SECRET SCRUB ルール（MANDATORY）:
#   - raw secret は絶対に snapshot json に書かない
#   - access_token / refresh_token → del() で削除
#   - secret value の指紋が必要なら sha256 前 8 文字のみ記録
#   - 存在の有無だけ必要な場合は *_present: true/false
#   Reviewer は merge 前に本スクリプトの scrub ロジックを目視確認すること。
#
# 必須環境変数:
#   META_APP_ID
#   META_APP_SECRET
#   META_PAGE_ID
#   META_PAGE_TOKEN
#   META_GRAPH_API_VERSION  (任意、既定 v19.0)
#
# 任意環境変数:
#   SNAPSHOT_DIR   出力ルートディレクトリ (default: external-state-snapshots)
#   SPRINT_TAG     スナップショットのディレクトリ名サフィックス (default: manual)
#
# 使い方:
#   bash scripts/snapshot/meta.sh
#
# 出力:
#   ${SNAPSHOT_DIR}/${DATE}-${SPRINT_TAG}/meta_app.json
#   ${SNAPSHOT_DIR}/${DATE}-${SPRINT_TAG}/meta_subscriptions.json
#   ${SNAPSHOT_DIR}/${DATE}-${SPRINT_TAG}/meta_page_subscribed_apps.json
#
# 関連:
#   docs/adr/ADR-035-external-state-verification.md
#   scripts/smoke/external-meta.sh
# =============================================================================
set -euo pipefail

SNAPSHOT_ROOT="${SNAPSHOT_DIR:-external-state-snapshots}"
SPRINT_TAG="${SPRINT_TAG:-manual}"
DATE_TAG="$(date +%Y-%m-%d)"
OUT="${SNAPSHOT_ROOT}/${DATE_TAG}-${SPRINT_TAG}"

log() {
    echo "[snapshot/meta] $(date -u +%Y-%m-%dT%H:%M:%SZ) $*" >&2
}

require_env() {
    local var="$1"
    if [[ -z "${!var:-}" ]]; then
        log "ERROR: required env var '${var}' is not set"
        exit 1
    fi
}

require_env META_APP_ID
require_env META_APP_SECRET
require_env META_PAGE_ID
require_env META_PAGE_TOKEN

GRAPH_VERSION="${META_GRAPH_API_VERSION:-v19.0}"

# App access token: META_APP_ID|META_APP_SECRET 形式（Meta 公式仕様）
# META_APP_TOKEN という env は存在しないため使わない（ADR-035 recon 参照）
META_APP_ACCESS_TOKEN="${META_APP_ID}|${META_APP_SECRET}"

mkdir -p "$OUT"
log "Output dir: ${OUT}"
log "Graph API version: ${GRAPH_VERSION}"

# --- 1. App 情報 ---
log "Fetching Meta App info..."
curl -fsS \
    "https://graph.facebook.com/${GRAPH_VERSION}/${META_APP_ID}?access_token=${META_APP_ACCESS_TOKEN}" \
    | jq 'del(.access_token, .client_secret, .app_secret_proof) | .app_secret_present = true' \
    > "${OUT}/meta_app.json"
log "Saved: ${OUT}/meta_app.json"

# --- 2. App subscriptions ---
log "Fetching Meta App subscriptions..."
curl -fsS \
    "https://graph.facebook.com/${GRAPH_VERSION}/${META_APP_ID}/subscriptions?access_token=${META_APP_ACCESS_TOKEN}" \
    | jq '.' \
    > "${OUT}/meta_subscriptions.json"
log "Saved: ${OUT}/meta_subscriptions.json"

# --- 3. Page subscribed_apps ---
log "Fetching Meta Page subscribed_apps..."
curl -fsS \
    "https://graph.facebook.com/${GRAPH_VERSION}/${META_PAGE_ID}/subscribed_apps?access_token=${META_PAGE_TOKEN}" \
    | jq 'del(.[] | .access_token?, .token?) | .page_token_present = true' \
    > "${OUT}/meta_page_subscribed_apps.json"
log "Saved: ${OUT}/meta_page_subscribed_apps.json"

# --- 4. prev snapshot との diff ---
PREV=$(ls -td "${SNAPSHOT_ROOT}"/*/ 2>/dev/null | grep -v "^${OUT}/$" | head -1 || echo "")
if [[ -n "$PREV" && -f "${PREV}meta_app.json" ]]; then
    log "Diffing against prev snapshot: ${PREV}"
    DIFF_OUT=""
    if ! diff <(jq -S . "${PREV}meta_app.json") <(jq -S . "${OUT}/meta_app.json") > /dev/null 2>&1; then
        DIFF_OUT=$(diff <(jq -S . "${PREV}meta_app.json") <(jq -S . "${OUT}/meta_app.json") || true)
        log "DRIFT DETECTED in meta_app.json:"
        echo "$DIFF_OUT" >&2
        echo "$DIFF_OUT" > "${OUT}/meta_app.diff"
    fi
    if ! diff <(jq -S . "${PREV}meta_subscriptions.json") <(jq -S . "${OUT}/meta_subscriptions.json") > /dev/null 2>&1; then
        DIFF_OUT=$(diff <(jq -S . "${PREV}meta_subscriptions.json") <(jq -S . "${OUT}/meta_subscriptions.json") || true)
        log "DRIFT DETECTED in meta_subscriptions.json:"
        echo "$DIFF_OUT" >&2
        echo "$DIFF_OUT" > "${OUT}/meta_subscriptions.diff"
    fi
else
    log "No previous snapshot found — this is the baseline"
fi

log "Snapshot complete: ${OUT}"
echo "DONE: ${OUT}"
