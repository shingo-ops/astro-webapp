#!/usr/bin/env bash
# =============================================================================
# ADR-035: External State Verification — L2 Smoke: Discord Webhooks
#
# 目的:
#   Discord Webhook の疎通テスト。
#   --dry-run / --sandbox / --live の 3 mode に対応。
#
# Mode:
#   --dry-run    設定だけ読んで表示、実行しない
#   --sandbox    (default) Webhook URL に GET リクエストで疎通確認（メッセージ送信なし）
#   --live       本番 channel に smoke test メッセージを送信。PO_LIVE_OK=yes 必須
#
# 必須環境変数:
#   DISCORD_WEBHOOK_PR
#   DISCORD_WEBHOOK_PLAN_REVIEW
#   DISCORD_WEBHOOK_OWNER_PING
#
# --live mode 追加必須:
#   PO_LIVE_OK=yes
#
# 使い方:
#   bash scripts/smoke/external-discord.sh [--dry-run|--sandbox|--live]
#
# 関連:
#   docs/adr/ADR-035-external-state-verification.md
#   scripts/snapshot/discord.sh
#   scripts/notify/discord-owner-ping.sh
# =============================================================================
set -euo pipefail

MODE="${1:---sandbox}"

log() {
    echo "[smoke/discord] $(date -u +%Y-%m-%dT%H:%M:%SZ) $*" >&2
}

require_env() {
    local var="$1"
    if [[ -z "${!var:-}" ]]; then
        log "ERROR: required env var '${var}' is not set"
        exit 1
    fi
}

check_webhook_reachable() {
    local name="$1"
    local url="$2"
    # GET リクエストで webhook metadata 取得（送信なし）
    local status
    status=$(curl -fsS -o /dev/null -w "%{http_code}" \
        --max-time 10 \
        "$url" 2>/dev/null || echo "000")
    log "Webhook ${name}: HTTP ${status}"
    echo "$status"
}

WEBHOOKS=(
    "DISCORD_WEBHOOK_PR"
    "DISCORD_WEBHOOK_PLAN_REVIEW"
    "DISCORD_WEBHOOK_OWNER_PING"
)

case "$MODE" in
  --dry-run)
    log "MODE: dry-run"
    for wh in "${WEBHOOKS[@]}"; do
        val="${!wh:-}"
        if [[ -n "$val" ]]; then
            log "${wh}=(set, masked)"
        else
            log "${wh}=(not set)"
        fi
    done
    log "dry-run: no API calls made"
    echo "PASS: dry-run complete"
    ;;

  --sandbox)
    # Phase 0: Discord sandbox channel 未整備のため dry-run 相当で動作 (Production webhook を叩かない)
    echo "WARN: sandbox channel は未整備のため dry-run 動作（ADR-035 Scope OUT、Production webhook を叩かない）" >&2
    log "MODE: sandbox (dry-run fallback — Discord sandbox channel not yet provisioned)"
    for wh in "${WEBHOOKS[@]}"; do
        val="${!wh:-}"
        if [[ -n "$val" ]]; then
            log "${wh}=(set, masked)"
        else
            log "${wh}=(not set)"
        fi
    done
    log "sandbox: no API calls made (scaffold only)"
    echo "PASS: sandbox scaffold (dry-run equivalent)"
    ;;

  --live)
    if [[ "${PO_LIVE_OK:-}" != "yes" ]]; then
        log "ERROR: live mode requires PO_LIVE_OK=yes"
        exit 1
    fi
    log "MODE: live"
    require_env DISCORD_WEBHOOK_OWNER_PING

    SMOKE_MSG="[ADR-035 smoke/live] Discord webhook 疎通テスト $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    PAYLOAD=$(jq -nc --arg content "$SMOKE_MSG" '{content: $content}')

    log "Sending smoke message to DISCORD_WEBHOOK_OWNER_PING..."
    STATUS=$(curl -fsS -o /dev/null -w "%{http_code}" \
        -X POST -H "Content-Type: application/json" \
        -d "$PAYLOAD" \
        "$DISCORD_WEBHOOK_OWNER_PING" 2>/dev/null || echo "000")
    log "DISCORD_WEBHOOK_OWNER_PING send status: ${STATUS}"

    if [[ "$STATUS" != "204" && "$STATUS" != "200" ]]; then
        log "ERROR: Discord message send failed (status=${STATUS})"
        exit 1
    fi
    echo "PASS: live smoke OK (status=${STATUS})"
    ;;

  *)
    log "ERROR: unknown mode '${MODE}'. Use --dry-run, --sandbox, or --live"
    exit 1
    ;;
esac
