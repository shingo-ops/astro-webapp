#!/bin/bash
# validate-worktree-start.sh — 作業開始前のworktree強制チェック
#
# 目的: エージェントがメインリポジトリで作業を開始するのを防ぐ
#       個室（worktree）以外での作業開始をブロックし、ブランチ変更干渉を根本から排除
#
# 呼び出し元:
#   - .claude/agents/generator.md の Step 0（実装開始前）
#   - .claude/agents/evaluator.md の Step 0（評価開始前）
#   - .claude/agents/reviewer.md の Step 0（レビュー開始前）
#
# validate-pr-ownership.sh との違い:
#   - validate-pr-ownership.sh = 終わり（push/PR作成前）のチェック
#   - validate-worktree-start.sh = 始まり（作業開始前）のチェック
#
# 参考: docs/PARALLEL_TERMINAL_GUIDE.md

set -e

# CI環境はスキップ（GitHub Actions は専用環境で実行）
if [ -n "${GITHUB_ACTIONS}" ]; then
  exit 0
fi

ACTUAL_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"
CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null)"

# main / develop / hotfix は worktree 不要（読み取り・確認作業のため）
case "${CURRENT_BRANCH}" in
  main|develop|master)
    exit 0
    ;;
esac

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# チェック: ~/worktrees/ 配下かどうか
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# メインリポジトリで feature ブランチ作業中 =
# 他エージェントの git checkout でブランチが変わるリスクがある状態

case "${ACTUAL_ROOT}" in
  "${HOME}"/worktrees/*) ;;  # OK: 個室（worktree）内で作業している
  *)
    echo ""
    echo "🚫 作業開始を中断しました: worktree（個室）の外で作業しようとしています。"
    echo ""
    echo "   現在のディレクトリ: ${ACTUAL_ROOT}"
    echo "   現在のブランチ    : ${CURRENT_BRANCH}"
    echo ""
    echo "   このまま作業を続けると、別のエージェントが git checkout を実行したとき"
    echo "   あなたのブランチが変わってしまう可能性があります。"
    echo ""
    echo "   正しい手順:"
    echo "   1. bash scripts/new-worktree.sh ${CURRENT_BRANCH} --claude"
    echo "   2. 作成された個室ディレクトリで作業してください"
    echo "      ~/worktrees/salesanchor/$(echo "${CURRENT_BRANCH}" | tr '/' '-')/"
    echo ""
    exit 1
    ;;
esac

echo "✅ worktreeチェック通過: ${CURRENT_BRANCH} @ ${ACTUAL_ROOT}"
exit 0
