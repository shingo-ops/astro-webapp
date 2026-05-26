#!/bin/bash
# agent-config.sh — Agent Workflow Configuration (Central SSoT)
#
# 目的: エージェント開発ワークフローの共通設定値を一元管理する
#       Design Tokens と同じ思想 — 値は1箇所で定義し、スクリプトはここを参照する
#
# 使い方（スクリプト内でのソース読み込み）:
#   GIT_COMMON_DIR="$(git rev-parse --git-common-dir 2>/dev/null)"
#   if [[ "${GIT_COMMON_DIR}" = /* ]]; then
#     source "$(dirname "${GIT_COMMON_DIR}")/.claude/agent-config.sh"
#   else
#     source "$(git rev-parse --show-toplevel)/.claude/agent-config.sh"
#   fi
#
# 変更する場合: このファイルだけ変更すれば全スクリプトに反映される（git pull で全員に配布）
# 関連ドキュメント: docs/adr/ADR-074-worktree-agent-enforcement.md

# ── worktree ルートディレクトリ ───────────────────────────────────────────────
# 全エージェントがこの配下の「個室」で作業する規約
# scripts/validate-pr-ownership.sh と validate-worktree-start.sh が参照する
AGENT_WORKTREE_BASE="${HOME}/worktrees"

# ── フィーチャーブランチのベース ─────────────────────────────────────────────
# git rebase・divergence チェックで使用するブランチ名
# origin/$AGENT_BASE_BRANCH との乖離を validate-pr-ownership.sh が確認する
AGENT_BASE_BRANCH="develop"

# ── Active Work Registry の相対パス ─────────────────────────────────────────
# リポジトリルートからの相対パス（重複作業防止の SSoT ファイル）
AGENT_ACTIVE_WORK_REL=".claude-pipeline/active-work.md"

# ── ブランチ命名プレフィックス（参照用・強制なし） ────────────────────────────
# ドキュメント・エラーメッセージでの表示用。ESLint のような機械強制はしない
AGENT_BRANCH_PREFIX="feature/morimoto/"
