#!/usr/bin/env bash
# =============================================================================
# claude-dispatch.sh — Codex から Claude Code エージェントを呼び出す入口
# =============================================================================
# 使い方:
#   bash scripts/claude-dispatch.sh reviewer "プロンプト"
#   bash scripts/claude-dispatch.sh evaluator "プロンプト"
#   bash scripts/claude-dispatch.sh governance "プロンプト"
#
# Codex のシェルから呼べる。claude -p（非対話モード）で実行する。
#
# ⚠️  サンドボックス要件:
#   Codex の read-only / workspace-write サンドボックスは macOS Seatbelt で
#   Claude Code の OAuth 認証（Securityフレームワーク）をブロックするため動作しない。
#   Codex から呼ぶ場合は必ず danger-full-access サンドボックスを使うこと:
#     codex exec --sandbox danger-full-access "bash scripts/claude-dispatch.sh reviewer '...'"
# =============================================================================

set -euo pipefail

CLAUDE_BIN="$(which claude 2>/dev/null || echo '')"

if [[ $# -lt 1 ]]; then
  echo "❌ 使用法: bash scripts/claude-dispatch.sh <role> [prompt...]"
  echo "   対応 role: reviewer / evaluator / governance / research / planner / architect"
  exit 1
fi

ROLE="$1"
shift || true

if [[ -z "$CLAUDE_BIN" ]]; then
  echo "❌ claude CLI が見つかりません"
  echo "   Claude Code がインストールされているか確認してください"
  exit 1
fi

# ロール別ツール制限
case "$ROLE" in
  reviewer)
    TOOLS="Read,Grep,Glob,Bash"
    ;;
  evaluator)
    TOOLS="Read,Grep,Glob,Bash"
    ;;
  governance)
    TOOLS="Read,Grep,Glob,Bash"
    ;;
  research)
    TOOLS="Read,Grep,Glob,WebFetch,WebSearch"
    ;;
  planner)
    TOOLS="Read,Grep,Glob"
    ;;
  architect)
    TOOLS="Read,Grep,Glob"
    ;;
  *)
    echo "❌ 未対応の role: $ROLE"
    echo "   対応 role: reviewer / evaluator / governance / research / planner / architect"
    exit 1
    ;;
esac

if [[ $# -gt 0 ]]; then
  USER_PROMPT="$*"
else
  if [[ -t 0 ]]; then
    echo "❌ プロンプトを指定してください"
    exit 1
  fi
  USER_PROMPT="$(cat)"
fi

echo "🤖 Claude Code ${ROLE} 起動中..."
echo "   プロンプト: ${USER_PROMPT}"
echo ""

# --setting-sources "project" でユーザーレベルのフック（worktree-only-guard.sh 等）を除外する
# → Codex サンドボックスのような非 TTY 環境でのハングを防ぐ
"$CLAUDE_BIN" -p "$USER_PROMPT" \
  --agent "$ROLE" \
  --allowedTools "$TOOLS" \
  --no-session-persistence \
  --setting-sources "project" \
  --output-format text \
  < /dev/null
