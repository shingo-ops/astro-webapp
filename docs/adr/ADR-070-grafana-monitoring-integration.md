# ADR-070: Grafana ドメイン移行 + Uptime Kuma→Prometheus 統合

**Status**: Accepted  
**Date**: 2026-05-25  
**Author**: shingo-ops (PO)

---

## What（何を・なぜ・ユーザー価値・事業制約）

### 背景

Grafana の `GF_SERVER_ROOT_URL` が旧ドメイン `jarvis-claude.uk` のままになっており、
`https://app.salesanchor.jp/grafana/` からアクセスするとログイン後のリダイレクトが旧ドメインに
飛んでしまい、事実上 Grafana が使えない状態だった。

また Uptime Kuma（死活監視）と Grafana（メトリクス可視化）が独立しており、
システム全体の状態を一画面で確認できる「管理室」が存在しなかった。

### 決定

1. **Grafana の `GF_SERVER_ROOT_URL` を `app.salesanchor.jp` に変更**し、正常動作を回復する
2. **Uptime Kuma の Prometheus メトリクスエンドポイント（`/metrics`）を Prometheus の scrape 対象に追加**し、
   Grafana から死活監視データを可視化できるようにする

### スコープ

- `docker-compose.yml`: `GF_SERVER_ROOT_URL` を `app.salesanchor.jp` に変更（**1行**）
- `monitoring/prometheus/prometheus.yml`: `uptime-kuma` scrape job を追加（**5行**）
- 既存アプリへのコード変更: **ゼロ**
- nginx.conf: **変更なし**（`app.salesanchor.jp` の `/grafana/` プロキシは既存）

### スコープ外（VPS 上でのオペレーション・UI 操作）

以下は本 PR に含まない。デプロイ後に手動で実施する:

1. VPS で Grafana コンテナ再起動: `docker compose restart grafana`
2. VPS で `.env` に `UPTIME_KUMA_API_KEY=<key>` を追加
   - Uptime Kuma の Settings > API Keys で生成
3. VPS で Prometheus コンテナ再起動: `docker compose restart prometheus`
4. Grafana で Uptime Kuma ダッシュボードをインポート（Community Dashboard ID: 18278）

### アクセス

- Grafana（管理室）: `https://app.salesanchor.jp/grafana/`
- Uptime Kuma（死活監視）: `https://monitor.salesanchor.jp/`
- 旧ドメイン: `https://jarvis-claude.uk/grafana/`（nginx プロキシ済み・引き続き動作）

---

## Why（採用理由）

- `GF_SERVER_ROOT_URL` 変更は **1行のみ**・ダウンタイムゼロ・他設定への影響なし
- Uptime Kuma v2 は Prometheus メトリクスエンドポイントをネイティブサポート（追加コンテナ不要）
- 死活監視（Uptime Kuma）とシステムメトリクス（Prometheus + node/postgres/nginx exporter）を
  Grafana 1 画面に統合することで運用コストを最小化
- Grafana Community Dashboard 18278 により、ダッシュボード開発コストゼロで可視化できる
