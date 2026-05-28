# ADR-029: Self-hosted runner fleet — 2 台 Mac 体制と labels 戦略の正式化

| 項目 | 内容 |
|------|------|
| ステータス | Accepted |
| 作成日 | 2026-05-15 |
| 起案 | ひとし（森本） |
| 関連 ADR | ADR-012（What/How 役割分担モデル、claude-pipeline 運用基盤）/ ADR-035（External State Verification、本 ADR の cron runner として参照）/ ADR-038（QA Smoke Suite、本 ADR の labels を使用）/ ADR-039（Generator codebase reconnaissance） |

## What

salesanchor の self-hosted runner を **2 台 Mac 体制**（Hikky-dev-Mac + Shingo-Mac-Temp）で正式運用し、labels 戦略を整理する。memory 上は 2026-05-15 時点で記録済だが、`docs/adr/` には未起案だったため、ADR-035 起案時に 4 箇所で cross-reference したものの存在しない ADR への参照になっていた問題（PR #379 Round 1 Reviewer Minor-1 で指摘）を解消する。

### 1. 2 台 Mac 体制の正式化

- **Hikky-dev-Mac**（既存、ひとし担当）
  - MacBook Pro 13" 2020 (Intel, 8GB, macOS Sequoia 15.7.5)
  - 持ち歩き運用、バッテリ劣化のため sleep 抑制（`pmset -c disablesleep 1` 等）は **採用しない**（2026-05-07 確定、memory `project_runner_host_decision.md`）
  - shutdown 中は runner offline 許容、復帰後の workflow_dispatch は手動再起動
- **Shingo-Mac-Temp**（新規、しんごさん側）
  - 2026-05-15 追加
  - Hikky-dev-Mac が offline 時のフォールバック稼働を担う

### 2. Labels 戦略

repo 内 workflow の `runs-on` 設定は **3 パターン**:

| Pattern | 用途 | 使用 workflow（起案時 reconnaissance 結果） |
|---------|------|----------------------------------------------|
| `runs-on: self-hosted`（labels なし） | どの self-hosted runner でも OK | `claude-pipeline.yml:17` |
| `runs-on: [self-hosted, salesanchor-vps]` | `salesanchor-vps` label 付き runner 専用 | `qa-smoke.yml:59`, `external-state-snapshot.yml:50` |
| `runs-on: ubuntu-latest` | GitHub-hosted runner | `feedback-issue-triage.yml`, `e2e.yml`, `deploy.yml`, `discord-pr-notify.yml`, `schema-check.yml`, `test.yml` |

**`salesanchor-vps` label の実態は memory 上未確認** — memory の 2 台 Mac 体制（Hikky-dev-Mac / Shingo-Mac-Temp）には `salesanchor-vps` label の記録なし。可能性:

- (a) VPS (49.212.137.46) 上に runner が別途存在し、`salesanchor-vps` label が付いている
- (b) Mac runner のいずれかに `salesanchor-vps` label が付いている
- (c) しんごさん側でラベル運用が変わって memory が古い

実態調査は しんごさん確認 follow-up（本 ADR 起案後に確認 → §実態調査結果 を更新）。

### 3. Hikky-dev-Mac の launchd 自動起動

ひとし TODO（しんごさん依頼 2026-05-15、memory `project_adr029_runner.md`）:

- 現状: shutdown 後にひとしが手動で `./run.sh` していた
- 目標: launchd plist を整備し、ログイン時 / shutdown 復帰時に runner が自動 online になる
- 手順は `docs/onboarding/self-hosted-runner-setup.md` に記載（しんごさん作成中、本 ADR の implementation 範囲）

### 4. Onboarding doc の整備

`docs/onboarding/self-hosted-runner-setup.md` をしんごさんが作成中（新規）。内容:

- 2 台体制の概要
- macOS 上の runner セットアップ手順（`./config.sh` → `./run.sh` → launchd plist）
- labels 設定方法
- 障害時の復旧手順（runner offline → workflow_dispatch 再起動）

既存の `docs/onboarding/claude-code.md`（実在確認済）と並ぶ位置。

## Why

salesanchor の自動実装パイプライン（claude-pipeline）と週次 cron（qa-smoke / external-state-snapshot）は self-hosted runner に依存している。runner 1 台体制（Hikky-dev-Mac のみ）では:

