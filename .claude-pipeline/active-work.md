# Active Work Registry — 並列エージェント作業の唯一の真実（SSoT）

> **新しいターミナルで作業を開始する前に必ずこのファイルを確認すること。**
> 重複が見つかった場合は STOP → しんごさんに確認。

## ルール

| # | タイミング | 操作 |
|---|-----------|------|
| 1 | 作業開始前 | このファイルを読んで、同じ機能エリアで進行中の作業がないか確認する |
| 2 | Worktree 作成時 | `scripts/new-worktree.sh` が自動でエントリを追記する |
| 3 | PR マージ完了後 | 該当行を `DONE` に更新する（削除しない・ログとして残す） |
| 4 | 重複発見時 | STOP → しんごさんに確認してから開始する |

## 現在進行中の作業

| ブランチ名 | 担当機能エリア | 開始日時 | 状態 | PR# | 備考 |
|-----------|--------------|---------|------|-----|------|
| feature/morimoto/dev-workflow-improvements | 開発ワークフロー改善 | 2026-06-02 | IN_PROGRESS | | |
| feature/morimoto/invoice-issuer-path-fix | 請求書作成 発行者情報ボタンパス修正 | 2026-06-02 | IN_PROGRESS | | |

| feature/morimoto/pre-commit-active-work-exception | （記入してください） | 2026-06-02 10:40 | IN_PROGRESS | | |
| feature/morimoto/fix-release-pr-drawbacks | （記入してください） | 2026-06-02 10:42 | IN_PROGRESS | | |
---

## 記入例

```
| feature/morimoto/your-feature-name | 受信箱 UI    | 2026-05-26 10:00 | IN_PROGRESS |     | タブ1で作業中 |
| feature/morimoto/your-other-feature | スケジュール  | 2026-05-26 11:30 | REVIEW      | 923 | タブ2で作業中 |
```

## 状態の種類

| 状態 | 意味 |
|------|------|
| `IN_PROGRESS` | 現在作業中（Generator が動いている） |
| `REVIEW` | PR 提出済み・Reviewer/Evaluator 待ち |
| `BLOCKED` | 問題があり停止中（しんごさん確認待ち） |
| `DONE` | PR マージ完了（ログとして永続保持） |
