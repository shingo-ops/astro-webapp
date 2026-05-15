#!/usr/bin/env bash
# =============================================================================
# ADR-035: External State Verification — L5 Owner Ping: Discord
#
# 目的:
#   外部システム drift 検出時やスナップショット完了時に、人間（PO）向けの
#   action items を Discord #owner-ping channel に通知する。
#
# 必須環境変数:
#   DISCORD_WEBHOOK_OWNER_PING   Discord webhook URL for #owner-ping channel
#
# 引数:
#   $1   通知メッセージ本文（markdown 形式）
#
# 使い方:
#   bash scripts/notify/discord-owner-ping.sh "## External system action items
#   - [ ] Meta: subscription drift detected — please re-subscribe via Meta dashboard
#   - [ ] GitHub: PIPELINE_PAT rotation due 2026-08-05"
#
# 関連:
#   docs/adr/ADR-035-external-state-verification.md
#   .github/workflows/external-state-snapshot.yml
#   docs/runbooks/external-state-operations.md
# =============================================================================
set -euo pipefail

log() {
    echo "[notify/discord-owner-ping] $(date -u +%Y-%m-%dT%H:%M:%SZ) $*" >&2
}

if [[ -z "${DISCORD_WEBHOOK_OWNER_PING:-}" ]]; then
    log "ERROR: DISCORD_WEBHOOK_OWNER_PING is not set"
    exit 1
fi

if [[ $# -lt 1 || -z "$1" ]]; then
    log "ERROR: message body is required as first argument"
    echo "Usage: $0 <message>" >&2
    exit 1
fi

BODY="$1"

# Discord message character limit: 2000
if [[ ${#BODY} -gt 1900 ]]; then
    log "WARN: message body exceeds 1900 chars (${#BODY}), truncating..."
    BODY="${BODY:0:1900}..."
fi

PAYLOAD=$(jq -nc --arg content "$BODY" '{content: $content}')

log "Sending owner ping to Discord..."
HTTP_STATUS=$(curl -fsS -o /dev/null -w "%{http_code}" \
    -X POST \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD" \
    "$DISCORD_WEBHOOK_OWNER_PING" 2>/dev/null || echo "000")

log "Discord response HTTP status: ${HTTP_STATUS}"

if [[ "$HTTP_STATUS" != "204" && "$HTTP_STATUS" != "200" ]]; then
    log "ERROR: Discord webhook returned ${HTTP_STATUS}"
    exit 1
fi

log "Owner ping sent successfully"
echo "DONE: owner ping sent (status=${HTTP_STATUS})"
