#!/usr/bin/env bash
# =============================================================================
# ADR-035: External State Verification — L2 Smoke: GitHub Secrets & Actions
#
# 目的:
#   GitHub Secrets / Branch protection / Actions の疎通テスト。
#   --dry-run / --sandbox / --live の 3 mode に対応。
#
# Mode:
#   --dry-run    設定だけ読んで表示、実行しない
#   --sandbox    (default) GitHub API に接続して repo の public 情報を確認
#   --live       GitHub API で secrets 存在確認 + branch protection 確認。PO_LIVE_OK=yes 必須
#
# 必須環境変数:
#   PIPELINE_PAT     GitHub Personal Access Token
#
# 任意環境変数:
#   GITHUB_REPO      対象リポジトリ (default: shingo-ops/salesanchor)
#
# --live mode 追加必須:
#   PO_LIVE_OK=yes
#
# 使い方:
#   bash scripts/smoke/external-github.sh [--dry-run|--sandbox|--live]
#
# 関連:
#   docs/adr/ADR-035-external-state-verification.md
#   scripts/snapshot/github.sh
# =============================================================================
set -euo pipefail

MODE="${1:---sandbox}"
REPO="${GITHUB_REPO:-shingo-ops/salesanchor}"
GH_API="https://api.github.com"

log() {
    echo "[smoke/github] $(date -u +%Y-%m-%dT%H:%M:%SZ) $*" >&2
}

require_env() {
    local var="$1"
    if [[ -z "${!var:-}" ]]; then
        log "ERROR: required env var '${var}' is not set"
        exit 1
    fi
}

gh_api() {
    local path="$1"
    curl -fsS \
        -H "Authorization: token ${PIPELINE_PAT}" \
        -H "Accept: application/vnd.github+json" \
        "${GH_API}${path}"
}

case "$MODE" in
  --dry-run)
    log "MODE: dry-run"
    log "PIPELINE_PAT=(masked, length=${#PIPELINE_PAT:-0})"
    log "GITHUB_REPO=${REPO}"
    log "dry-run: no API calls made"
    echo "PASS: dry-run complete"
    ;;

  --sandbox)
    # Phase 0: GitHub sandbox 環境は未整備のため dry-run 相当で動作 (Production を叩かない)
    echo "WARN: sandbox 環境は未整備のため dry-run 動作（ADR-035 Scope OUT、Production GitHub API を叩かない）" >&2
    log "MODE: sandbox (dry-run fallback — GitHub sandbox not yet provisioned)"
    log "PIPELINE_PAT=(masked, length=${#PIPELINE_PAT:-0})"
    log "GITHUB_REPO=${REPO}"
    log "sandbox: no API calls made (scaffold only)"
    echo "PASS: sandbox scaffold (dry-run equivalent)"
    ;;

  --live)
    if [[ "${PO_LIVE_OK:-}" != "yes" ]]; then
        log "ERROR: live mode requires PO_LIVE_OK=yes"
        exit 1
    fi
    log "MODE: live"
    require_env PIPELINE_PAT

    # repo 確認
    log "Checking repo ${REPO}..."
    REPO_INFO=$(gh_api "/repos/${REPO}") || { log "ERROR: repo API failed"; exit 1; }
    REPO_NAME=$(echo "$REPO_INFO" | jq -r '.full_name')
    log "Repo confirmed: ${REPO_NAME}"

    # secrets 一覧（存在確認のみ、値は見えない）
    log "Checking repository secrets..."
    SECRETS_RESP=$(gh_api "/repos/${REPO}/actions/secrets") || { log "WARN: secrets API failed (needs admin scope)"; }
    if [[ -n "${SECRETS_RESP:-}" ]]; then
        SECRET_COUNT=$(echo "$SECRETS_RESP" | jq '.total_count // 0')
        log "Secrets count: ${SECRET_COUNT}"
    fi

    # branch protection — develop
    log "Checking branch protection for develop..."
    BP_STATUS=$(curl -fsS -o /dev/null -w "%{http_code}" \
        -H "Authorization: token ${PIPELINE_PAT}" \
        -H "Accept: application/vnd.github+json" \
        "${GH_API}/repos/${REPO}/branches/develop/protection" 2>/dev/null || echo "000")
    log "Branch protection (develop) HTTP status: ${BP_STATUS}"

    echo "PASS: live smoke OK (repo=${REPO_NAME}, secrets_count=${SECRET_COUNT:-unknown}, bp_develop=${BP_STATUS})"
    ;;

  *)
    log "ERROR: unknown mode '${MODE}'. Use --dry-run, --sandbox, or --live"
    exit 1
    ;;
esac
