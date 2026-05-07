# Self-hosted Runner コマンドリファレンス

salesanchor の self-hosted runner（Hitoshi の Mac, agentName: `Hikky-dev-Mac`）操作に必要なコマンド集。

トラブル時・再登録時・日常確認に使う。背景は [`self-hosted-runner-credential-trap.md`](./self-hosted-runner-credential-trap.md)。

---

## 1. ローカル runner 操作（zsh エイリアス）

`~/.zshrc` に定義済（Hitoshi の Mac）:

| エイリアス | 実体 | 用途 |
|---|---|---|
| `runner-start` | `cd ~/actions-runner && nohup ./run.sh > runner.log 2>&1 &` | バックグラウンド起動 |
| `runner-status` | `ps aux \| grep -i Runner.Listener \| grep -v grep` | 稼働確認 |
| `runner-log` | `tail -f ~/actions-runner/runner.log` | ログ追従 |
| `runner-stop` | `pkill -f Runner.Listener` | 停止 |

## 2. ローカル runner 直接操作（生コマンド）

```bash
# 起動（対話モード／ターミナル占有）
cd ~/actions-runner && ./run.sh

# 起動（バックグラウンド）
cd ~/actions-runner && nohup ./run.sh > runner.log 2>&1 & disown

# 停止（gracefully）
kill -TERM <PID-of-run.sh>     # 親プロセスから順に伝播

# 強制停止（最後の手段）
pkill -9 -f Runner.Listener

# 状態詳細
ps aux | grep -E "Runner.Listener|run-helper.sh|/run\.sh" | grep -v grep
cat ~/actions-runner/.runner            # agentName, agentId, server URL
ls -la ~/actions-runner/_diag/ | head   # 直近 diag log
```

## 3. ログ確認・解析

```bash
# ローカル listener log
tail -f ~/actions-runner/runner.log
tail -100 ~/actions-runner/runner.log

# 最新の Worker (job 実行) ログ
ls -1t ~/actions-runner/_diag/Worker_*.log | head -1 | xargs tail -200

# Listener (接続) ログ
ls -1t ~/actions-runner/_diag/Runner_*.log | head -1 | xargs tail -100
```

## 4. GitHub 側状態確認（gh CLI）

```bash
# 直近 workflow run（status / conclusion）
gh run list --workflow="Claude Max Auto-Pipeline (Partner Subscription)" --limit 5 \
  --json databaseId,status,conclusion,createdAt,event,headBranch \
  -q '.[] | "\(.createdAt) | id=\(.databaseId) | \(.status)/\(.conclusion) | branch=\(.headBranch)"'

# 走行中ジョブ
gh run list --status in_progress --limit 5
gh run list --status queued --limit 5

# 特定 run の詳細
gh run view <RUN_ID> --json status,conclusion,jobs

# 特定 run のステップ別結果
gh run view <RUN_ID> --json jobs -q '.jobs[].steps[]|{name, conclusion}'

# 失敗ステップのみ生ログ取得
gh run view <RUN_ID> --log-failed

# 全ログ（grep 用）
gh run view <RUN_ID> --log | grep "Checkout Code"
gh run view <RUN_ID> --log | grep -E "Runner name|Machine name"
```

> **Note**: Hikky-dev は repo admin ではないため、`gh api .../runners` 系の admin API は 403。Runners 一覧などは Web UI (`https://github.com/shingo-ops/salesanchor/settings/actions/runners`) を使う。

## 5. Workflow dispatch（手動起動）

```bash
# 必ず --ref を指定（省略すると default branch = main で実行される！）
gh workflow run "Claude Max Auto-Pipeline (Partner Subscription)" \
  --ref develop \
  -f adr_files=docs/adr/ADR-NNN.md

# テスト用（no-op の ADR-999）
gh workflow run "Claude Max Auto-Pipeline (Partner Subscription)" \
  --ref develop \
  -f adr_files=docs/adr/ADR-999-pipeline-test.md

# 直前の dispatch 確認
gh run list --workflow="Claude Max Auto-Pipeline (Partner Subscription)" --limit 1

# dispatch 後にライブで進行をフォロー
gh run watch <RUN_ID>
```

## 6. 再登録 / 改名手順

```bash
# Step 0: 安全確認
gh run list --status in_progress      # 空であること
gh run list --status queued           # 空であること
ps aux | grep "Runner.Worker" | grep -v grep   # 空であること

# Step 1: registration token を Web UI から取得
# https://github.com/shingo-ops/salesanchor/settings/actions/runners/new
# → "AABBCC...XXXXX" の英数字部分をコピー（1時間で expire）

# Step 2: listener 停止
runner-stop

# Step 3: 旧登録解除
# ※ 同一 registration token を Step 4 でも再利用できる（remove と register で 2 回消費可）
cd ~/actions-runner
./config.sh remove --token <TOKEN>

# Step 4: 新名で再登録（Step 3 と同じ TOKEN でOK）
./config.sh \
  --url https://github.com/shingo-ops/salesanchor \
  --token <TOKEN> \
  --name "Hikky-dev-Mac" \
  --labels "self-hosted,macOS" \
  --unattended

# Step 5: 再起動
runner-start

# Step 6: 動作確認
cat ~/actions-runner/.runner | grep agentName    # "Hikky-dev-Mac" のはず
runner-status
gh workflow run "Claude Max Auto-Pipeline (Partner Subscription)" --ref develop \
  -f adr_files=docs/adr/ADR-999-pipeline-test.md
```

## 7. トラブル診断クイックチェック

```bash
# 「workflow が動かない」時の切り分け順序

# (1) リスナー生きてる？
runner-status
# → 出力なし: runner-start で起動

# (2) GitHub と接続されてる？
tail -20 ~/actions-runner/runner.log
# → "Listening for Jobs" があれば OK

# (3) ジョブを受け取った形跡は？
grep "Running job" ~/actions-runner/runner.log | tail -5

# (4) job 失敗の生ログ
gh run view <FAILED_RUN_ID> --log-failed

# (5) Checkout が失敗してる？
gh run view <FAILED_RUN_ID> --log | grep "Checkout Code" | grep -E "error|fatal" | head -10
```

## 8. PAT / Secret 関連

```bash
# PIPELINE_PAT rotation 期限チェック（90日サイクル, 2026-08-05 失効目安）
gh issue view 300 --repo shingo-ops/salesanchor

# secret の存在確認（中身は不可視）
gh api /repos/shingo-ops/salesanchor/actions/secrets --jq '.secrets[].name'

# secret 作成・更新は Web UI のみ:
# https://github.com/shingo-ops/salesanchor/settings/secrets/actions
```

---

## 関連 doc

- [`self-hosted-runner-credential-trap.md`](./self-hosted-runner-credential-trap.md) — 2026-05-07 の事故と PIPELINE_PAT 導入の経緯
- Issue #300 — PAT rotation リマインダー
- PR #299 — checkout に PIPELINE_PAT 明示渡し
