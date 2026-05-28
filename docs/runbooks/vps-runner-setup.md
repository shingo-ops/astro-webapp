# VPS runner セットアップ Runbook (ADR-078)

さくらVPS（Ubuntu、IP: `49.212.137.46`）に GitHub Actions self-hosted runner を登録し、`salesanchor-vps` ラベルを付与する手順書。

**対象 ADR**: ADR-078  
**対象 workflow**: `qa-smoke.yml`, `external-state-snapshot.yml`  
**自動化スクリプト**: `scripts/setup-vps-runner.sh`（Step 3〜5 を自動実行）  
**所要時間目安**: 30〜60 分  
**実施予定日**: 2026-06-15 前後

---

## 事前確認チェックリスト

作業開始前に以下をすべて確認する。

- [ ] さくらVPS への SSH アクセスが手元から可能（`ssh <USER>@49.212.137.46`）
- [ ] GitHub リポジトリの **Admin 権限**を持つしんごさんアカウントで `gh` CLI 認証済み（`gh auth status`）
- [ ] VPS 側で `curl` が使用可能（VPS 上で `curl --version`）
- [ ] VPS のディスク空き容量が 2GB 以上ある（VPS 上で `df -h /`）
- [ ] VPS のメモリ空きが 1GB 以上ある（VPS 上で `free -h`）。不足する場合は **別サーバーを用意する**（下記「メモリ不足時の対処」参照）
- [ ] VPS の OS が Ubuntu であること（VPS 上で `lsb_release -a`）

---

## Step 1: VPS 接続確認

```bash
# ローカルから VPS への SSH 接続
ssh <VPS_USER>@49.212.137.46

# 接続後、OS・スペック確認
lsb_release -a        # Ubuntu 確認
uname -m              # x86_64 を期待（→ linux-x64 バイナリを使用）
nproc                 # CPU コア数
free -h               # メモリ確認
df -h /               # ディスク空き確認

# インターネット接続確認
curl -s https://api.github.com | python3 -c "import sys,json; d=json.load(sys.stdin); print('OK:', d.get('current_user_url','connected'))"
```

**確認ポイント**: `uname -m` が `x86_64` なら後続のバイナリは `linux-x64` 版を使用する。

---

## Step 2: メモリ確認

> Playwright headless Chromium は約 706MB のメモリを消費する。
> **メモリ不足の場合はスワップ増設ではなく、別サーバーを用意する方針**（しんごさん決定 2026-05-28）。

```bash
# VPS 上で実行
free -h
# → "available" が 1GB 以上あれば続行
```

**メモリ不足時の対処**: さくらVPS コントロールパネルから追加サーバー（1GB RAM 以上）を契約し、そちらに runner を登録する。IP アドレスが変わった場合は本 runbook の `49.212.137.46` を置き換えること。

---

## Step 3〜5 の自動実行（推奨）

Step 3〜5（バイナリ取得 → config.sh → systemd サービス化）は `setup-vps-runner.sh` で一括実行できる。

```bash
# 1. ローカルでトークン取得
RUNNER_TOKEN=$(gh api --method POST \
  /repos/shingo-ops/salesanchor/actions/runners/registration-token --jq '.token')

# 2. トークンを VPS にセキュアに渡してスクリプト実行
#    ※ トークンは環境変数で渡す（CLIオプションは ps aux で見えるため禁止）
ssh <VPS_USER>@49.212.137.46 "RUNNER_TOKEN='${RUNNER_TOKEN}' bash -s" \
  < scripts/setup-vps-runner.sh
```

手動で実行したい場合は以下 Step 3〜5 を参照。

---

## Step 3: runner バイナリのダウンロード・インストール

```bash
# VPS 上で実行
mkdir -p ~/actions-runner && cd ~/actions-runner

# 最新バージョンを自動取得
RUNNER_VERSION=$(curl -s https://api.github.com/repos/actions/runner/releases/latest \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['tag_name'].lstrip('v'))")
echo "Runner version: ${RUNNER_VERSION}"

# バイナリをダウンロード（linux-x64 版）
curl -o actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz -L \
  "https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz"

# チェックサム検証
echo "$(curl -sL https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz.sha256)" \
  | shasum -a 256 -c

# 展開
tar xzf ./actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz

# 確認（config.sh / run.sh / svc.sh が存在すれば OK）
ls -la | grep -E "config|run|svc"
```

