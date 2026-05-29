# Claude Code セットアップガイド（Sales Anchor / salesanchor 開発者向け）

このドキュメントは、本リポジトリで Claude Code を使って開発するためのオンボーディング手順をまとめたもの。

---

## 1. 設定の3層構造を理解する

Claude Code の設定は 3 層に分かれている。**チーム共通のものはリポジトリにコミットし、個人の好みはユーザーグローバルに置く** ─ この分離を守ること。

| 層 | 場所 | Git | 中身 |
|---|---|---|---|
| ユーザーグローバル | `~/.claude/CLAUDE.md`<br>`~/.claude/settings.json` | ❌ コミットしない | 個人の好み・通知・キーバインド・auto-memory |
| **プロジェクト共通** | `<repo>/CLAUDE.md`<br>`<repo>/.claude/settings.json`<br>`<repo>/.claude/agents/` | ✅ **コミット** | チーム前提・規約・専用エージェント |
| プロジェクトローカル | `<repo>/.claude/settings.local.json`<br>`<repo>/CLAUDE.local.md` | ❌ gitignore | 個人の上書き分 |

### やってはいけないこと
- 個人の好み（口調・通知・コマンド改行ルール等）を `<repo>/CLAUDE.md` に書かない
- VPS パスワード・API token・SSH鍵 を `CLAUDE.md` や `.claude/` に書かない（**GitHub Secrets 等の安全な場所に置く**）
- auto-memory ディレクトリ（`~/.claude/projects/...`）の中身をリポにコピーしない（個人の試行錯誤履歴）

---

## 2. 初回セットアップ（パートナー / 新規参画者向け）

### Step 1: Claude Code をインストール
```bash
npm install -g @anthropic-ai/claude-code
# または公式案内 https://claude.com/claude-code を参照
```

### Step 2: リポジトリをクローン
```bash
git clone https://github.com/shingo-ops/salesanchor.git
cd salesanchor
```

クローンするだけで `CLAUDE.md` と `.claude/` がチーム共通設定として自動的に効く。

### Step 3: gh / git の認証
```bash
gh auth login          # GitHub CLI（PR 作成・レビューに必要）
git config user.name  "<あなたの名前>"
git config user.email "<あなたのメール>"
```

### Step 4: 個人ローカル設定（任意）
個人の好み（口調・通知音声など）は `~/.claude/CLAUDE.md` に書く。本リポジトリの `CLAUDE.md` には触らない。

このプロジェクト内だけの個人上書きが必要なら `.claude/settings.local.json` を作る（gitignore 済）。

### Step 5: 必要な MCP サーバ（任意）
- **context7** — 外部ライブラリのドキュメント参照（推奨）
- **playwright** — E2E テスト・UI 検証で使用
- **voicevox** — hitoshi の音声通知用（個人）

設定方法は `claude mcp add` で各自登録。

---

## 3. リポジトリ専用エージェントの使い方

`.claude/agents/` にチーム共通のサブエージェントが定義されている。

| Agent | 役割 |
|---|---|
| `research` | 外部事例・成功/失敗パターンを Evidence Package にまとめる |
| `planner` | Evidence から意思決定可能な Plan Package を作る |
| `architect` | 実装前の妥当性確認と Generator 指示の作成 |
| `generator` | 承認済み範囲のみ実装する |
| `reviewer` | 実装の準拠監査を行う |
| `evaluator` | 実装を Playwright で検証、Pass/Fail 判定 |
| `governance` | 定期レビューで標準化・継続改善を判断する |

AEON ルートを使う場合は、まず [AEON Operation Guide](../ai-agents/aeon-operation.md) を読む。Claude Code の同じ terminal session から `bash scripts/aeon-dispatch.sh <role> ...` を呼ぶ。`research / planner / architect / reviewer / evaluator` は Codex に委譲し、`generator` は既存の Generator wrapper を使う。
まとめて進める場合は `bash scripts/aeon-delivery.sh [--generator=exec|auto|interactive] "..."` を使う。これで research → planner → architect → generator → evaluator → reviewer を同じ terminal session で順に回せる。
`main` へ昇格する場合は `bash scripts/aeon-release.sh [PR番号]` を使う。

