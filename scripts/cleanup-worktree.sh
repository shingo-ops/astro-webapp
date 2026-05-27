#!/bin/bash
# cleanup-worktree.sh — PRマージ後のworktree自動クリーンアップ
#
# 目的: gh-pr-merge-safe.sh がマージ成功した後に呼び出され、
#       使用済みworktreeとブランチを自動削除する
#
# 使用方法: bash scripts/cleanup-worktree.sh <ブランチ名> <worktreeパス> <メインリポジトリルート>
#
# 呼び出し元: scripts/gh-pr-merge-safe.sh（マージ成功後に自動実行）

set -e

BRANCH="${1}"
WORKTREE_DIR="${2}"
MAIN_REPO_ROOT="${3}"

if [ -z "${BRANCH}" ] || [ -z "${WORKTREE_DIR}" ] || [ -z "${MAIN_REPO_ROOT}" ]; then
  echo "使い方: bash scripts/cleanup-worktree.sh <ブランチ名> <worktreeパス> <メインリポジトリルート>"
  exit 1
fi

# ── メインリポジトリ自体は削除しない ─────────────────────────────────────────
if [ "${WORKTREE_DIR}" = "${MAIN_REPO_ROOT}" ]; then
  echo "ℹ️  メインリポジトリのためworktreeクリーンアップをスキップ"
  exit 0
fi

echo ""
echo "🗑️  worktreeをクリーンアップしています..."
echo "   ブランチ: ${BRANCH}"
echo "   パス    : ${WORKTREE_DIR}"
echo ""

# ── worktree 削除（メインリポジトリから実行）─────────────────────────────────
git -C "${MAIN_REPO_ROOT}" worktree remove --force "${WORKTREE_DIR}" 2>/dev/null && \
  echo "✅ worktree削除完了: ${WORKTREE_DIR}" || \
  echo "⚠️  worktree削除スキップ（既に存在しない可能性あり）"

# ── ローカルブランチ削除 ─────────────────────────────────────────────────────
git -C "${MAIN_REPO_ROOT}" branch -D "${BRANCH}" 2>/dev/null && \
  echo "✅ ブランチ削除完了: ${BRANCH}" || \
  echo "⚠️  ブランチ削除スキップ（既に存在しない可能性あり）"

# ── active-work.md からエントリ削除 ─────────────────────────────────────────
ACTIVE_WORK_FILE="${MAIN_REPO_ROOT}/.claude-pipeline/active-work.md"
if [ -f "${ACTIVE_WORK_FILE}" ]; then
  python3 - "${ACTIVE_WORK_FILE}" "${BRANCH}" <<'PYEOF'
import sys, re

filepath, branch = sys.argv[1], sys.argv[2]

with open(filepath, encoding="utf-8") as f:
    content = f.read()

# ブランチ名を含む行を削除（テーブル行のみ対象）
lines = content.splitlines(keepends=True)
new_lines = [l for l in lines if branch not in l or not l.strip().startswith('|')]
new_content = ''.join(new_lines)

if new_content != content:
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(new_content)
    print(f"✅ active-work.md からエントリを削除しました: {branch}")
else:
    print(f"ℹ️  active-work.md にエントリなし（スキップ）: {branch}")
PYEOF
fi

# ── worktree prune ───────────────────────────────────────────────────────────
git -C "${MAIN_REPO_ROOT}" worktree prune 2>/dev/null || true

echo ""
echo "✅ クリーンアップ完了"
echo ""
