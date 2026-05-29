#!/usr/bin/env bash
# =============================================================================
# codex-generator.sh — Codex を Generator エージェントとして起動するラッパー
# =============================================================================
# 使い方:
#   bash scripts/codex-generator.sh              # 対話モード（推奨）
#   bash scripts/codex-generator.sh --auto       # 非対話モード（自動承認）
#   bash scripts/codex-generator.sh --exec       # 非対話モード（codex exec）
#   bash scripts/codex-generator.sh --smoke      # smoke 検証（no-op）
#
# Claude Code の "次のスプリントを実装して" に相当する Codex 版コマンド。
# スペック (.claude-pipeline/spec.md) を読み込んで Codex に渡す。
# =============================================================================

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
SPEC_FILE="$REPO_ROOT/.claude-pipeline/spec.md"
CODEX_BIN="${HOME}/.npm-global/bin/codex"
EXEC_MODE="0"
SMOKE_MODE="0"

# ────────────────────────────────────────────────────────────────────────────
# 前提チェック
# ────────────────────────────────────────────────────────────────────────────
if [[ ! -x "$CODEX_BIN" ]]; then
  echo "❌ Codex CLI が見つかりません: $CODEX_BIN"
  echo "   npm install -g @openai/codex を実行してください"
  exit 1
fi

# 認証トークン期限チェック（3日以内で警告）
bash "$REPO_ROOT/scripts/codex-auth-check.sh"

if [[ ! -f "$SPEC_FILE" ]]; then
  echo "❌ スペックファイルが見つかりません: $SPEC_FILE"
  echo "   Planner でスプリントスペックを作成してください"
  exit 1
fi

# ────────────────────────────────────────────────────────────────────────────
# モード選択
# ────────────────────────────────────────────────────────────────────────────
APPROVAL_POLICY="on-request"
MODE_LABEL="対話モード（各コマンドの承認が必要）"

if [[ "${1:-}" == "--auto" ]]; then
  APPROVAL_POLICY="untrusted"
  MODE_LABEL="自動モード（信頼済みコマンドは自動承認）"
elif [[ "${1:-}" == "--exec" ]]; then
  EXEC_MODE="1"
  MODE_LABEL="非対話モード（codex exec）"
elif [[ "${1:-}" == "--smoke" ]]; then
  EXEC_MODE="1"
  SMOKE_MODE="1"
  MODE_LABEL="smoke モード（no-op report）"
fi

# ────────────────────────────────────────────────────────────────────────────
# 起動
# ────────────────────────────────────────────────────────────────────────────
echo "🤖 Codex Generator 起動"
echo "   モード : $MODE_LABEL"
echo "   スペック: $SPEC_FILE"
echo ""

if [[ "$SMOKE_MODE" == "1" ]]; then
  echo "🧪 Codex Generator smoke validation"
  echo "   status : no-op"
  echo "   note   : Codex を起動せず、Generator ラッパーの起動経路のみ確認"
  echo "   result : change-free exit"
  exit 0
fi

PROMPT="$(cat <<'PROMPT_EOF'
あなたは salesanchor プロジェクトの Generator エージェントです。
以下のスプリントスペックを読んで実装してください。

## 実行ルール（順番通りに従うこと）

1. .claude-pipeline/active-work.md を確認し、同一機能エリアの IN_PROGRESS がないか確認。
   重複があれば STOP してユーザーに報告すること。

2. 以下のコマンドでワークツリーを作成（スプリント番号・テーマ名から命名）:
   bash scripts/new-worktree.sh feature/morimoto/<英語で簡潔なトピック>

3. ワークツリーディレクトリに移動して実装する。

4. 実装後、品質チェック:
   - フロントエンド: cd frontend && npm run check:all && npm run test:unit
   - バックエンド  : cd backend && make lint-ci
   （make test は docker compose up -d postgres redis が必要な場合のみ）

5. git add + git commit -m "feat: <説明>"

6. bash scripts/validate-pr-ownership.sh を実行して確認。

7. git push origin HEAD

8. bash scripts/gh-pr-create-safe.sh でPRを作成（--base develop は自動付与）。

## 重要ルール
- i18n: 全 UI 文字列は t("key") 経由。ja.json + en.json に同キー必須。
- CSS: ハードコード色・値禁止。CSS 変数 (var(--xxx)) を使うこと。
- 不可逆操作（DROP TABLE / git push --force / rm -rf 等）は実行禁止。

## スプリントスペック

PROMPT_EOF
)"

if [[ "$SMOKE_MODE" == "1" ]]; then
  PROMPT="$(cat <<'PROMPT_EOF'
あなたは salesanchor プロジェクトの Generator エージェントです。
これは smoke 検証です。実装はせず、変更なしで終了してください。

必須ルール:
- ファイル変更をしないこと
- git add / commit / push / PR 作成をしないこと
- 既存スプリントや spec の実装判断をしないこと
- 変更が必要だと判断しても、ここでは実行せず blocker として報告すること

出力:
- smoke validation の短いレポート
- 変更なしで終了した事実
- 必要なら blocker のみ
PROMPT_EOF
)"
  FULL_PROMPT="$PROMPT"
else
  # スペック本文を追記
  FULL_PROMPT="${PROMPT}
$(cat "$SPEC_FILE")"
fi

# Codex 起動（salesanchor ルートから）
cd "$REPO_ROOT"
if [[ "$EXEC_MODE" == "1" ]]; then
  printf '%s\n' "$FULL_PROMPT" | "$CODEX_BIN" exec --sandbox workspace-write --cd "$REPO_ROOT" -
else
  "$CODEX_BIN" \
    --sandbox workspace-write \
    --ask-for-approval "$APPROVAL_POLICY" \
    --cd "$REPO_ROOT" \
    "$FULL_PROMPT"
fi
