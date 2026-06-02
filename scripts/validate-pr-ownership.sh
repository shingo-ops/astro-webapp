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
#       docs/adr/ADR-074-worktree-agent-enforcement.md

set -e

# CI環境はスキップ（GitHub Actions は自分専用のブランチを自分で管理する）
if [ -n "${GITHUB_ACTIONS}" ]; then
  exit 0
fi

# ── 中央設定ファイルを読み込む（SSoT: .claude/agent-config.sh）──────────────
# --git-common-dir でメインリポジトリルートを取得（worktree でも main repo でも動作する）
GIT_COMMON_DIR="$(git rev-parse --git-common-dir 2>/dev/null)"
if [[ "${GIT_COMMON_DIR}" = /* ]]; then
  MAIN_REPO_ROOT="$(dirname "${GIT_COMMON_DIR}")"
else
  MAIN_REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"
fi
CONFIG_FILE="${MAIN_REPO_ROOT}/.claude/agent-config.sh"
if [ -f "${CONFIG_FILE}" ]; then
  # shellcheck source=.claude/agent-config.sh
  source "${CONFIG_FILE}"
fi
# デフォルト値（config がない環境へのフォールバック）
AGENT_WORKTREE_BASE="${AGENT_WORKTREE_BASE:-${HOME}/worktrees}"
AGENT_BASE_BRANCH="${AGENT_BASE_BRANCH:-develop}"
AGENT_ACTIVE_WORK_REL="${AGENT_ACTIVE_WORK_REL:-.claude-pipeline/active-work.md}"
AGENT_BRANCH_PREFIX="${AGENT_BRANCH_PREFIX:-feature/morimoto/}"

ACTUAL_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"
CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null)"
ACTIVE_WORK_FILE="${MAIN_REPO_ROOT}/${AGENT_ACTIVE_WORK_REL}"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# チェック1: worktree 外での push を禁止
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 各エージェントは AGENT_WORKTREE_BASE/<repo>/<branch>/ で作業する規約
# メインリポジトリから push すると他エージェントの変更が混入する可能性がある

case "${ACTUAL_ROOT}" in
  "${AGENT_WORKTREE_BASE}/"*) ;;  # OK: 個室（worktree）内で作業している
  *)
    echo ""
    echo "🚫 push を中断しました: worktree 外での作業は禁止されています。"
    echo ""
    echo "   現在のディレクトリ: ${ACTUAL_ROOT}"
    echo "   許可される場所   : ${AGENT_WORKTREE_BASE}/salesanchor/<branch>/"
    echo ""
    echo "   正しい手順:"
    echo "   1. bash scripts/new-worktree.sh ${AGENT_BRANCH_PREFIX}<トピック名>"
    echo "   2. cd ${AGENT_WORKTREE_BASE}/salesanchor/${AGENT_BRANCH_PREFIX//\//-}<トピック名>"
    echo "   3. そこから作業・push してください"
    echo ""
    exit 1
    ;;
esac

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# チェック2: active-work.md にブランチが登録されているか（完全一致）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# new-worktree.sh が作成時に自動登録する（SSoT: AGENT_ACTIVE_WORK_REL）

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
# AGENT_BASE_BRANCH と現在ブランチの分岐点が最新であるか確認
# 不一致 = 他エージェントの変更がベースにマージされた後に rebase していない

if git rev-parse --verify "origin/${AGENT_BASE_BRANCH}" >/dev/null 2>&1; then
  MERGE_BASE="$(git merge-base HEAD "origin/${AGENT_BASE_BRANCH}" 2>/dev/null)"
  BASE_HEAD="$(git rev-parse "origin/${AGENT_BASE_BRANCH}" 2>/dev/null)"

  if [ -n "${MERGE_BASE}" ] && [ -n "${BASE_HEAD}" ]; then
    if [ "${MERGE_BASE}" != "${BASE_HEAD}" ]; then
      echo ""
      echo "⚠️  push を中断しました: ${AGENT_BASE_BRANCH} と乖離があります。"
      echo "   他エージェントの変更が ${AGENT_BASE_BRANCH} にマージされています。"
      echo ""
      echo "   正しい手順:"
      echo "   git fetch origin && git rebase origin/${AGENT_BASE_BRANCH}"
      echo ""
      exit 1
    fi
  fi
fi

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# チェック4: マージ済みPRへの追加 push を禁止
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 問題: PRマージ後に同じブランチへ push すると変更が develop/main に反映されない
# 解決: gh でPR状態を確認し MERGED なら push をブロックする

if command -v gh >/dev/null 2>&1; then
  PR_STATE="$(gh pr list --head "${CURRENT_BRANCH}" --state merged --json state --jq '.[0].state' 2>/dev/null)"
  if [ "${PR_STATE}" = "MERGED" ]; then
    echo ""
    echo "🚫 push を中断しました: このブランチのPRはすでにマージ済みです。"
    echo "   ブランチ: ${CURRENT_BRANCH}"
    echo ""
    echo "   追加変更がある場合は新しいブランチ・PRを作成してください:"
    echo "   bash scripts/new-worktree.sh ${AGENT_BRANCH_PREFIX}<新トピック名>"
    echo ""
    exit 1
  fi
fi

echo "✅ オーナーシップチェック通過: ${CURRENT_BRANCH}"
exit 0
