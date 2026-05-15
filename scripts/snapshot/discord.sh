#!/usr/bin/env bash
# =============================================================================
# ADR-035: External State Verification — L3 Snapshot: Discord Webhooks
#
# 目的:
#   Discord Webhook の metadata（channel_id / guild_id）を JSON に保存し、
#   前回スナップショットとの diff で drift を検出する。
#
# SECRET SCRUB ルール（MANDATORY）:
#   - Webhook URL（token 含む）は snapshot json に書かない
#   - channel_id / guild_id / name は保存対象（機密でない）
#   - token フィールドは del() で削除
#   Reviewer は merge 前に本スクリプトの scrub ロジックを目視確認すること。
#
# 必須環境変数:
#   DISCORD_WEBHOOK_PR
#   DISCORD_WEBHOOK_PLAN_REVIEW
#   DISCORD_WEBHOOK_OWNER_PING
#
# 任意環境変数:
#   SNAPSHOT_DIR   出力ルートディレクトリ (default: external-state-snapshots)
#   SPRINT_TAG     スナップショットのディレクトリ名サフィックス (default: manual)
#
# 使い方:
#   bash scripts/snapshot/discord.sh
#
# 出力:
#   ${SNAPSHOT_DIR}/${DATE}-${SPRINT_TAG}/discord_webhooks.json
#
# 関連:
#   docs/adr/ADR-035-external-state-verification.md
#   scripts/smoke/external-discord.sh
#   scripts/notify/discord-owner-ping.sh
# =============================================================================
set -euo pipefail

SNAPSHOT_ROOT="${SNAPSHOT_DIR:-external-state-snapshots}"
SPRINT_TAG="${SPRINT_TAG:-manual}"
DATE_TAG="$(date +%Y-%m-%d)"
OUT="${SNAPSHOT_ROOT}/${DATE_TAG}-${SPRINT_TAG}"

log() {
    echo "[snapshot/discord] $(date -u +%Y-%m-%dT%H:%M:%SZ) $*" >&2
}

require_env() {
    local var="$1"
    if [[ -z "${!var:-}" ]]; then
        log "ERROR: required env var '${var}' is not set"
        exit 1
    fi
}

mkdir -p "$OUT"
log "Output dir: ${OUT}"

fetch_webhook_metadata() {
    local name="$1"
    local url="$2"
    # Discord Webhook GET で metadata 取得（token は含まれるが del で削除）
    local resp
    resp=$(curl -fsS --max-time 10 "$url" 2>/dev/null \
        || echo '{"error":"fetch_failed"}')
    echo "$resp" | jq --arg name "$name" '{
        webhook_name: $name,
        id: .id,
        name: .name,
        channel_id: .channel_id,
        guild_id: .guild_id,
        type: .type,
        token_present: (if .token then true else false end),
        error: .error
      } | del(.token)'
}

log "Fetching Discord webhook metadata..."
WEBHOOKS_JSON="[]"

for wh_name in DISCORD_WEBHOOK_PR DISCORD_WEBHOOK_PLAN_REVIEW DISCORD_WEBHOOK_OWNER_PING; do
    url="${!wh_name:-}"
    if [[ -z "$url" ]]; then
        log "WARN: ${wh_name} not set — skipping"
        META=$(jq -n --arg name "$wh_name" '{"webhook_name": $name, "error": "env_not_set"}')
    else
        log "Fetching ${wh_name}..."
        META=$(fetch_webhook_metadata "$wh_name" "$url")
    fi
    WEBHOOKS_JSON=$(echo "$WEBHOOKS_JSON" | jq --argjson entry "$META" '. + [$entry]')
done

echo "$WEBHOOKS_JSON" | jq '{
    snapshot_at: "'"$(date -u +%Y-%m-%dT%H:%M:%SZ)"'",
    webhooks: .
  }' > "${OUT}/discord_webhooks.json"
log "Saved: ${OUT}/discord_webhooks.json"

# --- prev snapshot との diff ---
PREV=$(ls -td "${SNAPSHOT_ROOT}"/*/ 2>/dev/null | grep -v "^${OUT}/$" | head -1 || echo "")
if [[ -n "$PREV" && -f "${PREV}discord_webhooks.json" ]]; then
    log "Diffing against prev snapshot: ${PREV}"
    if ! diff <(jq -S . "${PREV}discord_webhooks.json") <(jq -S . "${OUT}/discord_webhooks.json") > /dev/null 2>&1; then
        DIFF_OUT=$(diff <(jq -S . "${PREV}discord_webhooks.json") <(jq -S . "${OUT}/discord_webhooks.json") || true)
        log "DRIFT DETECTED in discord_webhooks.json:"
        echo "$DIFF_OUT" >&2
        echo "$DIFF_OUT" > "${OUT}/discord_webhooks.diff"
    fi
else
    log "No previous snapshot found — this is the baseline"
fi

log "Snapshot complete: ${OUT}"
echo "DONE: ${OUT}"
