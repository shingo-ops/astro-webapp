#!/usr/bin/env bash
# =============================================================================
# aeon-dispatch.sh — Claude Code から AEON エージェントを同一ターミナルで起動する入口
# =============================================================================
# 使い方:
#   bash scripts/aeon-dispatch.sh generator [--auto|--exec|--smoke] # Generator は既存 wrapper を利用
#   bash scripts/aeon-dispatch.sh research "..."    # Codex Research
#   bash scripts/aeon-dispatch.sh planner "..."     # Codex Planner
#   bash scripts/aeon-dispatch.sh architect "..."   # Codex Architect
#   bash scripts/aeon-dispatch.sh reviewer "..."    # Codex Reviewer
#   bash scripts/aeon-dispatch.sh evaluator "..."   # Codex Evaluator
#   printf '%s\n' "..." | bash scripts/aeon-dispatch.sh research
# =============================================================================

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"

if [[ $# -lt 1 ]]; then
  echo "❌ 使用法: bash scripts/aeon-dispatch.sh <generator|research|planner|architect|reviewer|evaluator> [prompt...]"
  exit 1
fi

ROLE="$1"
shift || true

case "$ROLE" in
  generator)
    if [[ "${1:-}" == "--auto" ]]; then
      exec bash "$REPO_ROOT/scripts/codex-generator.sh" --auto
    elif [[ "${1:-}" == "--exec" ]]; then
      exec bash "$REPO_ROOT/scripts/codex-generator.sh" --exec
    elif [[ "${1:-}" == "--smoke" ]]; then
      exec bash "$REPO_ROOT/scripts/codex-generator.sh" --smoke
    elif [[ $# -gt 0 ]]; then
      echo "⚠️  generator は prompt を受け取りません。引数は無視します。"
      exec bash "$REPO_ROOT/scripts/codex-generator.sh"
    fi
    exec bash "$REPO_ROOT/scripts/codex-generator.sh"
    ;;
  research)
    if [[ $# -gt 0 ]]; then
      USER_PROMPT="$*"
    else
      if [[ -t 0 ]]; then
        echo "❌ プロンプトを指定してください"
        exit 1
      fi
      USER_PROMPT="$(cat)"
    fi
    exec bash "$REPO_ROOT/scripts/codex-research.sh" "$USER_PROMPT"
    ;;
  planner)
    if [[ $# -gt 0 ]]; then
      USER_PROMPT="$*"
    else
      if [[ -t 0 ]]; then
        echo "❌ プロンプトを指定してください"
        exit 1
      fi
      USER_PROMPT="$(cat)"
    fi
    exec bash "$REPO_ROOT/scripts/codex-planner.sh" "$USER_PROMPT"
    ;;
  architect)
    if [[ $# -gt 0 ]]; then
      USER_PROMPT="$*"
    else
      if [[ -t 0 ]]; then
        echo "❌ プロンプトを指定してください"
        exit 1
      fi
      USER_PROMPT="$(cat)"
    fi
    exec bash "$REPO_ROOT/scripts/codex-architect.sh" "$USER_PROMPT"
    ;;
  reviewer)
    if [[ $# -gt 0 ]]; then
      USER_PROMPT="$*"
    else
      if [[ -t 0 ]]; then
        echo "❌ プロンプトを指定してください"
        exit 1
      fi
      USER_PROMPT="$(cat)"
    fi
    exec bash "$REPO_ROOT/scripts/codex-reviewer.sh" "$USER_PROMPT"
    ;;
  evaluator)
    if [[ $# -gt 0 ]]; then
      USER_PROMPT="$*"
    else
      if [[ -t 0 ]]; then
        echo "❌ プロンプトを指定してください"
        exit 1
      fi
      USER_PROMPT="$(cat)"
    fi
    exec bash "$REPO_ROOT/scripts/codex-evaluator.sh" "$USER_PROMPT"
    ;;
  *)
    echo "❌ 未対応の role: $ROLE"
    echo "   対応 role: generator / research / planner / architect / reviewer / evaluator"
    exit 1
    ;;
esac
