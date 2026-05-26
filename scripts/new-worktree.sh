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

  # Active Work Registry に自動登録（SSoT: .claude-pipeline/active-work.md）
  ACTIVE_WORK_FILE="${REPO_ROOT}/.claude-pipeline/active-work.md"
  if [ -f "${ACTIVE_WORK_FILE}" ]; then
    STARTED_AT="$(date '+%Y-%m-%d %H:%M')"
    # 既存のエントリを確認
    if grep -q "${BRANCH}" "${ACTIVE_WORK_FILE}" 2>/dev/null; then
      echo "ℹ️  active-work.md に既存エントリあり（重複登録をスキップ）"
    else
      python3 - "${ACTIVE_WORK_FILE}" "${BRANCH}" "${STARTED_AT}" <<'PYEOF'
import sys, re

filepath, branch, started = sys.argv[1], sys.argv[2], sys.argv[3]
new_row = f"| {branch} | （記入してください） | {started} | IN_PROGRESS | |"

with open(filepath, encoding="utf-8") as f:
    content = f.read()

# *(なし)* プレースホルダー行を置換（初回登録）
if "*(なし)*" in content:
    content = re.sub(r"\| \*\(なし\)\* \| — \| — \| — \| — \|", new_row, content)
else:
    # テーブルの最終行の直後に挿入（--- セパレータの前）
    # 構造: | 最終行 |\n\n---\n\n## 記入例
    # "## 記入例" の前には "---" セパレータがあるため、
    # "## 記入例" の直前に挿入するとテーブル外になるバグを修正
    # lambda を使うことでブランチ名内の \1 等が後方参照と誤解釈されるのを防ぐ
    content = re.sub(
        r"(\n---\n\n## 記入例)",
        lambda m: "\n" + new_row + m.group(1),
        content,
        count=1,
    )

with open(filepath, "w", encoding="utf-8") as f:
    f.write(content)
PYEOF
      echo "📋 active-work.md に登録しました（担当機能エリアを記入してください）"
    fi
  fi
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
