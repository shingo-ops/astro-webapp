#!/usr/bin/env bash
# =============================================================================
# codex-reviewer.sh — Codex を Reviewer として非対話実行するラッパー
# =============================================================================
# 使い方:
#   bash scripts/codex-reviewer.sh "..."   # Sprint review / external PR review
#   printf '%s\n' "..." | bash scripts/codex-reviewer.sh
# =============================================================================

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
exec bash "$REPO_ROOT/scripts/codex-exec.sh" reviewer "$@"
