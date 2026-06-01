# Active Work Registry — 並列エージェント作業の唯一の真実（SSoT）

> **新しいターミナルで作業を開始する前に必ずこのファイルを確認すること。**
> 重複が見つかった場合は STOP → しんごさんに確認。

## ルール

| # | タイミング | 操作 |
|---|-----------|------|
| 1 | 作業開始前 | このファイルを読んで、同じ機能エリアで進行中の作業がないか確認する |
| 2 | Worktree 作成時 | `scripts/new-worktree.sh` が自動でエントリを追記する |
| 3 | PR マージ完了後 | 該当行を削除する（Generator または手動） |
| 4 | 重複発見時 | STOP → しんごさんに確認してから開始する |

## 現在進行中の作業

| ブランチ名 | 担当機能エリア | 開始日時 | 状態 | PR# | 備考 |
|-----------|--------------|---------|------|-----|------|
| feature/morimoto/standardize-agent-pipeline-defs | エージェント定義標準化 | 2026-05-29 | IN_PROGRESS | | |
| feature/morimoto/deploy-skip-migrations-frontend-only | デプロイ最適化 | 2026-05-30 | REVIEW | | ADR-082 フロントのみデプロイで DB migration を skip し所要時間短縮 |
| feature/morimoto/fix-profile-blank-phone-migration | プロフィール設定空白バグ修正 | 2026-05-31 | IN_PROGRESS | | deploy.yml から抜けていた Migration 083 を追加 |
| feature/morimoto/github-collector-metrics | GitHub collector metrics | 2026-05-29 20:48 | IN_PROGRESS | | |
| feature/morimoto/codex-research-planning-gaps | Codex research / planning gaps | 2026-05-30 00:37 | IN_PROGRESS | | |
| feature/morimoto/remove-design-review-gate | design review gate removal | 2026-05-30 05:39 | IN_PROGRESS | | |
| feature/morimoto/aeon-operation-guide-pr | AEON operation guide PR | 2026-05-30 05:42 | IN_PROGRESS | | |
| feature/morimoto/inbox-auto-select-first-conv | （記入してください） | 2026-05-30 21:46 | IN_PROGRESS | | |
| feature/morimoto/aeon-standardize | （記入してください） | 2026-05-30 21:47 | IN_PROGRESS | | |
| feature/morimoto/claude-dispatch-verify | （記入してください） | 2026-05-30 21:56 | IN_PROGRESS | | |
| feature/morimoto/fix-deploy-zero-downtime | （記入してください） | 2026-05-30 22:08 | IN_PROGRESS | | |
| feature/morimoto/governance-section-f | （記入してください） | 2026-05-31 10:57 | IN_PROGRESS | | |
| feature/morimoto/add-governance-agent | （記入してください） | 2026-05-31 10:59 | IN_PROGRESS | | |
| feature/morimoto/condition-standardize | inventory condition 16値正規化 | 2026-05-31 14:00 | IN_PROGRESS | | |
| feature/morimoto/codex-agent-dispatch | Codexエージェント自動委任 | 2026-05-31 | IN_PROGRESS | | |
| feature/morimoto/stylelint-phase2-error | stylelint error昇格 Phase2 | 2026-05-31 | IN_PROGRESS | | |
| feature/morimoto/back-merge-main-for-1262 | （記入してください） | 2026-05-31 17:20 | IN_PROGRESS | | |
| feature/morimoto/permit-danger-script | permit-danger.sh 実装 | 2026-05-31 | IN_PROGRESS | | |
| feature/morimoto/branch-protection-cleanup | （記入してください） | 2026-05-31 18:13 | IN_PROGRESS | | |
| feature/morimoto/unify-icon-btn-token | （記入してください） | 2026-05-31 20:36 | IN_PROGRESS | | |
| feature/morimoto/account-settings-ui | アカウント設定UI改善 | 2026-05-31 | IN_PROGRESS | | |
| feature/morimoto/profile-section-kana-fields | プロフィール設定かなフィールド追加 | 2026-05-31 | IN_PROGRESS | | |
| feature/morimoto/move-templates-to-inbox-header | テンプレートをサイドバーから受信箱ヘッダーへ移動 | 2026-05-31 | IN_PROGRESS | | |
| feature/morimoto/hub-shell-unification | hub-shell 共通化・背景透過 | 2026-05-31 | IN_PROGRESS | | |
| feature/morimoto/inventory-picker-outside-click | 商品候補ドロップダウンを外側クリックで閉じる修正 | 2026-06-01 | IN_PROGRESS | | |
---

## 記入例

```
| feature/morimoto/inbox-redesign | 受信箱 UI    | 2026-05-26 10:00 | IN_PROGRESS |     | タブ1で作業中 |
| feature/morimoto/schedule-fix   | スケジュール  | 2026-05-26 11:30 | REVIEW      | 923 | タブ2で作業中 |
```

## 状態の種類

| 状態 | 意味 |
|------|------|
| `IN_PROGRESS` | 現在作業中（Generator が動いている） |
| `REVIEW` | PR 提出済み・Reviewer/Evaluator 待ち |
| `BLOCKED` | 問題があり停止中（しんごさん確認待ち） |
