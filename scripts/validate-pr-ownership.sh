#!/bin/bash
# validate-pr-ownership.sh — PR作成・push前のオーナーシップ検証
#
# 目的: 並行エージェント開発で「自分の変更だけをPRに含める」を機械的に保証する
#       他エージェントの変更が混入したPRを物理的に防ぐ
#
# 呼び出し元:
#   - frontend/.husky/pre-push （git push 時に自動実行）
#   - ~/.claude/agents/generator.md の Step Final（gh pr create 前に手動実行）
#
# 参考: docs/PARALLEL_TERMINAL_GUIDE.md

set -e

# CI環境はスキップ（GitHub Actions は自分専用のブランチを自分で管理する）
if [ -n "${GITHUB_ACTIONS}" ]; then
  exit 0
fi

ACTUAL_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# チェック1: worktree 外での push を禁止
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 各エージェントは ~/worktrees/salesanchor/<branch>/ で作業する（PARALLEL_TERMINAL_GUIDE.md）
# メインリポジトリから push すると他エージェントの変更が混入する可能性がある

case "${ACTUAL_ROOT}" in
  "${HOME}"/worktrees/*) ;;  # OK: 個室（worktree）内で作業している
  *)
    echo ""
    echo "🚫 push を中断しました: worktree 外での作業は禁止されています。"
    echo ""
    echo "   現在のディレクトリ: ${ACTUAL_ROOT}"
    echo "   許可される場所   : ~/worktrees/salesanchor/<branch>/"
    echo ""
    echo "   正しい手順:"
    echo "   1. bash scripts/new-worktree.sh feature/morimoto/<トピック名>"
    echo "   2. cd ~/worktrees/salesanchor/feature-morimoto-<トピック名>"
    echo "   3. そこから作業・push してください"
    echo ""
    exit 1
    ;;
esac

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# チェック2: active-work.md にブランチが登録されているか（完全一致）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# new-worktree.sh が作成時に自動登録する（SSoT: .claude-pipeline/active-work.md）

# --git-common-dir でメインリポジトリを確実に取得（worktree list は順序不定）
GIT_COMMON_DIR="$(git rev-parse --git-common-dir 2>/dev/null)"
MAIN_REPO_ROOT="$(dirname "${GIT_COMMON_DIR}")"
ACTIVE_WORK_FILE="${MAIN_REPO_ROOT}/.claude-pipeline/active-work.md"
CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null)"

if [ ! -f "${ACTIVE_WORK_FILE}" ]; then
  echo ""
  echo "🚫 push を中断しました: active-work.md が見つかりません。"
  echo "   期待パス: ${ACTIVE_WORK_FILE}"
  echo ""
  exit 1
fi

# grep -q で完全一致（"| branch |" 形式）— 部分一致による誤検出を防ぐ
if ! grep -q "| ${CURRENT_BRANCH} |" "${ACTIVE_WORK_FILE}" 2>/dev/null; then
  echo ""
  echo "🚫 push を中断しました: ブランチが active-work.md に登録されていません。"
  echo "   ブランチ: ${CURRENT_BRANCH}"
  echo ""
  echo "   正しい手順:"
  echo "   bash scripts/new-worktree.sh ${CURRENT_BRANCH}"
  echo "   （実行すると active-work.md に自動登録されます）"
  echo ""
  exit 1
fi

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# チェック3: マージベース検証（他エージェントの変更混入チェック）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# develop と現在ブランチの分岐点が origin/develop の最新コミットと一致するか確認
# 不一致 = 他エージェントの変更が develop にマージされた後に rebase していない
#         → そのまま push すると develop の最新が含まれていない状態になる

if git rev-parse --verify origin/develop >/dev/null 2>&1; then
  MERGE_BASE="$(git merge-base HEAD origin/develop 2>/dev/null)"
  DEVELOP_HEAD="$(git rev-parse origin/develop 2>/dev/null)"

  if [ -n "${MERGE_BASE}" ] && [ -n "${DEVELOP_HEAD}" ]; then
    if [ "${MERGE_BASE}" != "${DEVELOP_HEAD}" ]; then
      echo ""
      echo "⚠️  push を中断しました: develop と乖離があります。"
      echo "   他エージェントの変更が develop にマージされています。"
      echo ""
      echo "   正しい手順:"
      echo "   git fetch origin && git rebase origin/develop"
      echo ""
      exit 1
    fi
  fi
fi

echo "✅ オーナーシップチェック通過: ${CURRENT_BRANCH}"
exit 0
