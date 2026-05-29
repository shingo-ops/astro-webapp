# ADR-080: 監視スタックの管理室VPS分離 — RAM危機の根本解決とCIランナー統合

| 項目 | 内容 |
|------|------|
| ステータス | Proposed |
| 作成日 | 2026-05-28 |
| 起案 | しんごさん（PO） |
| 関連 ADR | ADR-029（self-hosted runner fleet）/ ADR-078（VPS runner 登録）/ ADR-079（Claude Code 監視アクセス）/ ADR-070（Grafana 監視統合）/ ADR-069（Uptime Kuma） |

## What

アプリVPS（49.212.137.46、さくらVPS 2GB）で同居している監視スタックを、新規契約する「管理室VPS」（さくらVPS 2GB/50GB）に分離する。同時に、ADR-078 で計画していた GitHub Actions self-hosted runner（`salesanchor-vps` ラベル）も管理室VPSに配置する。

### 分離後の構成

**アプリVPS（既存 49.212.137.46）に残るもの:**

| コンテナ | 残す理由 |
|---------|---------|
| node-exporter | ホストOSメトリクス収集（移動するとアプリVPSのメトリクスが取れなくなる） |
| postgres-exporter | PostgreSQL の Docker 内部ネットワーク依存 |
| redis-exporter | Redis の Docker 内部ネットワーク依存 |
| nginx-exporter | nginx の Docker 内部ネットワーク依存 |
| promtail | アプリVPSのコンテナログを読み取り、管理室VPSの Loki へ push |

**管理室VPS（新規・さくらVPS 2GB/50GB）に移動するもの:**

| コンテナ | 移動する理由 |
|---------|-------------|
| prometheus | scrape 対象をリモート（HTTP経由）に変更可能 |
| grafana | 表示専用、どこでも動く |
| loki | ログ受信サーバー、promtail からの push を受け取る |
| uptime-kuma | アプリVPS外から監視すべき（同居だとアプリVPSダウン時に通知不能） |
| gha-exporter | GitHub API 依存、場所を問わない |

**管理室VPSに追加するもの:**

| コンテナ/サービス | 用途 |
|-----------------|------|
| GitHub Actions self-hosted runner | `salesanchor-vps` ラベル、qa-smoke / external-state-snapshot 用 |

## Why

### 1. RAM 危機（直接原因）

アプリVPS（2GB RAM）の状況:

- OS + 全コンテナの合計 RAM 使用量が限界に達し、空きメモリ 98MB
- Grafana が設定上限 256MB の 99.7% を使用中で OOM リスクが常態化
- アプリ本体（~132MB）に対し、監視スタック（~547MB）が約4倍のメモリを消費

### 2. 監視の独立性（構造的問題）

- アプリVPSがダウンした場合、同居している Uptime Kuma も一緒に落ちるため、ダウン検知・通知が機能しない
- 監視と監視対象が同じホストにあるのは設計上の anti-pattern

### 3. CIランナーのリソース分離

- ADR-078 で計画していた `salesanchor-vps` ランナーをアプリVPSに登録すると、Playwright Chromium（~706MB）がアプリに影響する
- 管理室VPSに配置することで、CI実行がアプリ性能に影響しない

## Scope IN

- 管理室VPS（さくらVPS 2GB/50GB）の新規契約・初期セットアップ
- 監視スタック用 docker-compose の作成（管理室VPS用）
- アプリVPSの exporter 群を専用 docker-compose に分離
- Prometheus の scrape target をアプリVPSのパブリック/プライベートIPに変更
- promtail の Loki 接続先を管理室VPSに変更
- Grafana の公開設定維持（`https://app.salesanchor.jp/grafana/` の nginx プロキシ先変更、または新ドメイン `grafana.salesanchor.jp` への移行）
- GitHub Actions self-hosted runner の管理室VPSへの登録
- ADR-079 の `claude-monitor` ユーザーを管理室VPSにも設定
- 移行 runbook の整備
- ガバナンス継続化チェックリストの作成

## Scope OUT（明示除外）

- 管理室VPSの冗長化（1台構成で十分）
- Prometheus のリモートストレージ導入（ローカル TSDB を維持）
- アプリVPSのアプリケーションコンテナ構成変更（exporter 分離以外）
- VPN の導入（さくらVPSファイアウォール + ポートバインドで対応）
- 監視VPSの2台目（将来必要時に別ADR）
- Loki のログ保持期間変更

## Business constraints

- 管理室VPS の追加コスト: さくらVPS 2GB プラン（月額 ~1,738円）
- ダウンタイムゼロ移行: アプリは止めない。監視の一時欠損（数十分）は許容
- PO が GUI 操作する項目: VPS 契約、ファイアウォール設定、DNS 設定（Cloudflare）
- exporter のスクレイプポート（9100/9187/9113/9121等）はファイアウォールで管理室VPSのIPからのみ許可

## 技術的制約（アーキテクト査定済み）