---

## Step 4: 登録トークン取得 → `./config.sh` 実行

### 4-1. トークン取得（ローカルで実行）

> トークンの有効期限は **1 時間**。取得後すぐに Step 4-2 を実行すること。

```bash
# ローカル（しんごさん権限の gh CLI）で実行
gh api \
  --method POST \
  -H "Accept: application/vnd.github+json" \
  /repos/shingo-ops/salesanchor/actions/runners/registration-token \
  --jq '.token'
# → 出力されるトークン文字列をコピーしておく
# 例: AAAAABBBBCCCCDDDDEEEE12345
```

### 4-2. runner 設定（VPS で実行）

```bash
# VPS 上の ~/actions-runner で実行
cd ~/actions-runner

./config.sh \
  --url https://github.com/shingo-ops/salesanchor \
  --token <4-1で取得したトークン> \
  --name salesanchor-vps \
  --labels self-hosted,Linux,X64,salesanchor-vps \
  --work _work \
  --unattended

# 成功すると "Settings Saved." が表示される
```

**動作確認（オプション）**:
```bash
# runner を一時的に手動起動して "Listening for Jobs" が出るか確認
./run.sh &
sleep 5
kill %1
```

---

## Step 5: systemd サービス化（自動起動）

```bash
# VPS 上で実行（sudo 権限が必要）
cd ~/actions-runner

# systemd service のインストール
sudo ./svc.sh install

# サービスの起動
sudo ./svc.sh start

# 状態確認
sudo ./svc.sh status

# 自動起動（enable）確認
sudo systemctl is-enabled "$(sudo ./svc.sh status 2>&1 | grep -oE 'actions\.runner\.[^ ]+\.service' | head -1)"
# → "enabled" と表示されれば OK
```

**サービス名の例**: `actions.runner.shingo-ops-salesanchor.salesanchor-vps.service`

---

## Step 6: GitHub 上でランナー状態確認

### ブラウザで確認

1. `https://github.com/shingo-ops/salesanchor/settings/actions/runners` を開く
2. `salesanchor-vps` が **Online**（緑のアイコン）で表示されることを確認
3. ラベルに `self-hosted`, `Linux`, `X64`, `salesanchor-vps` が含まれることを確認

### CLI で確認

```bash
# ローカルで実行
gh api /repos/shingo-ops/salesanchor/actions/runners \
  --jq '.runners[] | {name: .name, status: .status, labels: [.labels[].name]}'
```

**期待出力**:
```json
{
  "name": "salesanchor-vps",
  "status": "online",
  "labels": ["self-hosted", "Linux", "X64", "salesanchor-vps"]
}
```

---

## Step 7: qa-smoke 動作確認

runner が Online になったことを確認後、`qa-smoke.yml` を手動実行する。

```bash
# ローカルで実行
gh workflow run qa-smoke.yml \
  --repo shingo-ops/salesanchor \
  --ref develop

# 実行状況を確認
sleep 10
gh run list --workflow qa-smoke.yml --repo shingo-ops/salesanchor --limit 3
```

または GitHub UI から: Actions → `QA Smoke (Weekly Full Run)` → Run workflow

**確認ポイント**:
- workflow が `Queued` → `In progress` に遷移する（runner が job を pick-up した証拠）
- ログに "Running on salesanchor-vps" が表示される
- 全 8 scene が完走しなくても、runner が起動して実行を開始することを確認

**ログ確認**:
```bash
RUN_ID=$(gh run list --workflow qa-smoke.yml --repo shingo-ops/salesanchor --limit 1 --json databaseId --jq '.[0].databaseId')
gh run view $RUN_ID --repo shingo-ops/salesanchor --log | head -50
```

---

## Step 8: ADR-078 ステータス更新

動作確認が取れたら ADR-078 のステータスを `Accepted` に更新して PR を作成する。

```bash
# ローカルで実行
sed -i '' 's/| ステータス | Proposed |/| ステータス | Accepted |/' \
  docs/adr/ADR-078-vps-runner-registration.md

node scripts/generate-adr-index.js
git add docs/adr/ADR-078-vps-runner-registration.md docs/adr/README.md
git commit -m "docs(adr): ADR-078 ステータスを Accepted に更新（VPS runner 登録完了）"
gh pr create --base develop --title "docs(adr): ADR-078 VPS runner 登録完了" --body "ADR-078 を Proposed → Accepted に更新。salesanchor-vps runner が Online になり、qa-smoke の動作確認完了。"
```