呼び出し例:
- 「Planner で機能 X の仕様書を起こして」
- 「次のスプリント実装して」（Generator）
- 「Evaluator 走らせて」
- 「Reviewer 走らせて」 / 「PR #123 レビューして」
- 「`bash scripts/aeon-dispatch.sh research '...'` で証拠収集して」
- 「`bash scripts/aeon-delivery.sh '...'` で delivery flow を進めて」
- 「`bash scripts/aeon-release.sh` で main へ昇格して」

詳しくは各 `.claude/agents/*.md` のフロントマターを参照。

---

## 4. 開発フロー（要点）

詳細は `<repo>/CLAUDE.md` の「ブランチ運用ルール」を読むこと。要点:

1. `develop` から `feature/morimoto/<topic>` を切る（`<topic>` は作業内容を英語で簡潔に）
   - ADR pipeline 経由の自動実装は別途 `feature/shingo/adr-NNN-impl` が自動生成される
2. 直接 `develop` / `main` にコミットしない
3. PO Approval → Generator → Reviewer → Evaluator → GitHub CI の順で進める
4. Reviewer / Evaluator の結果を確認してから PR を起票・マージする
5. `develop → main` も必ず PR 経由（Branch Protection で物理ブロック）
6. 不可逆操作（DROP TABLE / `rm -rf` / force-push 等）は **PO 確認必須**

### タスク台帳（全員共通・必読）

作業開始前に必ず3つのファイルを確認する:

```bash
cat tasks/todo.md                        # 進行中タスク一覧（担当・現在地・次の一手）
cat .claude-pipeline/active-work.md      # 誰がどのブランチで作業中か
# 長期タスクの場合は関連 runbook も確認
# 例: cat docs/runbooks/monitoring-vps-migration.md | head -60
```

作業後に状態が変わったら `tasks/todo.md` の該当行を更新すること（更新日・現在地・次の一手）。
**更新しないと毎週月曜の Discord 通知で「放置タスク」として報告される。**

---

## 5. プロジェクト前提のクイックリファレンス

`<repo>/CLAUDE.md` の「プロジェクト前提」を必ず読むこと。特に以下は事故の原因になりやすい:

- **マルチテナント**: 本番は `tenant_code=highlife-jpn` のみ。`TENANT_CODE` 既定値の `test-corp` は空
- **VPS コンテナ**: `/app` 書込不可、`/tmp` は tmpfs で `docker compose cp` 不可
- **ドメイン**: `jarvis-claude.uk` 系の旧ドメインは独断削除禁止
- **Self-hosted runner**: `actions/checkout` に必ず `with: token: ${{ secrets.PIPELINE_PAT }}` を指定（理由は `docs/ops/self-hosted-runner-credential-trap.md`）

---

## 6. デザインシステム

フロントエンドの UI を触る前に必ず確認すること。

| ドキュメント | 内容 |
|------------|------|
| `docs/onboarding/design-system.md` | **入門（5分）** — デザイントークン・CSS 変数・Storybook の使い方 |
| `docs/design-system/storybook-i18n-policy.md` | Storybook stories での i18n の書き方 |
| `docs/adr/ADR-067-design-token-enforcement.md` | CI 強制ルールの詳細 |
| `docs/adr/ADR-073-design-system-kgi-rubric.md` | KGI ルーブリック（完成基準） |

```bash
# ローカルで全デザインシステムチェックを一括実行
cd frontend && npm run check:all

# 未使用トークン監査（CI ブロックなし・定期確認用）
cd frontend && npm run audit:unused-tokens
```

---

## 7. 困った時

- Claude Code 機能の質問: `/help`、または公式ドキュメント https://docs.claude.com/claude-code
- 仕様の判断に迷ったら: PO（しんごさん）に質問してから着手
- ADR 起案 / 大きな設計変更: `docs/adr/ADR-NNN-*.md` を起案
- Reviewer の動きが期待と違う: `.claude/agents/reviewer.md` の Mode A / B を確認
