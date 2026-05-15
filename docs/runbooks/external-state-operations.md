# External State Operations Runbook

> ADR-035: External State Verification — L4 Manual Evidence + 運用手順

## 概要

本ドキュメントは、外部システム（Meta App / Firebase / GitHub / Cloudflare / Discord / GCP）の
状態検証・drift 対応・新 system 追加の手順を記述する。

5 層防御 (L1-L5) の概要:

| Layer | 実体 | 目的 |
|-------|------|------|
| L1 Contract | `docs/external-state-contract.yml` | 期待状態の宣言 |
| L2 Smoke | `scripts/smoke/external-{system}.sh` | 疎通テスト（3 mode） |
| L3 Snapshot | `scripts/snapshot/{system}.sh` | 状態取得・diff 検出 |
| L4 Manual evidence | `docs/runbooks/external-evidence/{system}/` | API 不可 surface のスクリーンショット置き場 |
| L5 Owner ping | `scripts/notify/discord-owner-ping.sh` | 人間向け action items の Discord 通知 |

---

## 週次 cron が offline だった場合の復旧手順

ADR-029 により runner host（Hikky-dev-Mac）の sleep は許容されている。
週次 cron 実行時に runner が offline の場合は次の手順で手動復旧:

```bash
# 週次 snapshot を手動実行
gh workflow run external-state-snapshot.yml

# 実行状況確認
gh run list --workflow=external-state-snapshot.yml --limit=5
```

---

## drift 検出時の対応手順

drift は L3 snapshot の `.diff` ファイルで検出される（`external-state-snapshots/{date}/` 配下）。
Discord #owner-ping に自動通知される（L5）。

### 1. drift の確認

```bash
# 最新スナップショットの diff ファイルを確認
ls external-state-snapshots/$(ls -t external-state-snapshots/ | head -1)/

# diff 内容を確認
cat external-state-snapshots/YYYY-MM-DD-weekly/meta_subscriptions.diff
```

### 2. 原因の特定

drift の種類に応じて確認場所が変わる:

| system | drift の原因例 | 確認場所 |
|--------|----------------|----------|
| Meta | subscription 解除 / App Review state 変更 | Meta Business Suite |
| Firebase | OAuth provider 追加・削除 / authorized domain 変更 | Firebase Console |
| GitHub | branch protection 変更 / secret 追加・削除 | GitHub Settings |
| Cloudflare | DNS record 変更 / WAF rule 追加・削除 | Cloudflare Dashboard |
| Discord | Webhook 削除・再生成 / channel 変更 | Discord Server Settings |
| GCP | IAM binding 変更 / Service account 削除 | GCP IAM Console |

### 3. contract の更新

drift が意図的な変更の場合（例: Firebase に OAuth provider を追加した）:

```yaml
# docs/external-state-contract.yml を人間が確認した上で更新
# contract の「自動更新」は禁止（ADR-035 Scope OUT）
firebase:
  auth_providers: [google.com, password, github.com]  # 追加
  last_verified: 2026-XX-XX  # 確認日を記録
```

### 4. 意図しない drift の場合

意図しない変更（外部システムが勝手に変わった / 誰かが誤操作した）は:
1. 外部システム側を正しい状態に戻す
2. L2 smoke で疎通を確認: `bash scripts/smoke/external-{system}.sh --live` (PO_LIVE_OK=yes 必要)
3. L3 snapshot を手動実行して baseline を更新

---

## L2 Smoke スクリプトの使い方

```bash
# dry-run: 設定確認のみ、API 呼び出しなし
bash scripts/smoke/external-meta.sh --dry-run

# sandbox: 疎通確認のみ（Meta は Phase 0 では dry-run 相当）
bash scripts/smoke/external-meta.sh --sandbox
bash scripts/smoke/external-firebase.sh --sandbox
bash scripts/smoke/external-github.sh --sandbox
bash scripts/smoke/external-cloudflare.sh --sandbox
bash scripts/smoke/external-discord.sh --sandbox
bash scripts/smoke/external-gcp.sh --sandbox

# live: 本番 API に投げる（PO 確認必須）
PO_LIVE_OK=yes bash scripts/smoke/external-meta.sh --live
```

---

## L3 Snapshot スクリプトの使い方