- Hikky-dev-Mac shutdown 中はパイプライン全停止
- ひとしのバッテリ事情で sleep 抑制不可 → 持ち歩き中の自然 offline 多発
- workflow_dispatch は 30 分以上 runner offline で job timeout、復帰後手動再 dispatch 必須

2 台体制 + 自動起動で可用性を担保することで:

- ひとしの 1 台が offline でも しんごさん側 Shingo-Mac-Temp で継続
- claude-pipeline / 週次 cron の信頼性向上
- ADR-035 / ADR-038 で導入した cron が初回から動く前提を満たす

加えて、ADR-035 PR #379 Round 1 Reviewer が ADR-029 未起案を Minor-1 で指摘した通り、**memory 参照だけで repo 内 ADR の cross-reference が機能していない**状態を解消する必要があった。本 ADR は memory の 2 台体制を docs/adr/ に正式起案して cross-reference を有効化する。

## Scope (IN)

- 本 ADR `docs/adr/ADR-029-self-hosted-runner-fleet.md` の起案（本ファイル）
- `docs/onboarding/self-hosted-runner-setup.md` の起案（しんごさん作成中、本 ADR の implementation 範囲、別 PR で実装）
- Hikky-dev-Mac の launchd 自動起動設定（ひとし TODO、本 ADR で明文化、別作業）
- 既存 workflow 9 本の `runs-on` 設定の **現状記録**（実態調査結果 table）

## Scope (OUT — 明示除外)

- **runner host hardware の変更**（Mac mini M4 投資、Linux VPS への移行など）→ memory `project_runner_host_decision.md` で別途検討中、しんごさんとの相談保留
- **`salesanchor-vps` label の正体究明と再構成**: 実態調査結果を反映する follow-up が必要（本 ADR では「未解明」と記録、別 PR で更新候補）
- **第 3 runner 追加**（将来必要時）
- **Linux VPS runner**（Claude CLI 動作要検証、別 ADR 候補）
- **PIPELINE_PAT rotation**（既存 memory `project_pipeline_pat_rotation.md`、rotation due 2026-08-05、別タスク）
- **既存 workflow の labels 変更**（本 ADR は現状記録のみ、再設計は別 ADR）

## Business constraints

- **バッテリ事情で sleep 抑制不可**（Hikky-dev-Mac、2026-05-07 確定）
- **Mac mini M4 投資（¥98,800）はしんごさんとの相談保留中**
- **30 分以上 Mac off 後の workflow_dispatch は job timeout** → 復帰後手動再 dispatch
- **マージ判断はしんごさん review 不要**: 運用基盤の ADR、Meta 申請関連ではないため Reviewer エージェント経路（ADR-035 / 039 と同じ）

## 実態調査結果（起案時 reconnaissance、しんごさん確認 follow-up 待ち）

| Workflow file | `runs-on` 設定 | 想定 runner | 備考 |
|---------------|----------------|-------------|------|
| `.github/workflows/claude-pipeline.yml:17` | `self-hosted` | Hikky-dev-Mac / Shingo-Mac-Temp どちらでも | label なし、両 Mac で動作可能 |
| `.github/workflows/qa-smoke.yml:59` | `[self-hosted, salesanchor-vps]` | `salesanchor-vps` label 付き runner | 実態未確認 |
| `.github/workflows/external-state-snapshot.yml:50` | `[self-hosted, salesanchor-vps]` | 同上 | ADR-035 で導入、実態未確認 |
| `.github/workflows/feedback-issue-triage.yml:21` | `ubuntu-latest` | GitHub-hosted | self-hosted 外 |
| `.github/workflows/e2e.yml:32` | `ubuntu-latest` | GitHub-hosted | self-hosted 外 |
| `.github/workflows/deploy.yml:10` | `ubuntu-latest` | GitHub-hosted | self-hosted 外 |
| `.github/workflows/discord-pr-notify.yml:11` | `ubuntu-latest` | GitHub-hosted | self-hosted 外 |
| `.github/workflows/schema-check.yml:33` | `ubuntu-latest` | GitHub-hosted | self-hosted 外 |
| `.github/workflows/test.yml:24` | `ubuntu-latest` | GitHub-hosted | self-hosted 外 |

**未解明事項**: `salesanchor-vps` label の runner は

