# AGENTS.md

Codex 向けプロジェクト共通ルール。Claude Code の `CLAUDE.md` に対応するファイル。

---

## プロジェクト前提

- **PO**: しんごさん（`shingo-ops`）— 本番アクセス・ADR起案・不可逆操作の最終判断
- **Dev**: Claude Code (Hikky-dev) & Codex — 設計・実装・PR起票
- **事業**: Sales Anchor — B2B SaaS CRM（HIGH LIFE JPN / Treasure Island JP）
- **スタック**: Python 3.12 / FastAPI / PostgreSQL 16 | React 18 + TypeScript + Vite | Astro | Docker + さくらVPS
- **本番 URL**: App `https://app.salesanchor.jp/` / API `https://api.salesanchor.jp/` / LP `https://salesanchor.jp/`
- **Legacy**: `https://jarvis-claude.uk/`（並行稼働中・**独断削除禁止、PO確認必須**）
- **設計判断**: `docs/adr/ADR-NNN-*.md` を参照。チャット履歴を根拠にしない

---

## AI Agent Pipeline

Runtime pipeline は次の順序で運用する。

```text
Research -> Planner -> Architect -> PO Approval -> Generator -> Reviewer -> Evaluator -> GitHub CI
```

- `.claude/agents/*` が runtime の正本
- `docs/agents/*` は同じ役割の詳細参照
- Governance は runtime pipeline の外側で、標準化・継続改善・証跡確認を担う

---

## セットアップ & 実行コマンド

### Frontend
```bash
cd frontend && npm install
npm run dev        # 開発サーバー（port 5173）
npm run build      # 本番ビルド（tsc + vite build）
npm run check:all  # 全静的チェック（CI と同一）
npm run test:unit  # ユニットテスト（vitest）
```

### Backend
```bash
cd backend && pip install -r requirements-dev.txt
make lint-ci   # ruff / bandit / mypy（Docker 不要）

# pytest を含む全チェック（postgres + redis の Docker 起動が必要）
docker compose up -d postgres redis
make check     # lint-ci + pytest（カバレッジ 60% 以上）
```

> **重要**: `make test`（pytest）は Docker が必須。Docker なし環境では `make lint-ci` のみ実行すること。

---

## ブランチ運用ルール

- `develop` から `feature/morimoto/<英語で簡潔>` ブランチを作成
- Codex が自動生成するブランチ名（例: `abc123-codex/fix-inbox`）はそのまま使ってよい
- `develop` / `main` への直接コミット禁止
- 完了後 `gh pr create` で PR 作成 → レビュー後 `develop` へマージ
- `develop → main` も PR 経由（直 push 禁止・Branch Protection で強制）
  - マージ方法は必ず "Create a merge commit"（squash 禁止 — back-merge が永続発生するため）

---

## 設計レビューゲート

- 全 PR は `design-review-gate` で、信頼済みレビュアーの設計レビュー証跡を確認する
- 承認コメントまたは GitHub Review には `Design Review: APPROVED`、`Reviewer:`、最新 `Commit:`、`Scope:`、`Evidence:` を含める
- 追加 push 後は `Commit:` が古くなるため、最新 SHA に対して再承認が必要
- `design-review-gate` を Required Status Check に追加・削除する作業は Branch Protection / Ruleset 変更のため PO 確認必須

---

## 不可逆操作は必ず PO 確認

DROP TABLE / 大量 DELETE / `rm -rf` / `git reset --hard` / `git push --force`（main/develop）/
本番 Docker volume 削除 / secrets 変更 / Cloudflare・Firebase 等の外部 GUI 操作 /
`.github/workflows/workflow-lint.yml` の変更 / `gh api` による Branch Protection・Ruleset 変更・削除

---

## i18n 強制（ADR-027）

全 UI 文字列は `t("key")` 経由（JSX / aria-label / placeholder / title すべて）。
`ja.json` と `en.json` は同一キー必須。ハードコード日本語は絶対禁止。

---

## VPS コンテナの落とし穴

- `/app` は書込不可 → 出力先は `/tmp`
- `docker compose cp backend:/tmp/...` は使えない（tmpfs）→ `docker compose exec -T backend cat /tmp/xxx > host_file`
- コンテナ再起動で `/tmp` は消える

---

## サブディレクトリ別ルール

| ディレクトリ | ルールファイル |
|-------------|-------------|
| `frontend/` | `frontend/AGENTS.md` |
| `backend/`  | `backend/AGENTS.md`  |

---

## ADR 一覧

`docs/adr/README.md`（自動生成）— 設計上の疑問は必ずここから該当 ADR を確認すること。

---

## 重要: このファイルの自動更新ルール

Claude Code がチームルール・ADR・技術制約に関わる重要な決定をメモリに保存する際、
Codex にも必要と判断した内容は、このファイル（またはサブディレクトリの AGENTS.md）を同時に更新すること。

更新トリガー例: ブランチ命名規則の変更 / i18n ルール変更 / 新規必須チェック追加 / ADR による技術制約変更

---

## 引き継ぎルール（忘れ防止）

会話メモリ・チャット履歴を根拠にした状態宣言は禁止。一次情報（ファイル・コマンド出力・PR URL）のみ有効。

### セッション開始時の必須確認（3ファイル）

```bash
cat tasks/todo.md                          # 進行中タスク台帳（正本）
cat .claude-pipeline/active-work.md        # ブランチ占有状況
cat docs/runbooks/<関連runbook>.md         # スプリント状態
```

### 状態変化があったターンの終了前に更新する

1. `tasks/todo.md` の対象行の「現在地」「次の一手」「根拠」「更新日」を書き換える
2. スプリント完了・開始・ブロック時は `docs/runbooks/` の対象スプリント行も更新する
3. 新規タスクは `tasks/todo.md` に追加し、`docs/ai-agents/evidence-registry.md` に根拠を記録する

### 根拠の書き方

根拠列には以下のいずれかを記入する（「〜のはず」は不可）:

| 根拠の種類 | 書き方の例 |
|----------|----------|
| ファイル確認 | `cat tasks/todo.md` 実行済み |
| PR確認 | PR #1134 マージ確認済み |
| コマンド出力 | `docker compose ps` → 全コンテナ healthy |
| ADR | ADR-080 §Phase1 参照 |

### スクリプトによる自動検証

```bash
bash scripts/check-task-state.sh   # tasks/todo.md と runbook の構造チェック
```

CI（task-state-check.yml）が PR ごとに自動実行する。
