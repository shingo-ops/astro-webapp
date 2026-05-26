# CLAUDE.md

チーム共通の真実のみ。個人設定は `~/.claude/CLAUDE.md`、初期セットアップは `docs/onboarding/claude-code.md`。

---

## プロジェクト前提

- **PO**: しんごさん（`shingo-ops`）— 本番アクセス・ADR起案・不可逆操作の最終判断
- **Dev**: Hikky-dev（Claude Code）— 設計・実装・PR起票
- **事業**: Sales Anchor (salesanchor) — B2B SaaS CRM（HIGH LIFE JPN / Treasure Island JP）
- **スタック**: Python 3.12 / FastAPI / PostgreSQL 16 | React 18 + TypeScript + Vite | Astro | Docker + さくらVPS
- **本番 URL**: App `https://app.salesanchor.jp/` / API `https://api.salesanchor.jp/` / LP `https://salesanchor.jp/`
- **Legacy**: `https://jarvis-claude.uk/`（並行稼働中・**独断削除禁止、PO確認必須**）
- **仕様書**: `salesanchor_system_overview.docx` 他 3 冊（リポジトリ外・PO から入手）
- **設計判断**: `docs/adr/ADR-NNN-*.md` で起案。メモリ・チャット履歴を根拠にしない

---

## VPS コンテナの落とし穴

- `/app` は書込不可 → 出力先は `/tmp`
- `docker compose cp backend:/tmp/...` は使えない（tmpfs）→ `docker compose exec -T backend cat /tmp/xxx > host_file`
- コンテナ再起動で `/tmp` は消える

---

## 不可逆操作は必ず PO 確認

DROP TABLE / 大量DELETE / `rm -rf` / `git reset --hard` / `git push --force`（main/develop） / 本番Docker volume削除 / secrets変更 / Cloudflare・Firebase等の外部GUI操作 / `.github/workflows/workflow-lint.yml` の変更 / `gh api` による Branch Protection・Ruleset・Required Status Check の変更・削除

---

## ブランチ運用ルール

- 作業前に `develop` から `feature/morimoto/<英語で簡潔>` ブランチを作成
- **AI エージェント並行作業時は必ず** `bash scripts/new-worktree.sh feature/morimoto/<topic>` で独立ディレクトリを作成（ブランチ切り替えによる編集消失 P5 防止。詳細: `docs/PARALLEL_TERMINAL_GUIDE.md`）
- `develop` / `main` への直接コミット禁止
- 完了後 `gh pr create` でPR作成 → レビュー後 `develop` へマージ
- **develop → main も PR 経由**（直push禁止・Branch Protection で強制）
  - `gh pr create --base main --head develop` を起票 → しんごさんがマージ
  - 緊急時は admin のみ bypass 可（`docs/BRANCH_PROTECTION_SETUP.md` §4 に記録）

---

## 実装フロー（ADR-012）

| 担当 | 役割 |
|------|------|
| PO | What（何を・なぜ・ユーザー価値・事業制約） |
| Web Claude | ADR に翻訳、見落とし指摘 |
| Claude Code | How 全権（技術選択・実装・テスト・PR） |

ADR は What/Why/Scope のみ記述（実装手順 How は書かない）。`claude-pipeline.yml` が自動起動。詳細: `docs/adr/ADR-012-what-how-separation.md`

---

## i18n 強制（ADR-027）

全 UI 文字列は `t("key")` 経由（JSX / aria-label / placeholder / title すべて）。`ja.json` と `en.json` は同一キー必須。ハードコード日本語は絶対禁止。詳細: `docs/adr/ADR-027-ui-internationalization.md`、grep セルフチェック: `frontend/CLAUDE.md`

---

## データ手動 DB INSERT の原則禁止（ADR-025）

**本番運用フェーズ移行後に effective**（現在は開発フェーズのため直接INSERT/UPDATE は継続）。ただし常時厳禁: 暗号化済シークレット（`*_token_encrypted`）の手動投入 / destructive操作（DROP TABLE等）のPO確認なし実行。詳細: `docs/adr/ADR-025_meta_integration_operational_hardening.md`

---

## このファイルにルールを追加する前に

以下に順番に答える:

1. CI / ESLint / Husky が既に強制しているか？ → YES: **書かない**（CSS変数・アイコン・デザイントークン規約はこれ）
2. `frontend/` だけに関係するか？ → YES: **`frontend/CLAUDE.md`** に追加
3. `backend/` だけに関係するか？ → YES: **`backend/CLAUDE.md`** に追加
4. frontend と backend 両方に等しく関係するか？ → YES: **このファイル** に追加（i18n 等）
5. Generator / Evaluator / Reviewer の動作手順か？ → YES: **`~/.claude/agents/`** の該当ファイルに追加
6. `~/.claude/rules/` に同等の内容が既にあるか？ → YES: **書かない**（Git workflow・coding-style 等）
7. 全セッションで Claude が知る必要があるか？ → NO: **書かない**（ADRリンクか docs/ 参照で十分）
8. 上記をすべて通過した場合のみ追加。既存セクションへの統合を最優先（新セクション追加は最後の手段）。

**ファイル全体が 120 行を超えたら `frontend/scripts/check-claude-size.js` が CI / pre-commit でブロックする。**

---

## ルール所在マップ（SSoT索引）

| ルール | 設定ファイル（SSoT） | 機械強制 |
|--------|---------------------|----------|
| ブランチ運用 | このファイル | Branch Protection Ruleset |
| i18n 強制 | このファイル §i18n + ADR-027 | ESLint |
| デザイントークン | `frontend/CLAUDE.md` + ADR-067 | ESLint / `check:all` |
| フロントカバレッジ閾値 | `frontend/vite.config.ts` | `frontend-check.yml` |
| バックエンドカバレッジ閾値 | `backend/pyproject.toml` | `test.yml` |
| ADR 一覧 | `docs/adr/README.md`（自動生成） | `adr-index-check.yml` |
| アイコン管理 | `frontend/CLAUDE.md` §アイコン | ESLint |
| テナントスキーマ | `backend/CLAUDE.md` + ADR-072 | `lint-tenant-schema.yml` |
| CSS 変数/ダークモード | ADR-067 | `check:css-*` / ESLint |
