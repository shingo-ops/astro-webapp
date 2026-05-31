#!/bin/bash
# check-hooks.sh — Claude Code フックスクリプトの実行権限を確認する
#
# 使い方:
#   bash scripts/check-hooks.sh          # チェックのみ
#   bash scripts/check-hooks.sh --fix    # 問題があれば chmod +x で自動修正
#
# CI / オンボーディング・定期メンテで実行する。
# exit 0: 全フック正常
# exit 1: 不足・権限なしのフックあり

set -e

HOOKS_DIR="${HOME}/.claude/scripts"
FIX_MODE=0
[ "${1}" = "--fix" ] && FIX_MODE=1

REQUIRED_HOOKS=(
  "worktree-only-guard.sh"
  "worktree-access-guard.sh"
  "agent-danger-hook.sh"
  "agent-start-hook.sh"
  "agent-stop-hook.sh"
  "gh-scope-guard.sh"
)

FAIL=0

echo "=== Claude Code フック権限チェック ==="
echo "対象ディレクトリ: ${HOOKS_DIR}"
echo ""

for hook in "${REQUIRED_HOOKS[@]}"; do
  path="${HOOKS_DIR}/${hook}"
  if [ ! -f "$path" ]; then
    echo "❌ MISSING    : $path"
    FAIL=1
  elif [ ! -x "$path" ]; then
    if [ "$FIX_MODE" -eq 1 ]; then
      chmod +x "$path"
      echo "🔧 FIXED      : $path  (chmod +x 適用)"
    else
      echo "❌ NOT EXEC   : $path  → chmod +x が必要"
      FAIL=1
    fi
  else
    echo "✅ OK         : $path"
  fi
done

echo ""

if [ "$FAIL" -eq 1 ]; then
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "問題が見つかりました。以下で修正してください:"
  echo "  bash scripts/check-hooks.sh --fix"
  echo "  または: chmod +x ~/.claude/scripts/*.sh"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  exit 1
fi

echo "全フック正常です。"
