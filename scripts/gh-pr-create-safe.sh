#!/bin/bash
# gh-pr-create-safe.sh — --base ガード付き PR 作成
#
# 目的: gh pr create の --base 指定漏れによる main への誤マージを防ぐ
#       - --base 未指定時は develop を自動付与
#       - --base main かつ head が develop/hotfix/* 以外 → ハードブロック
#
# 使用方法: bash scripts/gh-pr-create-safe.sh [gh pr create オプション...]
#           例: bash scripts/gh-pr-create-safe.sh --title "..." --body "..."
#
# 呼び出し元:
#   - ~/.claude/agents/generator.md（gh pr create の代わりに必須）
#   - ~/.claude/agents/manager.md（同上）
#
# 参考: scripts/gh-pr-merge-safe.sh（同パターン）
#       docs/adr/ADR-074-worktree-agent-enforcement.md

set -e

# CI環境はスキップ（GitHub Actions は自分でベースを管理する）
if [ -n "${GITHUB_ACTIONS}" ]; then
  gh pr create "$@"
  exit $?
fi

# ── 引数パース: --base と --head の値を抽出 ────────────────────────────────
BASE_VALUE=""
HEAD_VALUE=""
i=1
while [ $i -le $# ]; do
  arg="${!i}"
  case "$arg" in
    --base)
      i=$((i + 1))
      BASE_VALUE="${!i}"
      ;;
    --base=*)
      BASE_VALUE="${arg#--base=}"
      ;;
    --head)
      i=$((i + 1))
      HEAD_VALUE="${!i}"
      ;;
    --head=*)
      HEAD_VALUE="${arg#--head=}"
      ;;
  esac
  i=$((i + 1))
done

# ── --base 未指定 → develop を自動付与 ───────────────────────────────────
if [ -z "$BASE_VALUE" ]; then
  echo "ℹ️  --base 未指定のため develop を自動設定します"
  echo "   gh pr create --base develop $*"
  echo ""
  gh pr create --base develop "$@"
  exit $?
fi

# ── --base main のガード ──────────────────────────────────────────────────
if [ "$BASE_VALUE" = "main" ]; then
  # head ブランチを特定（--head 引数 → 現在ブランチ の順）
  ACTUAL_HEAD="${HEAD_VALUE:-$(git rev-parse --abbrev-ref HEAD 2>/dev/null)}"

  # develop または hotfix/* → リリース/ホットフィックスPRとして許可
  if [ "$ACTUAL_HEAD" = "develop" ] || echo "$ACTUAL_HEAD" | grep -qE '^hotfix/'; then
    echo "✅ ${ACTUAL_HEAD} → main のリリース/ホットフィックスPR: 許可"
    echo ""
    gh pr create "$@"
    exit $?
  fi

  # それ以外はハードブロック
  echo ""
  echo "🚫 gh-pr-create-safe: --base main へのPR作成を中断しました"
  echo ""
  echo "   head : ${ACTUAL_HEAD}"
  echo "   base : main"
  echo ""
  echo "   main を向く PR は develop または hotfix/* からのみ許可されています。"
  echo "   通常の機能開発は --base develop（または省略）を使用してください。"
  echo ""
  echo "   修正方法: bash scripts/gh-pr-create-safe.sh --title \"...\" ..."
  echo "             （--base 省略で develop が自動設定されます）"
  echo ""
  exit 1
fi

# ── develop 等その他のベース → そのまま通過 ───────────────────────────────
gh pr create "$@"