```bash
# 手動で全 6 system をスナップショット（VPS 2GB 配慮で直列実行）
SNAPSHOT_DIR=external-state-snapshots SPRINT_TAG=manual bash scripts/snapshot/meta.sh
sleep 5
SNAPSHOT_DIR=external-state-snapshots SPRINT_TAG=manual bash scripts/snapshot/firebase.sh
sleep 5
SNAPSHOT_DIR=external-state-snapshots SPRINT_TAG=manual bash scripts/snapshot/github.sh
sleep 5
SNAPSHOT_DIR=external-state-snapshots SPRINT_TAG=manual bash scripts/snapshot/cloudflare.sh
sleep 5
SNAPSHOT_DIR=external-state-snapshots SPRINT_TAG=manual bash scripts/snapshot/discord.sh
sleep 5
SNAPSHOT_DIR=external-state-snapshots SPRINT_TAG=manual bash scripts/snapshot/gcp.sh
```

### SECRET SCRUB 確認チェックリスト（Reviewer 必読）

Reviewer は merge 前に各 snapshot スクリプトの scrub ロジックを目視確認すること:

- [ ] `scripts/snapshot/meta.sh`: `access_token`, `client_secret`, `app_secret_proof` を `del()` で削除
- [ ] `scripts/snapshot/firebase.sh`: `private_key`, `private_key_id` を `del()` で削除
- [ ] `scripts/snapshot/github.sh`: PAT は API に使用するのみ、snapshot json に書かれていないか確認
- [ ] `scripts/snapshot/cloudflare.sh`: API token は使用のみ、DNS content を sha256 prefix に変換
- [ ] `scripts/snapshot/discord.sh`: Webhook URL（token 含む）を snapshot に書かず、`token_present` に変換
- [ ] `scripts/snapshot/gcp.sh`: `private_key` を `del()` で削除

---

## L4 Manual Evidence の保存手順

API で確認できない surface（Meta App Review state / Firebase OAuth provider details 等）は
スクリーンショットを `docs/runbooks/external-evidence/{system}/` に保存する。

```
docs/runbooks/external-evidence/
├── meta/
│   ├── app-review-state-YYYY-MM-DD.png    # Meta App Review state
│   ├── test-users-YYYY-MM-DD.png          # Test Users
│   └── app-mode-YYYY-MM-DD.png            # App Mode (Development/Live)
├── firebase/
│   ├── oauth-providers-YYYY-MM-DD.png     # OAuth provider details
│   └── authorized-domains-YYYY-MM-DD.png # Authorized domains
├── github/
│   ├── environment-protection-YYYY-MM-DD.png  # Environment protection rules
│   └── required-reviewers-YYYY-MM-DD.png      # Required reviewers
├── cloudflare/
│   ├── waf-custom-rules-YYYY-MM-DD.png    # WAF custom rules
│   └── page-rules-YYYY-MM-DD.png         # Page Rules
├── discord/
│   ├── channel-permissions-YYYY-MM-DD.png  # Channel permissions
│   └── bot-invite-YYYY-MM-DD.png          # Bot invite state
└── gcp/
    ├── org-policy-YYYY-MM-DD.png          # Org policy
    └── quotas-YYYY-MM-DD.png             # Quotas
```

ファイル命名規則: `{screenshot-subject}-YYYY-MM-DD.png`

**Evaluator が timestamp 確認するため、git commit に必ず含めること。**

---

## 新しい外部システムを追加する手順

ADR-035 は 6 system の bootstrap に絞っている（Scope OUT: 7 system 目以降は別 ADR）。
将来 7 system 目（Stripe / Sendgrid / AWS 等）を追加する場合:

1. `docs/external-state-contract.yml` に新 system セクションを追加
2. `scripts/smoke/external-{system}.sh` を作成（3 mode 対応）
3. `scripts/snapshot/{system}.sh` を作成（secret scrub 必須）
4. `docs/runbooks/external-evidence/{system}/.gitkeep` を作成
5. `.github/workflows/external-state-snapshot.yml` に新 snapshot step を追加
6. 別 ADR で正式に採択する

---

## 想定リスク対応

### API token expire

snapshot.sh 実行時にトークンが期限切れになると cron が失敗する。
Discord #owner-ping に通知（workflow の `if: always()` ステップ）→ PO がトークンを更新。

```bash
# 失敗した workflow の確認
gh run list --workflow=external-state-snapshot.yml --limit=5

# 手動再実行
gh workflow run external-state-snapshot.yml
```

### snapshot json に secret が混入した場合

**即座に以下を実行:**

1. git history から完全削除（`git filter-branch` または `git filter-repo`）
2. 該当 secret を revoke して新しい値で再生成
3. GitHub Settings で secret を更新
4. Reviewer と PO に報告

---

## 関連ドキュメント

- `docs/adr/ADR-035-external-state-verification.md` — 設計根拠
- `docs/external-state-contract.yml` — L1 contract
- `docs/runbooks/B-06_cloudflare_setup.md` — Cloudflare 設定 runbook
- `docs/runbooks/qa-smoke-operations.md` — QA Smoke 運用手順（ADR-038）
