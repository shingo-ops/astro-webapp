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

## Codex AI Agent 運用

長い Agent Prompt は禁止。実行時は下記 Runtime Prompt だけを使い、詳細定義は `docs/agents/`、出力形式は `docs/schemas/` を参照する。全 Agent は秘密情報を読まない・書かない。`.env`、`node_modules`、`.next`、`dist`、`build`、`coverage` は探索禁止。

### 共通ルール

- repo 全体探索は禁止。必要な場合は理由・対象パス・上限（例: `docs/adr` のみ、最大 20 件）を明記し、PO または作業依頼者の確認を取る
- `o4-mini` は使用禁止。デフォルトは `gpt-5`、深い調査・設計・Governance のみ `gpt-5.5`
- Agent 定義と Schema を再貼付しない。参照パスだけ渡す

### Runtime Prompts

| Agent | Runtime Prompt |
|-------|----------------|
| Research | Agent: Research. Reference: `docs/agents/research.md`. Output: `docs/schemas/research-package-v1.yaml`. Produce an Evidence Package only. No implementation, design, or governance decision. |
| Planner | Agent: Planner. Reference: `docs/agents/planner.md`. Input: `research-package-v1` only. Output: `planner-package-v1`. Convert evidence into a PO-decision plan. No research, implementation, review, governance, or Playwright. Next: Architect. |
| Architect | Agent: Architect. Reference: `docs/agents/architect.md`. Input: `planner-package-v1`. Output: `architect-review-v1`. Decision: `APPROVE` / `REVISE` / `REJECT`. No implementation, research, PR review, Playwright, or governance. |
| Generator | Agent: Generator. Reference: `docs/agents/generator.md`. Input: `planner-package-v1` + `architect-review-v1`. Required: Architect `APPROVE` + PO Approval true. Output: `generator-result-v1`. Modify only approved scope. |
| Reviewer | Agent: Reviewer. Reference: `docs/agents/reviewer.md`. Input: Planner + Architect + PO Approval + Generator Result. Output: `review-package-v1`. Audit implementation compliance only. No implementation, Playwright, external research, or new test design. |
| Evaluator | Agent: Evaluator. Reference: `docs/agents/evaluator.md`. Input: Planner + Architect + Generator Result + Review Package. Required: Reviewer `APPROVED`. Output: `evaluation-package-v1`. Role: Playwright / acceptance evidence only. |
| Governance | Agent: Governance. Reference: `docs/agents/governance.md`. Input: Evidence Registry, ADR, CI Metrics, Agent Metrics, Token Metrics. Output: `governance-decision-v1`. Schedule: Weekly / Monthly / Policy-specific. Role: periodic effectiveness review and standardization owner. |

---

## 重要: このファイルの自動更新ルール

Claude Code がチームルール・ADR・技術制約に関わる重要な決定をメモリに保存する際、
Codex にも必要と判断した内容は、このファイル（またはサブディレクトリの AGENTS.md）を同時に更新すること。

更新トリガー例: ブランチ命名規則の変更 / i18n ルール変更 / 新規必須チェック追加 / ADR による技術制約変更
