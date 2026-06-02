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
| feature/morimoto/dev-workflow-improvements | 開発ワークフロー改善 | 2026-06-02 | DONE | #1383 | |
| feature/morimoto/invoice-issuer-path-fix | 請求書作成 発行者情報ボタンパス修正 | 2026-06-02 | DONE | #1387 | |

| feature/morimoto/pre-commit-active-work-exception | pre-commitフック例外追加 | 2026-06-02 | DONE | #1389 | |
| feature/morimoto/fix-release-pr-drawbacks | リリースPR弊害対策 | 2026-06-02 | DONE | #1386 | |
| feature/morimoto/fix-pre-commit-regex | pre-commit正規表現修正 | 2026-06-02 | DONE | #1393 | |
| feature/morimoto/discord-bot-adr | Discord Bot ADR-091 | 2026-06-02 | DONE | #1394 | |
| feature/morimoto/hook-test-ci | CIテスト追加（shellcheck・pytest） | 2026-06-02 | DONE | #1397 | |
| feature/morimoto/discord-bot-reconnect-fix | Discord接続ループ防止 | 2026-06-02 | DONE | #1398 | |
| feature/morimoto/discord-ticket-phase1 | ADR-091 KPI3 Phase 1+2 | 2026-06-02 12:53 | DONE | #1404 | |
| feature/morimoto/discord-ticket-phase3 | ADR-091 KPI3 Phase 3 | 2026-06-02 13:30 | DONE | #1406 | |
| feature/morimoto/discord-kpi4-announce | ADR-091 KPI4 アナウンス投稿 | 2026-06-02 14:00 | DONE | #1408 | |
| feature/morimoto/adr072-precommit | （記入してください） | 2026-06-02 14:11 | IN_PROGRESS | | |
| feature/morimoto/discord-kpi5-role-channel | ADR-091 KPI5 顧客規模別チャンネル・ロール連動 | 2026-06-02 14:20 | DONE | #1411 | |
| feature/morimoto/discord-kpi6-remove | ADR-091 KPI6 アプリからの顧客削除 | 2026-06-02 14:48 | DONE | #1413 | |
| feature/morimoto/claude-md-hierarchy | （記入してください） | 2026-06-02 14:55 | IN_PROGRESS | | |
| feature/morimoto/discord-kpi7-role-ui | ADR-091 KPI7 ロール同期ステータス UI | 2026-06-02 14:55 | DONE | #1416 | |
| feature/morimoto/discord-kpi7-status-fix | KPI7 バッジ synced→success 修正 | 2026-06-02 | DONE | #1418 | |
| feature/morimoto/discord-role-name-config | ロール名アプリ設定 | 2026-06-02 | DONE | #1419 | |
| feature/morimoto/fix-messaging-window-response-type | messaging_window HUMAN_AGENT タグ未承認バグ修正 | 2026-06-02 15:00 | IN_PROGRESS | | |
| feature/morimoto/ci-fix-deploy-retry | （記入してください） | 2026-06-02 15:28 | IN_PROGRESS | | |
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
