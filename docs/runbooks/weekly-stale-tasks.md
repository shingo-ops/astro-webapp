# weekly-stale-tasks ワークフロー 運用 Runbook

対象ワークフロー: `.github/workflows/weekly-stale-tasks.yml`
関連スクリプト: `scripts/check-stale-tasks.py`, `scripts/notify/discord-owner-ping.sh`

---

## 概要

毎週月曜 11:00 JST（UTC 02:00）に `tasks/todo.md` の「進行中」テーブルを走査し、
7日以上更新のないタスクを Discord #owner-ping チャンネルに通知する。

---

## 失敗時の診断手順

### 1. 失敗ランを特定する

```bash
gh run list --workflow=weekly-stale-tasks.yml --limit=10
```

### 2. ランの詳細を確認する

```bash
gh run view <RUN_ID>
```

出力に "This run likely failed because of a workflow file issue." が含まれる場合は
下記「ワークフローファイル起因の失敗」を参照。

### 3. ジョブログを取得する

```bash
gh run view <RUN_ID> --log
```

---

## よくある失敗原因と対処

### A. `DISCORD_WEBHOOK_SCHEDULED_REPORT` シークレットが未設定

**症状**: ログに `ERROR: DISCORD_WEBHOOK_OWNER_PING is not set` が出力される。

**確認コマンド**:
```bash
gh secret list | grep DISCORD_WEBHOOK_SCHEDULED_REPORT
```

**対処**: GitHub リポジトリの Settings > Secrets and variables > Actions から
`DISCORD_WEBHOOK_SCHEDULED_REPORT` にDiscord Webhook URLを設定する。

エスカレーション先: しんごさん（PO）— Discord チャンネルの Webhook URL を保有。

---

### B. `tasks/todo.md` が存在しない、または「進行中」セクションがない

**症状**: スクリプトが `SKIP: tasks/todo.md not found` を出力してexit 0で終了する（失敗にならない）。

**対処**: `tasks/todo.md` に以下フォーマットの「進行中」セクションが存在するか確認:

```markdown
## 進行中

| タスク | 担当 | ... | 更新日 |
|--------|------|-----|--------|
| タスク名 | owner | ... | YYYY-MM-DD |
```

---

### C. "This run likely failed because of a workflow file issue"

**症状**: ジョブが0件でワークフロー全体が即座に failure になる。

**原因と対処**:

1. **ワークフローファイルの YAML 構文エラー**
   ```bash
   python3 -c "import yaml; yaml.safe_load(open('.github/workflows/weekly-stale-tasks.yml'))"
   ```
   エラーが出た場合は構文を修正してコミット。

2. **feature ブランチ上のワークフローが default branch と異なる**
   GHA の `schedule` ジョブは default branch（`main`）のワークフロー定義で動く。
   feature ブランチで `on:` に `push` がある場合は不要な起動が発生する。
   `weekly-stale-tasks.yml` の `on:` は `schedule` と `workflow_dispatch` のみにする。

3. **参照スクリプトの不在**
   feature ブランチで `scripts/check-stale-tasks.py` が欠落していると失敗する。
   ```bash
   git show origin/develop:scripts/check-stale-tasks.py > scripts/check-stale-tasks.py
   ```

---

### D. Discord 通知は送られたがタスクが正しく検出されない

**症状**: 明らかに 7日以上更新なしのタスクが検出されない。

**ローカルで再現**:
```bash
python3 scripts/check-stale-tasks.py
```

**確認ポイント**:
- `tasks/todo.md` の「進行中」テーブルの 6 列目（0-indexed で col[5]）が `YYYY-MM-DD` 形式か確認
- 列数が 6 列以上あるか確認（`len(cols) < 6` でスキップされる）

---

## 手動実行（テスト用）

```bash
gh workflow run weekly-stale-tasks.yml
```

実行結果の確認:
```bash
gh run list --workflow=weekly-stale-tasks.yml --limit=3
gh run view <RUN_ID> --log
```

---

## エスカレーション基準

| 状況 | 対応者 |
|------|--------|
| YAML 構文エラー / スクリプト欠落 | Hikky-dev（Claude Code）が修正 PR を起票 |
| Discord Webhook URL の設定・更新 | しんごさん（PO）のみ実施 |
| `tasks/todo.md` フォーマット崩れ | 最後に編集したセッションが修正 |
| 3週連続失敗 | しんごさんに Discord DM でエスカレーション |
