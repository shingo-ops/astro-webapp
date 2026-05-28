# ADR-078: VPS runner 登録計画 — さくらVPS への salesanchor-vps ラベル付き self-hosted runner 登録

| 項目 | 内容 |
|------|------|
| ステータス | Accepted |
| 作成日 | 2026-05-28 |
| 予定実施日 | 2026-06-15 前後 |
| 起案 | しんごさん（PO） |
| 関連 ADR | ADR-029（self-hosted runner fleet）/ ADR-035（External State Verification）/ ADR-038（QA Smoke Suite）/ ADR-075（GitHub Secrets Only Policy） |

## What

さくらVPS（Ubuntu、IP: 49.212.137.46）に GitHub Actions self-hosted runner を登録し、`salesanchor-vps` ラベルを付与する。

### 背景

ADR-029 §実態調査結果 および ADR-038 §Amendment (2026-05-27) で判明したとおり、`qa-smoke.yml` および `external-state-snapshot.yml` は `runs-on: [self-hosted, salesanchor-vps]` を指定しているが、対応する runner が実際には未登録の状態にある。その結果:

- 週次 QA smoke（毎週月曜 03:00 JST）は runner 待機のまま queue で止まり、一度も実行されていない
- External State Snapshot cron（ADR-035）も同様に実行不能

本 ADR は、2026-06-15 前後に VPS へ runner を登録し、両 workflow を実際に動かせる状態にすることを正式決定として記録する。

### 登録するランナーの仕様

| 項目 | 値 |
|------|----|
| ホスト | さくらVPS / Ubuntu（IP: 49.212.137.46） |
| runner name | `salesanchor-vps` |
| labels | `self-hosted`, `Linux`, `X64`, `salesanchor-vps` |
| 管理方式 | systemd service（自動起動） |
| 実行ユーザー | 既存 deploy ユーザーまたは専用 `github-runner` ユーザー |

## Why

1. **qa-smoke.yml が機能していない**: ADR-038 で設計した週次 E2E smoke suite は runner 未登録のため一度も実行できていない。品質保証の仕組みが存在するはずなのに動いていない。
2. **external-state-snapshot.yml も同様**: ADR-035 で設計した外部状態スナップショット cron も動いていない。
3. **VPS は最適な実行環境**: qa-smoke は本番 DB（PostgreSQL）への直接アクセスが必要。VPS 上で動かすことで firewall 制約なしにアクセスできる。GitHub-hosted runner では接続できない。
4. **コード変更不要**: `qa-smoke.yml` / `external-state-snapshot.yml` の `runs-on` は既に `salesanchor-vps` 指定済みのため、runner を登録するだけで即動く。

## Scope IN

- さくらVPS への GitHub Actions runner バイナリのインストール
- `./config.sh` 実行と `salesanchor-vps` ラベル付与
- systemd service 化（自動起動）
- `qa-smoke.yml` の workflow_dispatch による動作確認（1 回）
- `docs/runbooks/vps-runner-setup.md` の整備（同時作成済み）

## Scope OUT（明示除外）

- workflow 側の `runs-on` 変更（runner 側を整備するため変更不要）
- Claude CLI の VPS runner での動作（ADR-029 §Scope OUT、週次 cron には不要）
- runner の複数台構成・冗長化（初回登録後の運用フェーズで検討）
- PIPELINE_PAT rotation（rotation due 2026-08-05、別タスク）

## 実施タイムライン

| 日付 | マイルストーン |
|------|--------------|
| 2026-06-15（目標） | VPS runner 登録 + systemd 自動起動設定完了 |
| 2026-06-15 当日 | `qa-smoke.yml` を workflow_dispatch で手動実行して動作確認 |
| 2026-06-22（翌月曜）| 週次 cron が初めて自動実行される |
| 2026-06-22 | 週次 cron の実行履歴・Playwright report artifact を確認 |

**作業所要時間の目安**: 約 1.5〜2 時間

## 成功基準（Success Criteria）

1. GitHub リポジトリの Settings → Actions → Runners で `salesanchor-vps` runner が **Online** 状態で表示される
2. `qa-smoke.yml` を workflow_dispatch で手動実行したとき、`reset-and-smoke` job が runner に pick-up され、実行を開始する（全 8 scene green でなくとも、runner が job を取得することを確認）
3. systemd service が `enabled` 状態で、VPS 再起動後に runner が自動 online になる
4. 翌週月曜（2026-06-22）の weekly cron が自動実行され、GitHub Actions の実行履歴に記録される

## ロールバック手順

runner 登録後に問題が発生した場合:

```bash
# VPS 上で systemd service を停止・無効化
sudo systemctl stop actions.runner.shingo-ops-salesanchor.salesanchor-vps.service
sudo systemctl disable actions.runner.shingo-ops-salesanchor.salesanchor-vps.service

# runner の削除（GitHub 側からトークン取得後）
cd ~/actions-runner
./config.sh remove --token <REMOVE_TOKEN>
```

GitHub 側からの削除: Settings → Actions → Runners → runner 名 → Remove runner  
workflow 側は変更していないため、runner 削除後は元の「queue 待機」状態に戻る。

## 主なリスク

| リスク | 影響 | 対策 |
|-------|------|------|
| メモリ不足（OOM） | Playwright Chromium 起動時に約 706MB 消費。VPS 空きメモリ不足の場合 job が強制終了 | **別サーバーを用意する**（しんごさん決定 2026-05-28）。スワップ増設ではなく追加契約で対処 |
| 登録トークン期限切れ | トークンは 1 時間で失効 | 手順書を準備してからトークン取得し、即時実行 |
| ADR-029 未更新 | §Scope OUT に「Linux VPS runner は別 ADR 候補」と記載 | 本 ADR（ADR-077）が follow-up として機能 |

## 関連 referent（grep 確認済み）

| Referent | Type | hit count | top file:line |
|----------|------|-----------|---------------|
| `salesanchor-vps` | runner label | 2 lines | `qa-smoke.yml:59`, `external-state-snapshot.yml:50` |
| `runs-on: [self-hosted, salesanchor-vps]` | workflow 設定 | 2 lines | 同上 |
| `49.212.137.46` | VPS IP | CLAUDE.md 他 | 接続先 |
| `docs/runbooks/vps-runner-setup.md` | runbook | 新規作成（本 ADR と同時） | — |

## 関連ドキュメント

- ADR-029: `docs/adr/ADR-029-self-hosted-runner-fleet.md`
- ADR-035: `docs/adr/ADR-035-external-state-verification.md`
- ADR-038: `docs/adr/ADR-038-qa-smoke-suite.md`
- 実行手順書: `docs/runbooks/vps-runner-setup.md`
