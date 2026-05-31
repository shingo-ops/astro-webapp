# ADR-082: Generator Executor 選択 + Codex→Claude Code 自動フォールバック

| 項目 | 内容 |
|------|------|
| ステータス | Accepted |
| 作成日 | 2026-05-30 |
| 起案 | Claude Code (Hikky-dev) / しんごさん（PO） |
| 承認 | しんごさん（PO） |
| 関連 ADR | ADR-056（Human-in-the-Loop 最小化） / ADR-012（What/How 分離） |

---

## What

`claude-pipeline.yml` の Generator ステージ（`claude-worker` / `regenerate` ジョブ）に
`generator_executor` input（`auto` / `codex` / `claude`）を追加し、
Codex が利用不可の場合に Claude Code へ自動フォールバックする仕組みを導入する。

---

## Why

### 背景

- Codex（OpenAI CLI）を Generator 代替として試験採用（ADR 未記録の口頭決定 → 本 ADR で正式化）
- Codex はサードパーティサービスのため可用性が変動する（API 障害・CLI 未インストール・レート制限）
- Codex 不在でパイプラインが止まると PO が手動介入する必要があり、ADR-056 の自動化目標に反する

### 解決策

`generator_executor` 入力で実行エンジンを切り替え可能にし、`auto` モードでは Codex を優先しつつ失敗時は Claude Code にフォールバックする。

---

## Scope

- `.github/workflows/claude-pipeline.yml`（`claude-worker` / `regenerate` ジョブのみ）
- Reviewer / Evaluator / Governance ジョブは変更なし（引き続き Claude Code 専任）

---

## 設計詳細

### generator_executor の選択肢

| 値 | 動作 |
|----|------|
| `auto`（デフォルト） | `codex` コマンドが存在すれば Codex を試行。失敗または不在なら Claude Code に切り替え |
| `codex` | Codex 専用。失敗時はジョブ失敗（フォールバックなし） |
| `claude` | Claude Code 専用（従来の動作と同一） |

### フォールバック条件（auto モード）

1. `command -v codex` が失敗 → Claude Code に直接スイッチ
2. `codex --approval-mode full-auto "..."` が非ゼロ終了 → Claude Code にスイッチ
3. いずれのケースも `GENERATOR_FALLBACK=true` を `$GITHUB_ENV` に書き込み、後続の Discord 通知ステップが発動

### pull_request トリガー時の動作

`workflow_dispatch` 以外（PR の `synchronize` イベント）では `inputs.generator_executor` が存在しないため、
ワークフロー `env` レベルの `${{ inputs.generator_executor || 'auto' }}` が `auto` に解決される。
これにより regenerate ジョブも常に auto モードで動作する。

---

## Acceptance Criteria

- [ ] AC-1: `workflow_dispatch` 画面に `generator_executor` の選択肢（auto/codex/claude）が表示される
- [ ] AC-2: `auto` モードで `codex` コマンドが存在しない場合、Claude Code が実行されジョブが成功する
- [ ] AC-3: `auto` モードで `codex` が失敗した場合、Claude Code が実行されジョブが成功する
- [ ] AC-4: フォールバック発動時に Discord `DISCORD_WEBHOOK_PLAN_REVIEW` へ通知が飛ぶ
- [ ] AC-5: `claude` モードは従来の Claude Code 動作と同一である
- [ ] AC-6: `regenerate` ジョブでも同一フォールバックロジックが動作する

---

## トレードオフ

| 項目 | 内容 |
|------|------|
| 利点 | Codex 障害時もパイプラインが止まらない。executor を PR 単位で切り替え可能 |
| 欠点 | auto モードでは「どちらが実際に実行されたか」をログで確認する必要がある |
| 代替案 | Codex 専用モードのみ（フォールバックなし）→ 障害時に PO 介入が必要になるため不採用 |

---

## 運用

- デフォルトは `auto`。Codex が安定したら `codex` 専用モードに移行を検討する
- フォールバック Discord 通知が続く場合は Codex CLI のセットアップを確認する
  - `command -v codex` → インストール確認
  - Codex グローバル設定: `~/.codex/config.toml`
  - プロジェクト設定: `.codex/config.toml`