- memory `project_adr029_runner.md`（2 台 Mac 体制記録）に記述なし
- memory `project_runner_host_decision.md`（host 決定経緯）にも記述なし
- `gh api repos/shingo-ops/salesanchor/actions/runners` は Hikky-dev 権限不足で 403（memory `feedback_hikky_dev_permissions.md`）

→ しんごさん側で実体確認（runner 一覧 + 各 runner の labels 設定）が必要。本 ADR merge 後の follow-up issue / PR で更新する。

## 成功基準

1. ADR-029 が `docs/adr/ADR-029-self-hosted-runner-fleet.md` として起案され、ADR-035 / 038 等の cross-reference が valid になる
2. `docs/onboarding/self-hosted-runner-setup.md`（しんごさん作成）に 2 台のセットアップ手順 + labels 設定 + 障害復旧手順が記載される
3. Hikky-dev-Mac の launchd 自動起動が完了し、shutdown → 起動で runner が自動 online になる（ひとし TODO）
4. `salesanchor-vps` label の runner 実態が明確になり、本 ADR §実態調査結果 が follow-up で更新される（しんごさん確認）

## 想定リスク

1. **`salesanchor-vps` label の runner が実は存在しない**: qa-smoke.yml / external-state-snapshot.yml が起動しても runner queue で永続的に pick-up されない可能性 → しんごさん確認最優先、不在なら label 削除 or runner 追加の follow-up
2. **2 台同時 online 時の job 取り合い**: 同じ workflow が 2 つの runner で並走するリスク。`concurrency` group を workflow 側で適切に設定すべき（qa-smoke.yml は既に `concurrency.group: qa-smoke-tenant-006` で対応済、claude-pipeline は未設定）
3. **launchd 自動起動の権限問題**: macOS の自動起動でセキュリティ警告 / 権限不足が出る可能性 → onboarding doc に既知の回避策を記載
4. **PIPELINE_PAT rotation 時の影響**: rotation 時に両 runner で再 config が必要、memory `project_pipeline_pat_rotation.md` の手順に組み込む
5. **memory と実態のずれ**: 本 ADR は memory 起源で書かれているが、しんごさん側の運用変更を memory が捕捉できていない可能性。`salesanchor-vps` label がその例。実態調査 follow-up で順次解消

## 関連 referent（起案時 reconnaissance 結果）

ADR-039 §Codebase reconnaissance + ADR-035 で導入した起案時 referent 表を継承:

| Referent | Type | grep cmd | hit count | top file:line | Action | 備考 |
|----------|------|----------|-----------|---------------|--------|------|
| `runs-on: self-hosted` | workflow keyword | `grep -n "runs-on" .github/workflows/*.yml` | 1 line | claude-pipeline.yml:17 | Keep | 実在 |
| `[self-hosted, salesanchor-vps]` | runner labels | (同上) | 2 lines | qa-smoke.yml:59 + external-state-snapshot.yml:50 | Keep | 実在 |
| `Hikky-dev-Mac` | runner name | memory + runbook | (repo 内 grep 0 hit、memory 参照) | (none in repo) | Keep | memory 参照、本 ADR で repo 初言及 |
| `Shingo-Mac-Temp` | runner name | (同上) | (同上) | (none in repo) | Keep | memory 参照、本 ADR で repo 初言及 |
| `salesanchor-vps` | runner label | workflow grep | 2 lines | qa-smoke.yml:59 | Keep | 実在ラベル、実体不明 |
| `docs/onboarding/claude-code.md` | doc | `ls docs/onboarding/` | exists | docs/onboarding/claude-code.md | Keep | 既存 |
| `docs/onboarding/self-hosted-runner-setup.md` | doc | (同上) | 0 hit | (none) | **Add**（しんごさん作成中） | 新規 |
| `pmset -c disablesleep 1` | macOS cmd | memory `project_runner_host_decision.md` | (memory) | (バッテリ事情で不採用) | Keep | doc 化推奨 |
| `./run.sh` / `./config.sh` | runner cmd | memory + GitHub Actions runner 標準 | (memory) | (none) | Keep | onboarding doc で記載 |

Total referents: 9  /  0-hit replaced: 0  /  Add (新規): 1（`docs/onboarding/self-hosted-runner-setup.md`、しんごさん作成中）  /  Keep: 8

## Amendment — 2026-05-28: claude-pipeline `runs-on` を `[self-hosted, macOS]` に変更

### 変更内容

