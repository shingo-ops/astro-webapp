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

## ブランチ運用ルール

- `develop` から `feature/morimoto/<英語で簡潔>` ブランチを作成
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

## 重要: このファイルの自動更新ルール

Claude Code がチームルール・ADR・技術制約に関わる重要な決定をメモリに保存する際、
Codex にも必要と判断した内容は、このファイル（またはサブディレクトリの AGENTS.md）を同時に更新すること。

更新トリガー例: ブランチ命名規則の変更 / i18n ルール変更 / 新規必須チェック追加 / ADR による技術制約変更