---

## トラブルシューティング

### パターン 1: `./config.sh` でトークンエラー

**症状**: `Failed to connect to the server. Error: Invalid credentials`  
**原因**: 登録トークンの有効期限切れ（1 時間）または権限不足  
**対処**:
```bash
# ローカルで新しいトークンを取得し直す
gh api --method POST /repos/shingo-ops/salesanchor/actions/runners/registration-token --jq '.token'
# 新しいトークンで ./config.sh を再実行
```

---

### パターン 2: runner が Offline のまま

**確認手順**:
```bash
# VPS 上で
sudo systemctl status actions.runner.shingo-ops-salesanchor.salesanchor-vps.service
sudo journalctl -u actions.runner.shingo-ops-salesanchor.salesanchor-vps.service -n 50
```

**よくある原因**:
- ネットワーク不通: VPS 上で `curl https://api.github.com` 確認
- プロセスが重複: `ps aux | grep Runner.Listener`
- 権限問題: サービスのログを確認

---

### パターン 3: qa-smoke が queue で止まる（runner が job を取得しない）

**確認**:
```bash
# ローカルで
gh api /repos/shingo-ops/salesanchor/actions/runners \
  --jq '.runners[] | {name: .name, labels: [.labels[].name]}'
# → salesanchor-vps ラベルが含まれるか確認
```

**対処**: ラベルが不足している場合は runner を削除して Step 4 から再登録する。

---

### パターン 4: Playwright ブラウザのインストール失敗

**症状**: `Error: browserType.launch: Executable doesn't exist`  
**対処** (VPS 上で):
```bash
cd ~/actions-runner/_work/salesanchor/salesanchor/frontend
npx playwright install --with-deps chromium
```

依存ライブラリが不足している場合:
```bash
sudo apt-get install -y libglib2.0-0 libnss3 libnspr4 libatk1.0-0 \
  libatk-bridge2.0-0 libcups2 libdrm2 libxkbcommon0 libxcomposite1 \
  libxdamage1 libxfixes3 libxrandr2 libgbm1 libasound2
```

---

### パターン 5: OOM（メモリ不足）でジョブが強制終了

**症状**: ジョブが途中で無音終了する、VPS への SSH が切れる  
**確認** (VPS 上で):
```bash
dmesg | grep -i "oom\|killed" | tail -20
```

**対処**:
1. **別サーバーを用意する**（しんごさん決定 2026-05-28）。さくらVPS コントロールパネルから RAM 2GB 以上のプランを追加契約し、新サーバーに runner を移行する。
2. 移行後は本 runbook の IP `49.212.137.46` を新サーバー IP に更新し、ADR-078 §登録するランナーの仕様 も更新する。
3. 旧サーバーの runner は削除トークン取得 → `./config.sh remove --token <token>` でクリーンアップ。

---

### ロールバック手順

runner を削除して元の状態（queue 待機）に戻す。

```bash
# VPS 上で
sudo systemctl stop actions.runner.shingo-ops-salesanchor.salesanchor-vps.service
sudo systemctl disable actions.runner.shingo-ops-salesanchor.salesanchor-vps.service
cd ~/actions-runner

# GitHub からロールバックトークンを取得（ローカルで）
gh api --method POST /repos/shingo-ops/salesanchor/actions/runners/remove-token --jq '.token'

# VPS 上で削除
./config.sh remove --token <ロールバックトークン>
```

---

## 参照ドキュメント

- ADR-078: `docs/adr/ADR-078-vps-runner-registration.md`（本作業の ADR）
- ADR-038: `docs/adr/ADR-038-qa-smoke-suite.md`（qa-smoke suite 設計）
- ADR-035: `docs/adr/ADR-035-external-state-verification.md`
- ADR-029: `docs/adr/ADR-029-self-hosted-runner-fleet.md`
- qa-smoke 運用 runbook: `docs/runbooks/qa-smoke-operations.md`
- GitHub Actions runner 公式: https://docs.github.com/en/actions/hosting-your-own-runners/managing-self-hosted-runners/adding-self-hosted-runners
