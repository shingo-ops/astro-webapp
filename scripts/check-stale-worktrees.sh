#!/bin/bash
# check-stale-worktrees.sh — 放置worktreeの検出・通知
#
# 目的: ~/worktrees/salesanchor/ 配下の worktree を走査し、
#       .worktree-id の created_at が 24 時間以上経過したものを
#       「放置worktree」として検出・報告する。
#
# 使用方法: bash scripts/check-stale-worktrees.sh
#
# 出力キーワード（監督スクリプトが grep する）:
#   放置worktreeなし    — 放置なし
#   VOICEVOX通知        — VOICEVOX 通知を送った
#   アクティブセッションに通知 — claims.json でセッション特定し通知した
#
# 呼び出し元: 監督Cron（5分ごと）のみ実行すること
#             フィーチャータブからは実行しない（干渉ルール）
#
# 参考: docs/adr/ KGI100%プラン Sprint 3

set -euo pipefail

# ---------- 設定 ----------
STALE_HOURS="${STALE_HOURS:-24}"          # 環境変数で上書き可能（テスト用）
STALE_SECONDS=$(( STALE_HOURS * 3600 ))

WORKTREES_DIR="${HOME}/worktrees/salesanchor"
EVENTS_LOG="${HOME}/.claude/logs/agent-events.jsonl"
NOTIFY="${HOME}/.claude/scripts/notify.sh"
SEND_INSTRUCTION="${HOME}/.claude/scripts/send-instruction.sh"

# .claude-pipeline/claims.json はリポジトリルートからの相対パス
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || echo "")"
CLAIMS_JSON="${REPO_ROOT}/.claude-pipeline/claims.json"

# VOICEVOX 話者ID（agent-tokens.json があれば読む）
SPEAKER_WARNING=$(python3 -c "
import json, os
p = os.path.expanduser('~/.claude/agent-tokens.json')
if os.path.exists(p):
    d = json.load(open(p))
    print(d.get('speaker_warning', 3))
else:
    print(3)
" 2>/dev/null || echo "3")

NOW_EPOCH=$(date +%s)
STALE_COUNT=0

# ---------- ~/worktrees/salesanchor/ を走査 ----------
if [ ! -d "${WORKTREES_DIR}" ]; then
  echo "放置worktreeなし（${WORKTREES_DIR} が存在しません）"
  exit 0
fi

for WORKTREE_PATH in "${WORKTREES_DIR}"/*/; do
  [ -d "${WORKTREE_PATH}" ] || continue

  WORKTREE_ID_FILE="${WORKTREE_PATH}.worktree-id"
  [ -f "${WORKTREE_ID_FILE}" ] || continue

  # .worktree-id を読み込む
  BRANCH=$(python3 -c "
import json
d = json.load(open('${WORKTREE_ID_FILE}'))
print(d.get('branch', 'unknown'))
" 2>/dev/null || echo "unknown")

  CREATED_AT=$(python3 -c "
import json
d = json.load(open('${WORKTREE_ID_FILE}'))
print(d.get('created_at', ''))
" 2>/dev/null || echo "")

  UUID_VAL=$(python3 -c "
import json
d = json.load(open('${WORKTREE_ID_FILE}'))
print(d.get('uuid', 'unknown'))
" 2>/dev/null || echo "unknown")

  [ -z "${CREATED_AT}" ] && continue

  # created_at から経過秒数を計算
  CREATED_EPOCH=$(python3 -c "
from datetime import datetime, timezone
try:
    dt = datetime.strptime('${CREATED_AT}', '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
    print(int(dt.timestamp()))
except Exception:
    print(0)
" 2>/dev/null || echo "0")

  [ "${CREATED_EPOCH}" -eq 0 ] && continue

  AGE_SECONDS=$(( NOW_EPOCH - CREATED_EPOCH ))

  # 24時間未満はスキップ
  [ "${AGE_SECONDS}" -lt "${STALE_SECONDS}" ] && continue

  AGE_HOURS=$(( AGE_SECONDS / 3600 ))
  STALE_COUNT=$(( STALE_COUNT + 1 ))

  # ---------- VOICEVOX 警告通知 ----------
  if [ -x "${NOTIFY}" ]; then
    BRANCH_SHORT=$(echo "${BRANCH}" | sed 's|feature/morimoto/||')
    "${NOTIFY}" "放置ワークツリーを検出しました: ${BRANCH_SHORT}" "${SPEAKER_WARNING}" &
  fi
  echo "VOICEVOX通知: ${BRANCH} (${AGE_HOURS}時間経過)"

  # ---------- agent-events.jsonl に stale_worktree_detected を記録 ----------
  mkdir -p "$(dirname "${EVENTS_LOG}")"
  python3 - >> "${EVENTS_LOG}" <<PYEOF
import json
from datetime import datetime, timezone
print(json.dumps({
    "type": "stale_worktree_detected",
    "branch": "${BRANCH}",
    "uuid": "${UUID_VAL}",
    "age_hours": ${AGE_HOURS},
    "ts": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
}))
PYEOF

  # ---------- claims.json でアクティブセッション特定 ----------
  # 一時ファイル経由でPythonスクリプトを実行（heredoc内のシングルクォート問題を回避）
  _PY_SCRIPT=$(mktemp /tmp/claims_check.XXXXXX.py)
  cat > "${_PY_SCRIPT}" <<PYEOF
import json, os, sys
claims_path = os.environ.get("CLAIMS_PATH", "")
branch = os.environ.get("BRANCH_NAME", "")
if not os.path.exists(claims_path):
    sys.exit(0)
try:
    data = json.load(open(claims_path, encoding="utf-8"))
    claims = data if isinstance(data, list) else data.get("claims", [])
    for claim in claims:
        if isinstance(claim, dict) and claim.get("branch") == branch:
            sid = claim.get("session_id") or claim.get("uuid", "")
            if sid:
                print(sid)
                break
except Exception:
    pass
PYEOF
  SESSION_ID=$(CLAIMS_PATH="${CLAIMS_JSON}" BRANCH_NAME="${BRANCH}" python3 "${_PY_SCRIPT}" 2>/dev/null || echo "")
  rm -f "${_PY_SCRIPT}"

  if [ -n "${SESSION_ID}" ]; then
    # アクティブセッションが特定できた場合 → send-instruction で通知
    if [ -f "${SEND_INSTRUCTION}" ] && [ -x "${SEND_INSTRUCTION}" ]; then
      bash "${SEND_INSTRUCTION}" "${BRANCH}" \
        "このworktreeが${STALE_HOURS}時間経過しています。作業完了後は bash scripts/cleanup-worktree.sh を実行してください (UUID: ${UUID_VAL})" 2>/dev/null || true
    fi
    echo "アクティブセッションに通知: ${BRANCH} (セッション: ${SESSION_ID})"
  fi

done

# ---------- 結果サマリ ----------
if [ "${STALE_COUNT}" -eq 0 ]; then
  echo "放置worktreeなし（全worktreeが${STALE_HOURS}時間未満）"
fi
