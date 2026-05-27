#!/bin/bash
# release-worktree.sh — 放置worktreeの緊急解放
#
# 目的: クラッシュ・放置により .worktree-id が残存してブロックされた場合に
#       UUID・クレーム・active-work.md エントリを強制解放する
#
# 使用方法: bash scripts/release-worktree.sh <ブランチ名>
#           bash scripts/release-worktree.sh <ブランチ名> --full  # worktree削除も実行
#
# 呼び出し元: 手動 / Sprint 3 のVOICEVOX承認フロー

set -e

BRANCH="${1}"
MODE="${2}"  # --full でcleanup-worktree.shも実行

if [ -z "${BRANCH}" ]; then
  echo ""
  echo "使い方: bash scripts/release-worktree.sh <ブランチ名> [--full]"
  echo ""
  echo "  --full  : .worktree-idの解放に加えてworktreeとブランチも削除"
  echo ""
  exit 1
fi

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"
BRANCH_SAFE="${BRANCH//\//-}"
WORKTREE_DIR="${HOME}/worktrees/$(basename "${REPO_ROOT}")/${BRANCH_SAFE}"

echo ""
echo "🔓 緊急解放を開始します: ${BRANCH}"
echo ""

# ── .worktree-id の解放 ─────────────────────────────────────────────────────
WORKTREE_ID_FILE="${WORKTREE_DIR}/.worktree-id"
if [ -f "${WORKTREE_ID_FILE}" ]; then
  UUID_VAL="$(python3 -c "import json; d=json.load(open('${WORKTREE_ID_FILE}')); print(d.get('uuid','unknown'))" 2>/dev/null || echo 'unknown')"
  echo "🔓 UUID解放: ${UUID_VAL}"
  rm -f "${WORKTREE_ID_FILE}"
  echo "✅ .worktree-id を削除しました"
elif [ -d "${WORKTREE_DIR}" ]; then
  echo "ℹ️  .worktree-id が存在しません（既に解放済みか、UUID未発行）"
else
  echo "ℹ️  worktreeディレクトリが存在しません: ${WORKTREE_DIR}"
fi

# ── claims.json からクレームを解放 ──────────────────────────────────────────
CLAIMS_FILE="${REPO_ROOT}/.claude-pipeline/claims.json"
if [ -f "${CLAIMS_FILE}" ]; then
  python3 - "${CLAIMS_FILE}" "${BRANCH}" <<'PYEOF'
import sys, json, os

claims_file, branch = sys.argv[1], sys.argv[2]
try:
    with open(claims_file, encoding='utf-8') as f:
        claims = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    claims = {}

if branch in claims:
    session = claims[branch].get('session', 'unknown')
    del claims[branch]
    with open(claims_file, 'w', encoding='utf-8') as f:
        json.dump(claims, f, ensure_ascii=False, indent=2)
    print(f"✅ claims.json からクレームを解放しました（セッション: {session}）")
else:
    print(f"ℹ️  claims.json にエントリなし（スキップ）: {branch}")
PYEOF
fi

# ── agent-events.jsonl に release_forced を記録 ────────────────────────────
EVENTS_LOG="$HOME/.claude/logs/agent-events.jsonl"
python3 - <<PYEOF >> "$EVENTS_LOG"
import json
print(json.dumps({
    "type": "release_forced",
    "branch": "$BRANCH",
    "ts": "$(date -u '+%Y-%m-%dT%H:%M:%SZ')",
    "mode": "$MODE"
}))
PYEOF

# ── --full モード: cleanup-worktree.sh を実行 ──────────────────────────────
if [ "${MODE}" = "--full" ]; then
  CLEANUP_SCRIPT="${REPO_ROOT}/scripts/cleanup-worktree.sh"
  if [ -f "${CLEANUP_SCRIPT}" ]; then
    echo ""
    echo "🗑️  --full モード: cleanup-worktree.sh を実行します..."
    bash "${CLEANUP_SCRIPT}" "${BRANCH}" "${WORKTREE_DIR}" "${REPO_ROOT}"
  else
    echo "⚠️  cleanup-worktree.sh が見つかりません"
  fi
fi

echo ""
echo "✅ 緊急解放完了: ${BRANCH}"
echo ""