`claude-pipeline.yml` の全8ジョブ（`context` / `researcher` / `claude-worker` / `reviewer` / `evaluator` / `governance` / `automerge` / `regenerate`）の `runs-on` を以下のとおり変更した。

```yaml
# 変更前
runs-on: self-hosted

# 変更後
runs-on: [self-hosted, macOS]
```

### 変更理由

6月中旬に VPS Linux ランナー（`salesanchor-vps` ラベル）を追加予定。`self-hosted` のみでは Claude CLI 非対応の Linux ランナーで claude-pipeline が実行されるリスクがある。`macOS` ラベルを AND 条件で追加することで Mac ランナーのみに絞り込む。

GitHub Actions の公式仕様（[Choosing the runner for a job](https://docs.github.com/actions/using-jobs/choosing-the-runner-for-a-job)）により、`[self-hosted, macOS]` は両ラベルを持つランナーのみ選択される（AND 動作）。`macOS` ラベルは Mac 登録時に自動付与される。

### 定着化

`runner-label-lint.yml`（新規）を追加し、`claude-pipeline.yml` に bare `self-hosted` や誤った大文字・小文字（`macos`）が混入した場合に CI で検出する。

### §実態調査結果 更新

| Workflow file | `runs-on` 設定 | 備考 |
|---------------|----------------|------|
| `.github/workflows/claude-pipeline.yml` | `[self-hosted, macOS]` | **変更済み（2026-05-28）** |

---

## Amendment — 2026-05-28: salesanchor-vps ラベル付き VPS runner の正式追加

### 変更内容

ADR-078 の Accepted により、さくらVPS（Ubuntu、IP: 49.212.137.46）に第 3 ランナーとして `salesanchor-vps` ラベル付き self-hosted runner を追加することが正式決定した。

| 項目 | 値 |
|------|----|
| ホスト | さくらVPS / Ubuntu（IP: 49.212.137.46） |
| runner name | `salesanchor-vps` |
| labels | `self-hosted`, `Linux`, `X64`, `salesanchor-vps` |
| 管理方式 | systemd service（自動起動） |
| 目的 | `qa-smoke.yml` / `external-state-snapshot.yml` 専用（本番 DB に直アクセスが必要）|

### §実態調査結果 更新

| Workflow file | `runs-on` 設定 | 備考 |
|---------------|----------------|------|
| `.github/workflows/qa-smoke.yml:59` | `[self-hosted, salesanchor-vps]` | **VPS runner（ADR-078）で稼働予定** |
| `.github/workflows/external-state-snapshot.yml:50` | `[self-hosted, salesanchor-vps]` | 同上 |

### 登録手順・ロールバック

詳細は ADR-078 および `docs/runbooks/vps-runner-setup.md` を参照。  
自動化スクリプト: `scripts/setup-vps-runner.sh`

### メモリ不足時の方針

VPS の空きメモリが不足して OOM が発生した場合は、スワップ増設ではなく**別サーバーを追加契約**して runner を移行する（しんごさん決定 2026-05-28）。

---

## 関連メモリ・ドキュメント

- `~/.claude/projects/-Users-hitoshi-Documents---------------CRM----/memory/project_adr029_runner.md` (本 ADR 起案根拠、2 台体制記録)
- `~/.claude/projects/-Users-hitoshi-Documents---------------CRM----/memory/project_runner_host_decision.md` (host 決定経緯、2026-05-07 確定)
- `~/.claude/projects/-Users-hitoshi-Documents---------------CRM----/memory/project_pipeline_pat_rotation.md` (PIPELINE_PAT rotation due 2026-08-05)
- `~/.claude/projects/-Users-hitoshi-Documents---------------CRM----/memory/feedback_hikky_dev_permissions.md` (admin 権限なし、runner API 403)
- ADR-012 (What/How 役割分担、claude-pipeline 運用基盤)
- ADR-035 (External State Verification、本 ADR の cron runner として参照、PR #379 Round 1 Reviewer Minor-1 で「ADR-029 未起案」指摘の出処)
- ADR-038 (QA Smoke Suite、`[self-hosted, salesanchor-vps]` labels を使用)
- ADR-039 (Generator codebase reconnaissance、起案時 reconnaissance 表の前例)
- 既存 workflow 9 本（上記 §実態調査結果 table 参照）
- 既存 onboarding doc: `docs/onboarding/claude-code.md`（Hikky-dev runner setup の partial 情報を含む）
