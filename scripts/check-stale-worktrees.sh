#!/bin/bash
# check-stale-worktrees.sh — 放置worktreeの検出・通知
#
# 目的: 12時間以上放置されたworktreeを検出し、状況に応じて報告する
#       担当セッションがアクティブなら send-instruction で通知
#       担当セッションが停止中なら監督タブ（しんごさん）に VOICEVOX 報告
#
# 使用方法: bash scripts/check-stale-worktrees.sh
#
# 呼び出し元: 監督Cron（5分ごと）のみ実行すること
#             フィーチャータブからは実行しない（干渉ルール）
#
# 参考: docs/adr/ KGI100%プラン Sprint 3

set -e

STALE_HOURS="${STALE_HOURS:-12}"   # 環境変数で上書き可能（テスト用）
ACTIVE_MINUTES=10                   # この分以内のイベントがあれば「アクティブ」
EVENTS_LOG="$HOME/.claude/logs/agent-events.jsonl"
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"
SEND_INSTRUCTION="${REPO_ROOT}/scripts/send-instruction.sh"
NOTIFY="${HOME}/.claude/scripts/notify.sh"
SPEAKER_WARNING=$(python3 -c "import json; print(json.load(open('$HOME/.claude/agent-tokens.json'))['speaker_warning'])" 2>/dev/null || echo "3")

NOW_EPOCH=$(date +%s)
STALE_SECONDS=$(( STALE_HOURS * 3600 ))
ACTIVE_SECONDS=$(( ACTIVE_MINUTES * 60 ))

STALE_COUNT=0

# git worktree list で全worktreeのパスを取得
while IFS= read -r WORKTREE_PATH; do
  WORKTREE_ID_FILE="${WORKTREE_PATH}/.worktree-id"
  [ -f "${WORKTREE_ID_FILE}" ] || continue

  # .worktree-id を読み込む
  BRANCH=$(python3 -c "import json; d=json.load(open('${WORKTREE_ID_FILE}')); print(d.get('branch','unknown'))" 2>/dev/null || echo "unknown")
  CREATED_AT=$(python3 -c "import json; d=json.load(open('${WORKTREE_ID_FILE}')); print(d.get('created_at',''))" 2>/dev/null || echo "")
  UUID_VAL=$(python3 -c "import json; d=json.load(open('${WORKTREE_ID_FILE}')); print(d.get('uuid','unknown'))" 2>/dev/null || echo "unknown")

  [ -z "${CREATED_AT}" ] && continue

  # created_at から経過秒数を計算
  CREATED_EPOCH=$(python3 -c "
from datetime import datetime, timezone
dt = datetime.strptime('${CREATED_AT}', '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
print(int(dt.timestamp()))
" 2>/dev/null || echo "0")

  [ "${CREATED_EPOCH}" -eq 0 ] && continue

  AGE_SECONDS=$(( NOW_EPOCH - CREATED_EPOCH ))
  AGE_HOURS=$(( AGE_SECONDS / 3600 ))

  # 12時間未満はスキップ
  [ "${AGE_SECONDS}" -lt "${STALE_SECONDS}" ] && continue

  STALE_COUNT=$(( STALE_COUNT + 1 ))

  # agent-events.jsonl でそのブランチの最終活動時刻を確認
  LAST_ACTIVITY_EPOCH=$(python3 - "${EVENTS_LOG}" "${BRANCH}" <<'PYEOF'
import sys, json, os
from datetime import datetime, timezone

events_log, branch = sys.argv[1], sys.argv[2]
if not os.path.exists(events_log):
    print(0)
    sys.exit(0)

last_ts = None
with open(events_log, encoding='utf-8') as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
            if ev.get('branch') == branch or ev.get('target') == branch:
                last_ts = ev.get('ts', '')
        except Exception:
            pass

if not last_ts:
    print(0)
    sys.exit(0)

try:
    dt = datetime.strptime(last_ts, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
    print(int(dt.timestamp()))
except Exception:
    print(0)
PYEOF
)

  IDLE_SECONDS=$(( NOW_EPOCH - LAST_ACTIVITY_EPOCH ))
  BRANCH_SHORT=$(echo "$BRANCH" | sed 's|feature/morimoto/||')

  if [ "${LAST_ACTIVITY_EPOCH}" -gt 0 ] && [ "${IDLE_SECONDS}" -lt "${ACTIVE_SECONDS}" ]; then
    # セッションはアクティブ → 担当タブへ send-instruction
    if [ -f "${SEND_INSTRUCTION}" ]; then
      bash "${SEND_INSTRUCTION}" "${BRANCH}" \
        "このworktreeが${STALE_HOURS}時間経過しています。作業完了後は bash scripts/cleanup-worktree.sh を実行してください (UUID: ${UUID_VAL})" 2>/dev/null || true
    fi
    echo "📩 アクティブセッションに通知: ${BRANCH} (${AGE_HOURS}時間経過)"
  else
    # セッションは停止中 → 監督タブ（しんごさん）へ VOICEVOX 報告
    "${NOTIFY}" "${BRANCH_SHORT}のワークツリーが${AGE_HOURS}時間放置・セッション停止中です" "$SPEAKER_WARNING" &
    echo "🔔 VOICEVOX通知: ${BRANCH} (${AGE_HOURS}時間, セッション停止中)"

    # agent-events.jsonl に stale_detected を記録
    python3 - <<PYEOF >> "$EVENTS_LOG"
import json, os
print(json.dumps({
    "type": "stale_detected",
    "branch": "$BRANCH",
    "uuid": "$UUID_VAL",
    "age_hours": $AGE_HOURS,
    "ts": "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
}))
PYEOF
  fi

done < <(git worktree list --porcelain 2>/dev/null | grep '^worktree ' | awk '{print $2}')

if [ "${STALE_COUNT}" -eq 0 ]; then
  echo "✅ 放置worktreeなし（全worktreeが${STALE_HOURS}時間未満）"
fi
