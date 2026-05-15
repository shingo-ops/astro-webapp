#!/usr/bin/env bash
# =============================================================================
# ADR-035: External State Verification — L3 Snapshot: Cloudflare DNS
#
# 目的:
#   Cloudflare の DNS records / WAF ルール数を JSON に保存し、
#   前回スナップショットとの diff で drift を検出する。
#
# SECRET SCRUB ルール（MANDATORY）:
#   - raw API token は snapshot json に書かない
#   - DNS record の content（IP / CNAME 先）は sha256 前 8 文字のみ記録
#   - WAF ルールの action / expression は保存（機密でない）
#   Reviewer は merge 前に本スクリプトの scrub ロジックを目視確認すること。
#
# 必須環境変数:
#   CLOUDFLARE_API_TOKEN   Cloudflare API Token (read-only)
#
# 任意環境変数:
#   CF_ZONE_NAME   対象ゾーン (default: salesanchor.jp)
#   SNAPSHOT_DIR   出力ルートディレクトリ (default: external-state-snapshots)
#   SPRINT_TAG     スナップショットのディレクトリ名サフィックス (default: manual)
#
# 使い方:
#   bash scripts/snapshot/cloudflare.sh
#
# 出力:
#   ${SNAPSHOT_DIR}/${DATE}-${SPRINT_TAG}/cloudflare_dns_records.json
#   ${SNAPSHOT_DIR}/${DATE}-${SPRINT_TAG}/cloudflare_waf_rules.json
#
# 関連:
#   docs/adr/ADR-035-external-state-verification.md
#   scripts/smoke/external-cloudflare.sh
#   docs/runbooks/B-06_cloudflare_setup.md
# =============================================================================
set -euo pipefail

SNAPSHOT_ROOT="${SNAPSHOT_DIR:-external-state-snapshots}"
SPRINT_TAG="${SPRINT_TAG:-manual}"
DATE_TAG="$(date +%Y-%m-%d)"
OUT="${SNAPSHOT_ROOT}/${DATE_TAG}-${SPRINT_TAG}"
CF_API="https://api.cloudflare.com/client/v4"
ZONE_NAME="${CF_ZONE_NAME:-salesanchor.jp}"

log() {
    echo "[snapshot/cloudflare] $(date -u +%Y-%m-%dT%H:%M:%SZ) $*" >&2
}

require_env() {
    local var="$1"
    if [[ -z "${!var:-}" ]]; then
        log "ERROR: required env var '${var}' is not set"
        exit 1
    fi
}

require_env CLOUDFLARE_API_TOKEN

cf_api() {
    local path="$1"
    curl -fsS \
        -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" \
        -H "Content-Type: application/json" \
        "${CF_API}${path}"
}

mkdir -p "$OUT"
log "Output dir: ${OUT}"

# --- Zone ID 取得 ---
log "Looking up zone ${ZONE_NAME}..."
ZONES_RESP=$(cf_api "/zones?name=${ZONE_NAME}") || { log "ERROR: zones API failed"; exit 1; }
ZONE_ID=$(echo "$ZONES_RESP" | jq -r '.result[0].id // empty')
if [[ -z "$ZONE_ID" ]]; then
    log "ERROR: zone '${ZONE_NAME}' not found"
    exit 1
fi
log "Zone ID: ${ZONE_ID}"

# --- 1. DNS records（content は bash 側で sha256 計算して scrub） ---
log "Fetching DNS records..."
ZONE_ID_SHA=$(printf '%s' "$ZONE_ID" | sha256sum | head -c 8)
DNS_RECORDS_RAW=$(cf_api "/zones/${ZONE_ID}/dns_records?per_page=100")
DNS_RECORDS_SCRUBBED=$(echo "$DNS_RECORDS_RAW" \
    | jq -c '.result[]' \
    | while IFS= read -r rec; do
        content=$(echo "$rec" | jq -r '.content')
        content_sha=$(printf '%s' "$content" | sha256sum | head -c 8)
        echo "$rec" | jq --arg sha "$content_sha" '{
          name, type, ttl, proxied,
          content_sha256: ($sha + "...")
        }'
      done | jq -s '.')
echo "$DNS_RECORDS_SCRUBBED" \
    | jq --arg zone_name "$ZONE_NAME" --arg zone_sha "$ZONE_ID_SHA" '{
        zone_name: $zone_name,
        zone_id_sha256: ($zone_sha + "..."),
        count: length,
        records: .
      }' \
    > "${OUT}/cloudflare_dns_records.json"
log "Saved: ${OUT}/cloudflare_dns_records.json"

# --- 2. WAF ルール数 ---
log "Fetching WAF custom rules..."
WAF_RESP=$(cf_api "/zones/${ZONE_ID}/firewall/rules?per_page=100" 2>/dev/null \
    || echo '{"result":[],"result_info":{"total_count":0}}')
echo "$WAF_RESP" \
    | jq '{
        zone_name: "'"$ZONE_NAME"'",
        total_count: (.result_info.total_count // (.result | length)),
        rules: [.result[] | {description: .description, action: .action, paused: .paused}]
      }' \
    > "${OUT}/cloudflare_waf_rules.json"
log "Saved: ${OUT}/cloudflare_waf_rules.json"

# --- 3. prev snapshot との diff ---
PREV=$(ls -td "${SNAPSHOT_ROOT}"/*/ 2>/dev/null | grep -v "^${OUT}/$" | head -1 || echo "")
if [[ -n "$PREV" && -f "${PREV}cloudflare_dns_records.json" ]]; then
    log "Diffing against prev snapshot: ${PREV}"
    for fname in cloudflare_dns_records.json cloudflare_waf_rules.json; do
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
