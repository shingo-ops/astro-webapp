#!/bin/bash
# register-pr.sh — PR番号のworktree登録（gh pr create 直後に必須実行）
#
# 目的: .pr-number ファイルと active-work.md の PR# 列を原子的に更新する
#       手動での二重管理ミスをなくし gh-pr-merge-safe.sh が確実に動く状態にする
#
# 使用方法: bash scripts/register-pr.sh
#
# 前提: gh pr create がすでに完了していること（PRが存在すること）
#
# 参考: scripts/gh-pr-merge-safe.sh, docs/PARALLEL_TERMINAL_GUIDE.md

set -e

# CI環境はスキップ（GitHub Actions は自分専用のPRを自分で管理する）
if [ -n "${GITHUB_ACTIONS}" ]; then
  exit 0
fi

# ── 中央設定ファイルを読み込む ────────────────────────────────────────────────
GIT_COMMON_DIR="$(git rev-parse --git-common-dir 2>/dev/null)"
if [[ "${GIT_COMMON_DIR}" = /* ]]; then
  MAIN_REPO_ROOT="$(dirname "${GIT_COMMON_DIR}")"
else
  MAIN_REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"
fi
CONFIG_FILE="${MAIN_REPO_ROOT}/.claude/agent-config.sh"
if [ -f "${CONFIG_FILE}" ]; then
  source "${CONFIG_FILE}"
fi
AGENT_ACTIVE_WORK_REL="${AGENT_ACTIVE_WORK_REL:-.claude-pipeline/active-work.md}"
ACTIVE_WORK_FILE="${MAIN_REPO_ROOT}/${AGENT_ACTIVE_WORK_REL}"

CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null)"
WORKTREE_DIR="$(git rev-parse --show-toplevel 2>/dev/null)"

# ── ステップ1: PR番号を取得 ──────────────────────────────────────────────────
echo "📋 PR番号を取得中..."
if ! PR_NUMBER=$(gh pr view --json number --jq '.number' 2>/dev/null); then
  echo ""
  echo "🚫 PR番号の取得に失敗しました。"
  echo ""
  echo "   ブランチ '${CURRENT_BRANCH}' に対応するPRが見つかりません。"
  echo "   先に gh pr create を実行してPRを作成してください。"
  echo ""
  echo "   例: gh pr create --base develop --title \"feat: ...\" --body \"...\""
  echo ""
  exit 1
fi

if [ -z "${PR_NUMBER}" ]; then
  echo "🚫 PR番号が空です。gh pr create が正常に完了しているか確認してください。"
  exit 1
fi

echo "   PR #${PR_NUMBER} を確認しました"

# ── ステップ2: .pr-number ファイルに保存 ─────────────────────────────────────
echo "${PR_NUMBER}" > "${WORKTREE_DIR}/.pr-number"
echo "✅ .pr-number に保存しました: ${WORKTREE_DIR}/.pr-number"

# ── ステップ3: active-work.md の PR# 列を更新（macOS 互換 awk）─────────────
if [ -f "${ACTIVE_WORK_FILE}" ]; then
  # ブランチ行の PR# 列（6列目）を更新する
  # テーブル形式: | branch | area | date | status | PR# | notes |
  python3 - "${ACTIVE_WORK_FILE}" "${CURRENT_BRANCH}" "${PR_NUMBER}" <<'PYEOF'
import sys, re

filepath, branch, pr_num = sys.argv[1], sys.argv[2], sys.argv[3]

with open(filepath, encoding="utf-8") as f:
    lines = f.readlines()

updated = False
for i, line in enumerate(lines):
    # ブランチ名が完全一致するテーブル行を探す
    if f"| {branch} |" in line and not line.strip().startswith("|---"):
        parts = line.split("|")
        if len(parts) >= 7:  # 6列テーブル（| col1 | col2 | ... | col6 | で8要素）
            parts[5] = f" {pr_num} "  # PR# 列（0-indexで5番目: ''|branch|area|date|status|PR#|notes|''）
            lines[i] = "|".join(parts)
            updated = True
            break

with open(filepath, "w", encoding="utf-8") as f:
    f.writelines(lines)

sys.exit(0 if updated else 1)
PYEOF
  if [ $? -eq 0 ]; then
    echo "✅ active-work.md の PR# 列を更新しました: #${PR_NUMBER}"
  else
    echo "⚠️  active-work.md にブランチ '${CURRENT_BRANCH}' が見つかりませんでした"
    echo "   .pr-number は保存済みです。active-work.md は手動で更新してください。"
  fi
else
  echo "⚠️  active-work.md が見つかりません: ${ACTIVE_WORK_FILE}"
  echo "   .pr-number は保存済みです。"
fi

echo ""
echo "🎉 PR #${PR_NUMBER} の登録が完了しました（ブランチ: ${CURRENT_BRANCH}）"
echo "   次のステップ: Reviewer がレビューするか、Manager が gh-pr-merge-safe.sh でマージできます"
