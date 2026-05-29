#!/usr/bin/env bash
# =============================================================================
# codex-research.sh — Codex を Research / Planning エージェントとして非対話実行するラッパー
# =============================================================================
# 使い方:
#   bash scripts/codex-research.sh "タスク説明"
#   bash scripts/codex-research.sh --plan "タスク説明"   # Planner モード
#   bash scripts/codex-research.sh --json "タスク説明"   # JSON 出力
#
# codex exec を使って非対話で実行するため、Claude Code のターミナルから
# ! bash scripts/codex-research.sh "..." で直接呼べる。
# =============================================================================

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
CODEX_BIN="${HOME}/.npm-global/bin/codex"

# ────────────────────────────────────────────────────────────────────────────
# 引数パース
# ────────────────────────────────────────────────────────────────────────────
MODE="research"    # research | plan
JSON_OUTPUT=false
TASK=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --plan)
      MODE="plan"
      shift
      ;;
    --json)
      JSON_OUTPUT=true
      shift
      ;;
    --help|-h)
      echo "使い方:"
      echo "  bash scripts/codex-research.sh \"タスク説明\"          # Research モード"
      echo "  bash scripts/codex-research.sh --plan \"タスク説明\"   # Planner モード"
      echo "  bash scripts/codex-research.sh --json \"タスク説明\"   # JSON 出力"
      exit 0
      ;;
    *)
      TASK="$1"
      shift
      ;;
  esac
done

if [[ -z "$TASK" ]]; then
  echo "❌ タスク説明を指定してください"
  echo "   例: bash scripts/codex-research.sh \"受信箱 502 エラーの原因を調査して\""
  exit 1
fi

# ────────────────────────────────────────────────────────────────────────────
# 前提チェック
# ────────────────────────────────────────────────────────────────────────────
if [[ ! -f "$CODEX_BIN" ]]; then
  echo "❌ Codex CLI が見つかりません: $CODEX_BIN"
  echo "   npm install -g @openai/codex を実行してください"
  exit 1
fi

bash "$REPO_ROOT/scripts/codex-auth-check.sh"

# ────────────────────────────────────────────────────────────────────────────
# プロンプト構築
# ────────────────────────────────────────────────────────────────────────────
if [[ "$MODE" == "plan" ]]; then
  ROLE_PROMPT="$(cat <<'ROLE_EOF'
あなたは salesanchor プロジェクトの Planner エージェントです。
docs/agents/planner.md のルールに従い、Research 結果を設計計画に変換してください。

## 出力形式（必須）
- 目的
- 対象パス / 影響範囲
- 実装スコープ（Generator 向け）
- Evaluator 受け入れ基準
- リスクと制約
- 根拠（ファイルパス / コマンド出力 / ADR番号）

## 禁止事項
- 実装しない
- 推測で根拠を補わない
- 証拠のない設計判断をしない

## タスク
ROLE_EOF
)"
else
  ROLE_PROMPT="$(cat <<'ROLE_EOF'
あなたは salesanchor プロジェクトの Research エージェントです。
docs/agents/research.md のルールに従い、事実ベースの調査を行ってください。

## 出力形式（必須）
- 5W2H（Who/What/When/Where/Why/How/How Much）
- 成功パターン
- 失敗パターン
- 数値エビデンス（ファイルパス・行番号・CI job名・差分サイズ等）
- 制約・リスク・トレードオフ
- 推奨方向
- 却下した代替案
- Planner への引き継ぎ事項

## 禁止事項
- 実装しない
- 設計判断しない
- `.env` / secrets / node_modules / dist / build / coverage は読まない
- 証拠不足の場合は推測せず「証拠不足」と明記する

## タスク
ROLE_EOF
)"
fi

FULL_PROMPT="${ROLE_PROMPT}
${TASK}"

# ────────────────────────────────────────────────────────────────────────────
# 実行
# ────────────────────────────────────────────────────────────────────────────
echo "🔍 Codex ${MODE^} 実行中..."
echo "   タスク: ${TASK}"
echo ""

cd "$REPO_ROOT"

EXEC_ARGS=()
if [[ "$JSON_OUTPUT" == "true" ]]; then
  EXEC_ARGS+=("--json")
fi

"$CODEX_BIN" exec "${EXEC_ARGS[@]}" "$FULL_PROMPT"
