#!/bin/bash
# new-worktree.sh — Git Worktree 標準起動スクリプト
#
# 使い方:
#   bash scripts/new-worktree.sh <ブランチ名>
#   bash scripts/new-worktree.sh <ブランチ名> --claude  # Claude Code も同時起動
#
# 例:
#   bash scripts/new-worktree.sh feature/morimoto/new-feature
#   bash scripts/new-worktree.sh feature/morimoto/new-feature --claude
#
# 効果:
#   ~/worktrees/salesanchor/<ブランチ名>/ に独立した作業ディレクトリを作成
#   → 別ターミナルのブランチ切り替えに影響を受けない
#
# 参考: docs/PARALLEL_TERMINAL_GUIDE.md (P5)
#       https://incident.io/blog/shipping-faster-with-claude-code-and-git-worktrees

set -e

BRANCH="${1}"
WITH_CLAUDE="${2}"

if [ -z "${BRANCH}" ]; then
  echo ""
  echo "使い方: bash scripts/new-worktree.sh <ブランチ名> [--claude]"
  echo ""
  echo "例:"
  echo "  bash scripts/new-worktree.sh feature/morimoto/my-feature"
  echo "  bash scripts/new-worktree.sh feature/morimoto/my-feature --claude"
  echo ""
  exit 1
fi

# リポジトリルートを取得
REPO_ROOT="$(git rev-parse --show-toplevel)"
REPO_NAME="$(basename "${REPO_ROOT}")"

# worktree の配置先（~/worktrees/<リポジトリ名>/<ブランチ名の/を-に置換>）
BRANCH_SAFE="${BRANCH//\//-}"
WORKTREE_DIR="${HOME}/worktrees/${REPO_NAME}/${BRANCH_SAFE}"

# develop から最新化してブランチ作成
git fetch origin

# develop ブランチが存在するか確認
if git show-ref --verify --quiet "refs/remotes/origin/develop"; then
  BASE_BRANCH="origin/develop"
else
  BASE_BRANCH="origin/main"
fi

# すでに worktree が存在する場合はスキップ
if git worktree list | grep -q "${WORKTREE_DIR}"; then
  echo "ℹ️  worktree はすでに存在します: ${WORKTREE_DIR}"
else
  echo "🌿 worktree を作成しています..."
  echo "   ブランチ: ${BRANCH}"
  echo "   ベース  : ${BASE_BRANCH}"
  echo "   場所    : ${WORKTREE_DIR}"
  echo ""

  mkdir -p "$(dirname "${WORKTREE_DIR}")"
  git worktree add -b "${BRANCH}" "${WORKTREE_DIR}" "${BASE_BRANCH}"

  echo ""
  echo "✅ worktree を作成しました: ${WORKTREE_DIR}"
fi

echo ""
echo "📂 移動コマンド:"
echo "   cd ${WORKTREE_DIR}"
echo ""

# --claude フラグで Claude Code を起動
if [ "${WITH_CLAUDE}" = "--claude" ]; then
  echo "🤖 Claude Code を起動しています..."
  cd "${WORKTREE_DIR}"
  claude
fi

echo "🗑️  作業完了後のクリーンアップ:"
echo "   git worktree remove ${WORKTREE_DIR}"
echo "   git branch -d ${BRANCH}"
echo ""
