#!/usr/bin/env bash
# =============================================================================
# aeon-release.sh — AEON delivery の PR を main へ安全に昇格する入口
# =============================================================================
# 使い方:
#   bash scripts/aeon-release.sh                 # .pr-number を使う
#   bash scripts/aeon-release.sh 123             # PR #123 を昇格
#   bash scripts/aeon-release.sh --help
# =============================================================================

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
LOG_FILE="/tmp/aeon-release-$(date +%Y%m%d-%H%M%S).log"

usage() {
  echo "❌ 使用法: bash scripts/aeon-release.sh [PR番号]"
  exit 1
}

POSITIONAL=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --help|-h)
      usage
      ;;
    --)
      shift
      while [[ $# -gt 0 ]]; do
        POSITIONAL+=("$1")
        shift
      done
      ;;
    *)
      POSITIONAL+=("$1")
      shift
      ;;
  esac
done

exec > >(tee -a "$LOG_FILE") 2>&1

echo "🚀 AEON release started"
echo "   log : $LOG_FILE"
echo ""

bash "$REPO_ROOT/scripts/validate-worktree-start.sh"

CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
WORKTREE_DIR="$(git rev-parse --show-toplevel)"
PR_NUMBER_FILE="${WORKTREE_DIR}/.pr-number"

if [[ ${#POSITIONAL[@]} -gt 1 ]]; then
  usage
fi

if [[ ${#POSITIONAL[@]} -eq 1 ]]; then
  OWNED_PR="${POSITIONAL[0]}"
elif [[ -f "$PR_NUMBER_FILE" ]]; then
  OWNED_PR="$(tr -d '[:space:]' < "$PR_NUMBER_FILE")"
else
  echo "🚫 PR番号が見つかりません。引数か .pr-number を指定してください。"
  exit 1
fi

if [[ -z "$OWNED_PR" ]]; then
  echo "🚫 PR番号が空です。"
  exit 1
fi

BASE_REF="$(gh pr view "$OWNED_PR" --json baseRefName --jq '.baseRefName')"
if [[ "$BASE_REF" != "main" ]]; then
  echo "🚫 release は main 向け PR のみ許可します。baseRefName=$BASE_REF"
  exit 1
fi

REVIEW_DECISION="$(gh pr view "$OWNED_PR" --json reviewDecision --jq '.reviewDecision')"
MERGE_STATE="$(gh pr view "$OWNED_PR" --json mergeStateStatus --jq '.mergeStateStatus')"
if [[ "$REVIEW_DECISION" != "APPROVED" ]]; then
  echo "🚫 Reviewer APPROVED ではありません。reviewDecision=$REVIEW_DECISION"
  exit 1
fi
if [[ "$MERGE_STATE" != "CLEAN" ]]; then
  echo "🚫 mergeStateStatus が CLEAN ではありません。mergeStateStatus=$MERGE_STATE"
  exit 1
fi

printf '%s\n' "$OWNED_PR" > "$PR_NUMBER_FILE"

echo "✅ PR #${OWNED_PR} を main へ昇格します"
echo "   branch : $CURRENT_BRANCH"
echo "   base   : $BASE_REF"
echo "   review : $REVIEW_DECISION"
echo "   merge  : $MERGE_STATE"
echo ""

bash "$REPO_ROOT/scripts/gh-pr-merge-safe.sh" --merge --delete-branch

echo ""
echo "✅ AEON release complete"
echo "   log : $LOG_FILE"
