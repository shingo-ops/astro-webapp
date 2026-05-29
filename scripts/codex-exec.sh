#!/usr/bin/env bash
# =============================================================================
# codex-exec.sh — Codex を Research / Planner / Architect として非対話実行するラッパー
# =============================================================================
# 使い方:
#   bash scripts/codex-exec.sh research "..."   # Research 用
#   bash scripts/codex-exec.sh planner "..."    # Planner 用
#   bash scripts/codex-exec.sh architect "..."  # Architect 用
#   bash scripts/codex-exec.sh reviewer "..."   # Reviewer 用
#   bash scripts/codex-exec.sh evaluator "..."  # Evaluator 用
#   printf '%s\n' "..." | bash scripts/codex-exec.sh research
# =============================================================================

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
CODEX_BIN="${HOME}/.npm-global/bin/codex"
SANDBOX_MODE="read-only"

if [[ $# -lt 1 ]]; then
  echo "❌ 使用法: bash scripts/codex-exec.sh <research|planner|architect|reviewer|evaluator> [prompt...]"
  exit 1
fi

ROLE="$1"
shift || true

if [[ ! -x "$CODEX_BIN" ]]; then
  echo "❌ Codex CLI が見つかりません: $CODEX_BIN"
  echo "   npm install -g @openai/codex を実行してください"
  exit 1
fi

bash "$REPO_ROOT/scripts/codex-auth-check.sh"

case "$ROLE" in
  research)
    ROLE_PROMPT="$(cat <<'PROMPT'
あなたは SalesAnchor プロジェクトの Research エージェントです。
証拠収集だけを行い、実装や設計判断は行わないでください。

必須ルール:
- 事実、数値、制約、リスク、トレードオフを収集すること
- 既存の ADR、docs、ワークフロー、コード、コマンド出力を一次情報として扱うこと
- 推測は明示し、証拠が不足している場合は不足点を列挙すること
- 出力は schema に沿った Evidence Package にすること
- 実装計画やコード変更案を出さないこと
PROMPT
)"
    SANDBOX_MODE="read-only"
    ;;
  planner)
    ROLE_PROMPT="$(cat <<'PROMPT'
あなたは SalesAnchor プロジェクトの Planner エージェントです。
Research Package を基に WHAT を定義し、HOW は決めないでください。

必須ルール:
- `.claude-pipeline/spec.md` と `.claude-pipeline/state.json` を扱う前提で作業すること
- 実装、DB 設計、API 形状、ファイル構成は決めないこと
- 既存コードベースの制約と重複を確認すること
- 出力はスキーマ準拠の仕様書にすること
- 不確実な点は質問またはレビュー前提の指摘として残すこと
PROMPT
)"
    SANDBOX_MODE="read-only"
    ;;
  architect)
    ROLE_PROMPT="$(cat <<'PROMPT'
あなたは SalesAnchor プロジェクトの Architect エージェントです。
Planner Package が実装可能かどうかを判定し、Generator に渡す前の最終検査を行ってください。

必須ルール:
- 実装はしないこと
- 追加調査はしないこと
- `APPROVE` / `REVISE` / `REJECT` のいずれかで返すこと
- 受け入れ基準、リスク、PO 承認要否を明示すること
- 出力は schema 準拠の review にすること
PROMPT
)"
    SANDBOX_MODE="read-only"
    ;;
  reviewer)
    ROLE_PROMPT="$(cat <<'PROMPT'
あなたは SalesAnchor プロジェクトの Reviewer エージェントです。
Generator が作成した変更を監査し、Reviewer 判定を返してください。

必須ルール:
- 実装はしないこと
- Playwright は実行しないこと
- コード品質、セキュリティ、保守性の観点でレビューすること
- sprint review と external PR review のどちらかを明示すること
- 出力は review-package に沿った内容にすること
PROMPT
)"
    SANDBOX_MODE="read-only"
    ;;
  evaluator)
    ROLE_PROMPT="$(cat <<'PROMPT'
あなたは SalesAnchor プロジェクトの Evaluator エージェントです。
Generator の変更を実際にアプリを動かして検証し、評価結果を返してください。

必須ルール:
- 実装はしないこと
- Generator がスプリントを完了していることを前提にすること
- Playwright などの実行証拠を取ること
- acceptance criteria ごとに結果を明示すること
- 出力は evaluation-package に沿った内容にすること
PROMPT
)"
    SANDBOX_MODE="workspace-write"
    ;;
  *)
    echo "❌ 未対応の role: $ROLE"
    echo "   対応 role: research / planner / architect / reviewer / evaluator"
    exit 1
    ;;
esac

if [[ $# -gt 0 ]]; then
  USER_PROMPT="$*"
else
  if [[ -t 0 ]]; then
    echo "❌ プロンプトを指定してください"
    exit 1
  fi
  USER_PROMPT="$(cat)"
fi

FULL_PROMPT="${ROLE_PROMPT}

${USER_PROMPT}"

cd "$REPO_ROOT"
printf '%s\n' "$FULL_PROMPT" | "$CODEX_BIN" exec --sandbox "$SANDBOX_MODE" --cd "$REPO_ROOT" -
