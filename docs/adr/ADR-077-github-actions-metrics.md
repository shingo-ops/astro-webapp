# ADR-077: GitHub Actions CI メトリクスの Prometheus/Grafana 可視化

- **Status**: Accepted
- **Date**: 2026-05-28
- **Author**: shingo-ops (PO)
- **Implemented by**: Hikky-dev (Claude Code)

---

## What（何を・なぜ）

GitHub Actions の CI 実行データ（ワークフロー・ジョブ・ステップの実行時間と成否）を
Prometheus で収集し、Grafana で可視化する仕組みを導入する。

**解決する課題**

- どのジョブが遅いか・どのワークフローが失敗しがちかが数字で見えない
- CI 待ち時間がじわじわ伸びていても気づけない
- 改善施策の before/after を定量評価できない

**ユーザー価値**

- Grafana ダッシュボード 1 枚でワークフロー成功率・平均実行時間・遅いジョブ Top 10 を確認できる
- CI 品質の継続的モニタリングにより、開発速度低下を早期検知できる

---

## Scope（対象）

- 監視対象: `shingo-ops/salesanchor` リポジトリの全ワークフロー（28 本）
- 取得粒度: ワークフロー / ジョブ / ステップ の 3 階層
- 保存先: 既存 Prometheus（30 日保持）
- 表示先: 既存 Grafana（`app.salesanchor.jp/grafana/`）

**スコープ外**

- アラートルールの追加（Phase 2 で検討）
- self-hosted runner のメトリクス（ADR-029 で別管理）

---

## Decision（技術選択の理由）

### ツール: `gravitational/gha-exporter` v0.0.15

| 比較対象 | 選定理由 |
|---------|---------|
| `Labbs/github-actions-exporter` | 高カーディナリティ問題でクラッシュ実績あり（Issue #49）→ 除外 |
| `scality/gh-actions-exporter` | Webhook 方式のため nginx 変更が必要 → 今回スコープ外 |
| `gravitational/gha-exporter` | **API ポーリング + GitHub App 認証。nginx 変更不要。2025年11月まで継続メンテナンス実績** |

### 認証方式: GitHub App（App ID: 3890309）

PAT（Personal Access Token）より GitHub App を選んだ理由:
- 権限スコープを `actions: read` のみに限定できる
- しんごさん個人の PAT に依存しない（PAT は rotate が手動）
- API レート制限のクォータが PAT より大きい

### 秘密鍵の管理: ファイルマウント方式

`.env` に PEM 内容を直接書くとエスケープ問題が生じる。
VPS 上の安全なパスにファイルとして配置し、コンテナにマウントする。
`.env` には**ファイルパスのみ**を記録する。

---

## How（実装概要）

### 追加ファイル

```
monitoring/gha-exporter/
  Dockerfile               ← binary DL + entrypoint wrapper
  docker-entrypoint.sh     ← GHA_APP_KEY_FILE → GHA_APP_KEY 変換
monitoring/grafana/provisioning/dashboards/json/
  github-actions-ci.json   ← Grafana ダッシュボード定義
docs/adr/
  ADR-077-github-actions-metrics.md  ← 本ファイル
```

### 変更ファイル

| ファイル | 変更内容 |
|---------|---------|
| `docker-compose.yml` | `gha-exporter` サービス追加（`build:` 方式・backnet のみ） |
| `monitoring/prometheus/prometheus.yml` | `gha-exporter` scrape job 追加（60s間隔） |
| `monitoring/tokens.yml` | `gha_exporter: "v0.0.15"` 追加（バージョン SSoT） |
| `monitoring/scripts/validate_tokens.py` | CHECK 5: Dockerfile ARG バージョン整合性チェック追加 |
| `.env.example` | `GHA_APP_ID`, `GHA_APP_KEY_PATH` 追加 |

### VPS デプロイ手順（PR マージ後）

```bash
# 1. 秘密鍵ファイルを VPS に配置
scp ~/Downloads/salesanchor-ci-metrics.*.pem \
    ubuntu@vps:/home/ubuntu/salesanchor/secrets/gha-exporter-key.pem
chmod 600 /home/ubuntu/salesanchor/secrets/gha-exporter-key.pem

# 2. .env に値を追加
echo "GHA_APP_ID=3890309" >> /home/ubuntu/salesanchor/.env
echo "GHA_APP_KEY_PATH=/home/ubuntu/salesanchor/secrets/gha-exporter-key.pem" \
    >> /home/ubuntu/salesanchor/.env

# 3. コンテナをビルド・起動
cd /home/ubuntu/salesanchor
docker compose build gha-exporter
docker compose up -d gha-exporter
```

---

## 標準化・管理定着

| 仕組み | 内容 |
|--------|------|
| バージョン SSoT | `monitoring/tokens.yml` の `gha_exporter:` で一元管理 |
| CI 整合性チェック | `validate_tokens.py` CHECK 5 が Dockerfile ARG との一致を自動検証 |
| Grafana as-code | ダッシュボードは JSON ファイルで管理・自動プロビジョニング |
| ブランチ保護 | PR 経由でのみ変更可能（Branch Protection） |

---

## リスクと対処

| リスク | 対処 |
|--------|------|
| gha-exporter 停止中のデータ欠損 | `--backfill` フラグで起動時に最大2時間分を遡及取得 |
| GitHub API レート制限 | `--sleep=60s` でポーリング間隔を制御。GitHub App 認証でクォータ確保 |
| 秘密鍵の漏洩 | ファイルマウント方式（.env に書かない）+ `chmod 600` + `.gitignore` 除外済み |
