#!/usr/bin/env bash
# =============================================================================
# codex-evaluator.sh — Codex を Evaluator として非対話実行するラッパー
# =============================================================================
# 使い方:
#   bash scripts/codex-evaluator.sh "..."   # スプリント評価
#   printf '%s\n' "..." | bash scripts/codex-evaluator.sh
# =============================================================================

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
exec bash "$REPO_ROOT/scripts/codex-exec.sh" evaluator "$@"
