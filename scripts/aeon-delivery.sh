#!/usr/bin/env bash
# =============================================================================
# aeon-delivery.sh — Claude Code から AEON の delivery flow を同一ターミナルで進める入口
# =============================================================================
# 使い方:
#   bash scripts/aeon-delivery.sh "..."                     # default: generator exec
#   bash scripts/aeon-delivery.sh --generator=auto "..."
#   bash scripts/aeon-delivery.sh --generator=interactive "..."
#   bash scripts/aeon-delivery.sh --smoke "..."              # no-op smoke validation
#   printf '%s\n' "..." | bash scripts/aeon-delivery.sh
# =============================================================================

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
LOG_FILE="/tmp/aeon-delivery-$(date +%Y%m%d-%H%M%S).log"
GENERATOR_MODE="exec"
SMOKE_MODE="0"

usage() {
  echo "❌ 使用法: bash scripts/aeon-delivery.sh [--generator=exec|auto|interactive] [--smoke] [prompt...]"
  exit 1
}

POSITIONAL=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --generator=exec|--generator-exec)
      GENERATOR_MODE="exec"
      shift
      ;;
    --generator=auto|--generator-auto)
      GENERATOR_MODE="auto"
      shift
      ;;
    --generator=interactive|--generator-interactive)
      GENERATOR_MODE="interactive"
      shift
      ;;
    --smoke)
      SMOKE_MODE="1"
      shift
      ;;
    --help|-h)
      usage
      ;;
    --)
      shift
      while [[ $# -gt 0 ]]; do
        POSITIONAL+=("$1")
        shift
      done
      ;;
    *)
      POSITIONAL+=("$1")
      shift
      ;;
  esac
done

if [[ ${#POSITIONAL[@]} -gt 0 ]]; then
  USER_PROMPT="${POSITIONAL[*]}"
else
  if [[ -t 0 ]]; then
    usage
  fi
  USER_PROMPT="$(cat)"
fi

exec > >(tee -a "$LOG_FILE") 2>&1

echo "🤖 AEON delivery flow started"
echo "   log    : $LOG_FILE"
echo "   mode   : $GENERATOR_MODE"
echo "   smoke  : $SMOKE_MODE"
echo ""

bash "$REPO_ROOT/scripts/validate-worktree-start.sh"

run_stage() {
  local role="$1"
  shift
  echo "==> running ${role}"
  bash "$REPO_ROOT/scripts/aeon-dispatch.sh" "$role" "$@"
  echo
}

if [[ "$SMOKE_MODE" == "1" ]]; then
  SMOKE_RESEARCH="Smoke validation only. Return a minimal evidence package confirming the role started. Do not expand scope, do not search beyond the referenced AEON docs, and do not propose implementation."
  SMOKE_PLANNER="Smoke validation only. Return a minimal planner package confirming the pipeline contract. Do not expand scope, do not propose implementation details, and do not request new evidence."
  SMOKE_ARCHITECT="Smoke validation only. Return a minimal architect verdict confirming the route is implementation-ready. Do not implement or expand scope."
  SMOKE_GENERATOR="Smoke validation only. Confirm the generator wrapper starts and produces a no-op report. Do not modify files, do not commit, and do not open PRs."
  SMOKE_EVALUATOR="Smoke validation only. Return a minimal evaluation package confirming the evaluator role starts. Do not run Playwright and do not modify files."
  SMOKE_REVIEWER="Smoke validation only. Return a minimal review package confirming the reviewer role starts. Do not modify files and do not open PRs."
  run_stage research "$SMOKE_RESEARCH"
  run_stage planner "$SMOKE_PLANNER"
  run_stage architect "$SMOKE_ARCHITECT"
else
  run_stage research "$USER_PROMPT"
  run_stage planner "$USER_PROMPT"
  run_stage architect "$USER_PROMPT"
fi

case "$GENERATOR_MODE" in
  exec)
    if [[ "$SMOKE_MODE" == "1" ]]; then
      run_stage generator --smoke
    else
      run_stage generator --exec
    fi
    ;;
  auto)
    if [[ "$SMOKE_MODE" == "1" ]]; then
      run_stage generator --smoke
    else
      run_stage generator --auto
    fi
    ;;
  interactive)
    if [[ "$SMOKE_MODE" == "1" ]]; then
      run_stage generator --smoke
    else
      run_stage generator
    fi
    ;;
esac

if [[ "$SMOKE_MODE" == "1" ]]; then
  run_stage evaluator "$SMOKE_EVALUATOR"
  run_stage reviewer "$SMOKE_REVIEWER"
else
  run_stage evaluator "$USER_PROMPT"
  run_stage reviewer "$USER_PROMPT"
fi

echo "⚠️  Delivery flow reached Reviewer. If the PR is approved, merge it manually with merge-commit policy."
echo "   Use: bash scripts/aeon-release.sh [PR番号]"
echo "   This run is logged at: $LOG_FILE"