1. **VPS間通信**: prometheus（管理室）→ exporter 群（アプリVPS）の HTTP スクレイプが必要
2. **さくらVPSファイアウォール**: スクレイプポート（9100/9187/9113/9121等）の許可設定が必要（管理室VPSのIPからのみ）
3. **promtail のLoki接続先**: 管理室VPSのIPに変更が必要
4. **Grafana URL**: `https://app.salesanchor.jp/grafana/` を維持する場合、アプリVPS nginx のプロキシ先を管理室VPSに変更
5. **Playwright**: `--shm-size=256m` 必須（runner の docker-compose 設定）
6. **ADR-079 claude-monitor**: 管理室VPSにも同ユーザーを設定

## Consequences

### Positive

- アプリVPSのメモリが約547MB解放され、テストローンチに余裕ができる
- アプリVPSダウン時でも Uptime Kuma が検知・Discord 通知できる
- CI（qa-smoke）がアプリ性能に影響しない
- 監視スタックの再起動・メンテナンスがアプリに影響しない

### Negative

- VPS 2台の運用コスト増（月額 ~1,738円追加）
- VPS間通信の設定が必要（ファイアウォール、ポートバインド）
- exporter 群はアプリVPSに残留する必要がある（完全分離はできない）
- Grafana のプロキシ設定変更が必要
- 認証情報（claude-monitor SSH鍵、Grafana token）の管理対象が2台に増える

## ADR リレーション

| 関連 ADR | 関係 |
|---------|------|
| ADR-029 | Amendment で「OOM時は別サーバー追加」を決定済み。本 ADR がその具体化 |
| ADR-078 | runner 登録先がアプリVPSから管理室VPSに変更。ADR-078 の Amendment として反映 |
| ADR-079 | `claude-monitor` ユーザーを管理室VPSにも追加設定。Scope が拡大 |
| ADR-070 | Grafana 設定の移行元。プロビジョニングファイルをそのまま管理室VPSに持っていく |
| ADR-069 | Uptime Kuma の移行元。管理室VPSに移動することで本来の独立監視が実現 |

## 成功基準

1. アプリVPSの `docker stats` でメモリ使用量が移行前より 500MB 以上減少している
2. 管理室VPSで prometheus / grafana / loki / uptime-kuma / gha-exporter が全て healthy で稼働している
3. Grafana にブラウザでアクセスしてアプリVPSのメトリクスが表示される
4. Uptime Kuma がアプリVPSの `https://app.salesanchor.jp` を監視しており、ダウン検知で Discord 通知が届く
5. `salesanchor-vps` ラベルの runner が管理室VPSで Online になり、qa-smoke が実行される
6. アプリVPS の全アプリケーションコンテナが正常稼働している
7. exporter ポートがインターネットに公開されていない（管理室VPSのIPからのみアクセス可能）

## 主なリスク

| リスク | 影響 | 対策 |
|--------|------|------|
| VPS間ネットワーク遅延 | Prometheus の scrape timeout | さくらVPS同一リージョンを選択。scrape_timeout を調整（デフォルト10s） |
| 管理室VPSの OOM | 監視スタック + runner の同居で RAM 不足 | **4GB プランを推奨**（2GBは最小運用・retention短縮必須）。runner 実行時のみ Playwright が消費するため常時ではない |
| ファイアウォール設定ミス | メトリクス収集不能 | runbook にテストコマンドを明記。段階的に移行 |
| Grafana プロキシ変更時の URL 切れ | PO が一時的にアクセスできない | 先に管理室VPSで起動→確認→プロキシ切り替えの順序 |
| promtail → Loki 通信断 | ログが一時的に欠損 | 管理室VPSの Loki 起動確認後に promtail の接続先を切り替え |

## 実装制約（Codex / Generator 向け）

以下の制約は Codex・Claude Code どちらが実装する場合も必須：

| 制約 | 内容 |
|------|------|
| **Prometheus retention** | `--storage.tsdb.retention.time=30d`（4GB VPS の場合）を明示的に設定すること |
| **Loki retention** | `retention_period: 14d`（4GB VPS の場合）を明示的に設定すること |
| **ファイアウォール** | exporter ポート（9100/9187/9113/9121）は管理室VPS IPからのみ許可。インターネットに露出しないこと |
| **削除順序** | 旧監視コンテナの停止・削除は、管理室VPS側 Grafana で同等メトリクスを確認した後のみ実施すること。確認前の削除は監視不能を招くため厳禁 |
| **VPSサイズ** | 4GB 推奨。2GB で開始する場合は上記 retention 値を短縮（Prometheus 15d / Loki 7d）すること |

## 関連ドキュメント

- 移行 runbook: `docs/runbooks/monitoring-vps-migration.md`
- ガバナンスチェックリスト: `docs/B-13_mgmt-vps-governance.md`
- スプリント計画: `.claude-pipeline/spec.md`（監視VPS分離セクション）
- 既存監視 runbook: `docs/runbooks/monitoring-step7-vps.md`
- VPS runner runbook: `docs/runbooks/vps-runner-setup.md`
