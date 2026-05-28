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
| feature/morimoto/monitoring-tokens-sst | （記入してください） | 2026-05-26 23:45 | IN_PROGRESS | | |
| feature/morimoto/agent-pr-ownership-enforcement | 開発ルール強化（PR混入防止） | 2026-05-27 00:06 | REVIEW | 881 | |
| fix/morimoto/inbox-panel-split-dom | 受信箱 DOM構造修正 | 2026-05-27 17:10 | REVIEW | 839 | gitleaks CI再トリガー |
| feature/morimoto/pr-base-guard | PR誤マージ防止（gh-pr-create-safe） | 2026-05-27 | IN_PROGRESS | | |

| feature/morimoto/fix-pipeline-push-skip | CI pipeline push skip | 2026-05-27 | REVIEW | 1015 | |
| feature/morimoto/fix-active-work-format-check | （記入してください） | 2026-05-27 02:31 | IN_PROGRESS | | |
| feature/morimoto/auto-register-pr | （記入してください） | 2026-05-27 02:36 | IN_PROGRESS | | |
| feature/morimoto/fix-format-check-regex | （記入してください） | 2026-05-27 02:39 | IN_PROGRESS | | |
| feature/morimoto/fix-format-check-to-develop | （記入してください） | 2026-05-27 02:43 | IN_PROGRESS | | |
| release/develop-to-main-fix | リリース develop→main コンフリクト解消 | 2026-05-27 17:50 | IN_PROGRESS | | |
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
