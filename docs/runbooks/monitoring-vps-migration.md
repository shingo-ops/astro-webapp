# 管理室VPS移行 Runbook（ADR-080）

アプリVPS（49.212.137.46）から管理室VPS（新規）へ監視スタック + CIランナーを移行する手順書。

**対象 ADR**: ADR-080
**所要時間目安**: 4〜6時間（PO操作 + エージェント操作の合計）
**ダウンタイム**: アプリのダウンタイムなし。監視の一時欠損（最大30分程度）は許容

---

## スプリント状態（正本）

セッション開始時に読み、完了・ブロック・担当変更があったら即座に更新する。
`tasks/todo.md` の「監視VPS移行」行と常に同期すること。

| スプリント | フェーズ | 状態 | 担当 | ブロック理由 | 更新日 |
|----------|---------|:---:|------|-----------|------|
| M1 | Phase 1: VPS契約・ファイアウォール・Docker | 完了 | Claude Code | - | 2026-05-29 |
| M2-M6 | compose ファイル分離・設定変更（PR #1146） | 完了 | Codex | - | 2026-05-29 |
| M7a | 管理室VPS claude-monitor ユーザー設定（ADR-079） | 完了 | Claude Code | - | 2026-05-29 |
| M7b | Phase 7: 管理室VPSへ監視スタックをデプロイ・動作確認 | 未着手 | Claude Code | M2-M6デプロイ待ち | 2026-05-29 |
| M7c | Phase 7: アプリVPS旧監視コンテナ撤去 | 未着手 | Claude Code | M7b完了待ち | 2026-05-29 |
| M8 | 旧ボリューム削除（PO確認後・1週間運用後） | 未着手 | PO確認必須 | M7c完了+1週間後 | 2026-05-29 |

**状態の値**: `未着手` / `進行中` / `完了` / `ブロック`

> 管理室VPS IP: 49.212.160.98（2026-05-29 確定・置換済み）

---

## 凡例

| マーク | 意味 |
|--------|------|
| [PO] | しんごさん（GUI操作 or 最終判断が必要） |
| [Agent] | Claude Code / 開発者（CLI操作） |
| [確認] | 実行結果の確認コマンド |

---

## 前提条件チェックリスト

作業開始前に全てを確認する。

- [ ] [PO] さくらVPS 管理画面にログインできる
- [ ] [PO] Cloudflare ダッシュボードにログインできる
- [ ] [PO] 管理室VPSの契約が完了し、パブリックIPが確定している
- [ ] [Agent] アプリVPSへの SSH アクセスが可能
- [ ] [Agent] 管理室VPSへの SSH アクセスが可能（PO がユーザー作成済み）
- [ ] [Agent] `gh` CLI で admin 権限のある認証済み（runner 登録トークン取得に必要）

---

## Phase 0: ダウンタイムゼロ設計の説明

この移行は「先に新環境を立ち上げ → 動作確認 → 旧環境を撤去」の順序で行う。

```
時系列:
  [1] 管理室VPSに監視スタックを起動（アプリVPSの監視はそのまま稼働中）
  [2] 管理室VPSの監視が正常動作していることを確認
  [3] promtail の接続先を管理室VPSの Loki に切り替え（アプリVPS側の変更）
  [4] nginx プロキシの向き先を管理室VPSに変更（Grafana アクセス先の切り替え）
  [5] アプリVPSの監視コンテナを停止・撤去
```

Phase 1〜3 の間、アプリVPSの監視コンテナは稼働を続けるため、監視の空白期間は Phase 4（プロキシ切り替え）前後の数分間のみ。

---

## Phase 1: 管理室VPS セットアップ

### Step 1-1: VPS 契約 [PO]

1. さくらVPS コントロールパネルにログイン
2. 新規サーバー追加:
   - プラン: 2GB メモリ / 50GB SSD
   - OS: Ubuntu 22.04 LTS
   - リージョン: アプリVPSと同じリージョン（東京）
3. パブリックIPを記録: `________` (以下 `49.212.160.98` と表記)

### Step 1-2: ファイアウォール設定 [PO]

さくらVPS コントロールパネルでパケットフィルタを設定する。

**管理室VPS側:**

| 許可ポート | プロトコル | 送信元 | 用途 |
|-----------|----------|--------|------|
| 22 | TCP | PO のIP / Agent のIP | SSH |
| 80 | TCP | 0.0.0.0/0 | nginx（Cloudflare プロキシ受信） |
| 443 | TCP | 0.0.0.0/0 | nginx（HTTPS、Cloudflare origin pull 用） |
| 3000 | TCP | アプリVPSのIP / PO のIP / Agent のIP | Grafana（app.salesanchor.jp/grafana/ の転送先） |
| 3001 | TCP | アプリVPSのIP / PO のIP / Agent のIP | Uptime Kuma（/status/ と monitor.salesanchor.jp の転送先） |
| 9090 | TCP | PO のIP / Agent のIP | Prometheus API / Targets 確認 |

**アプリVPS側（追加ルール）:**

| 許可ポート | プロトコル | 送信元 | 用途 |
|-----------|----------|--------|------|
| 9100 | TCP | `49.212.160.98` のみ | node-exporter scrape |
| 9187 | TCP | `49.212.160.98` のみ | postgres-exporter scrape |
| 9113 | TCP | `49.212.160.98` のみ | nginx-exporter scrape |
| 9121 | TCP | `49.212.160.98` のみ | redis-exporter scrape |
| 3100 | TCP | --- | Loki: 開放しない（promtail は push 元なので管理室VPS側で受信） |

> **重要**: exporter ポートは管理室VPSのIPからのみ許可する。`0.0.0.0/0` で開放しないこと。

promtail（アプリVPS）→ Loki（管理室VPS）の通信は、管理室VPS側でポート 3100 を promtail（アプリVPSのIP）からのみ許可する。

**管理室VPS側（追加ルール）:**

| 許可ポート | プロトコル | 送信元 | 用途 |
|-----------|----------|--------|------|
| 3100 | TCP | `49.212.137.46`（アプリVPS IP）のみ | Loki: promtail からの push 受信 |

### Step 1-3: OS 初期セットアップ [Agent]

```bash
# 管理室VPSにSSHログイン
ssh <USER>@49.212.160.98

# OS アップデート
sudo apt update && sudo apt upgrade -y

# Docker のインストール
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER

# Docker Compose V2 確認
docker compose version
# → Docker Compose version v2.x.x が表示されること

# 再ログイン（docker グループ反映）
exit
ssh <USER>@49.212.160.98

# 確認
docker run --rm hello-world
```

**[確認]:**
```bash
docker --version   # Docker version 24+ を期待
docker compose version  # v2.x を期待
free -h            # 2GB RAM を確認
df -h /            # 50GB SSD を確認
```

### Step 1-4: 作業ディレクトリ作成 [Agent]

```bash
# 管理室VPS上
sudo mkdir -p /opt/salesanchor-monitoring
sudo chown $USER:$USER /opt/salesanchor-monitoring
cd /opt/salesanchor-monitoring

# 監視設定ファイル用ディレクトリ
mkdir -p monitoring/prometheus
mkdir -p monitoring/grafana/provisioning/datasources
mkdir -p monitoring/grafana/provisioning/dashboards/json
mkdir -p monitoring/grafana/provisioning/alerting
mkdir -p monitoring/loki
mkdir -p monitoring/loki/rules
mkdir -p monitoring/promtail
mkdir -p monitoring/gha-exporter
mkdir -p nginx/conf.d
```

---

## Phase 2: 監視スタック移動

### Step 2-1: アプリVPSから設定ファイルを取得 [Agent]

```bash
# ローカルまたはアプリVPSから管理室VPSへ転送

# Prometheus 設定
scp <USER>@49.212.137.46:/path/to/salesanchor/monitoring/prometheus/prometheus.yml \
    <USER>@49.212.160.98:/opt/salesanchor-monitoring/monitoring/prometheus/

# Prometheus アラートルール
scp <USER>@49.212.137.46:/path/to/salesanchor/monitoring/prometheus/alerts.yml \
    <USER>@49.212.160.98:/opt/salesanchor-monitoring/monitoring/prometheus/

# Grafana プロビジョニング
scp -r <USER>@49.212.137.46:/path/to/salesanchor/monitoring/grafana/provisioning/* \
    <USER>@49.212.160.98:/opt/salesanchor-monitoring/monitoring/grafana/provisioning/

# Loki 設定
scp <USER>@49.212.137.46:/path/to/salesanchor/monitoring/loki/loki-config.yaml \
    <USER>@49.212.160.98:/opt/salesanchor-monitoring/monitoring/loki/

# Loki ルール
scp -r <USER>@49.212.137.46:/path/to/salesanchor/monitoring/loki/rules/* \
    <USER>@49.212.160.98:/opt/salesanchor-monitoring/monitoring/loki/rules/

# gha-exporter
scp -r <USER>@49.212.137.46:/path/to/salesanchor/monitoring/gha-exporter/* \
    <USER>@49.212.160.98:/opt/salesanchor-monitoring/monitoring/gha-exporter/
```

### Step 2-2: docker-compose.monitoring.yml を配置 [Agent]

管理室VPS用の docker-compose ファイルをリポジトリで作成し（Sprint M2 で詳細定義）、管理室VPSに配置する。

```bash
# 管理室VPS上
cd /opt/salesanchor-monitoring
# docker-compose.monitoring.yml をここに配置
```

ファイル内容のポイント:

- prometheus の scrape_configs: アプリVPSの exporter をパブリックIP経由で参照
- loki: ポート 3100 を `0.0.0.0:3100:3100` で公開（ファイアウォールでアプリVPS IPのみ許可済み）
- grafana: `GF_SERVER_ROOT_URL` を維持（プロキシ構成に応じて設定）
- uptime-kuma: 外部 HTTP チェック用
- node-exporter: 管理室VPS自身のメトリクス用
- gha-exporter: GitHub API メトリクス用

### Step 2-3: .env ファイル作成 [PO]

```bash
# 管理室VPS上で作成
cat > /opt/salesanchor-monitoring/.env << 'ENVEOF'
GRAFANA_USER=admin
GRAFANA_PASSWORD=<アプリVPSと同じ値を設定>
GF_SERVER_ROOT_URL=https://app.salesanchor.jp/grafana/
DISCORD_WEBHOOK_URL=<既存の Discord Webhook URL>
APP_VPS_IP=49.212.137.46
GITHUB_TOKEN=<gha-exporter 用の GitHub PAT>
ENVEOF

chmod 600 /opt/salesanchor-monitoring/.env
```

### Step 2-4: 管理室VPSでコンテナ起動 [Agent]

```bash
# 管理室VPS上
cd /opt/salesanchor-monitoring
docker compose -f docker-compose.monitoring.yml up -d

# 起動確認
docker compose -f docker-compose.monitoring.yml ps
```

**[確認]:**
```bash
# 全コンテナが healthy/running であること
docker compose -f docker-compose.monitoring.yml ps

# Prometheus が起動しているか
curl -s http://localhost:9090/-/healthy
# → OK

# Grafana が起動しているか
curl -s http://localhost:3000/api/health
# → {"database":"ok"}

# Loki が起動しているか
curl -s http://localhost:3100/ready
# → ready
```

### Step 2-5: Grafana データ移行 [Agent]

既存の Grafana でカスタマイズしたダッシュボードがある場合、export → import する。

```bash
# アプリVPSから Grafana ダッシュボードを export
# (プロビジョニングファイルに含まれるものは自動で復元されるため、
#  手動作成したダッシュボードのみが対象)

# アプリVPS上で
curl -H "Authorization: Bearer <GRAFANA_TOKEN>" \
  "https://app.salesanchor.jp/grafana/api/search" | python3 -m json.tool
# → dashboard の uid を確認

# 各ダッシュボードを JSON で取得
curl -H "Authorization: Bearer <GRAFANA_TOKEN>" \
  "https://app.salesanchor.jp/grafana/api/dashboards/uid/<UID>" \
  -o dashboard-<UID>.json

# 管理室VPSの Grafana にインポート
curl -X POST -H "Content-Type: application/json" \
  -H "Authorization: Bearer <NEW_GRAFANA_TOKEN>" \
  -d @dashboard-<UID>.json \
  "http://localhost:3000/api/dashboards/db"
```

---

## Phase 3: VPS間通信設定（Prometheus scrape target 変更）

### Step 3-1: Prometheus scrape_configs 変更 [Agent]

管理室VPSの `monitoring/prometheus/prometheus.yml` を編集し、scrape target をアプリVPSの IP に変更する。

変更前（同一ホスト参照）:
```yaml
  - job_name: 'node'
    static_configs:
      - targets: ['node-exporter:9100']
```

変更後（リモート参照）:
```yaml
  # 管理室VPS 自身
  - job_name: 'node-exporter'
    static_configs:
      - targets: ['node-exporter:9100']
        labels:
          instance: 'mgmt-vps'

  # アプリVPSの exporter
  - job_name: 'node-exporter'
    static_configs:
      - targets: ['49.212.137.46:9100']
        labels:
          instance: 'app-vps'

  - job_name: 'postgres-exporter'
    static_configs:
      - targets: ['49.212.137.46:9187']
        labels:
          instance: 'app-vps'

  - job_name: 'nginx-exporter'
    static_configs:
      - targets: ['49.212.137.46:9113']
        labels:
          instance: 'app-vps'

  - job_name: 'redis-exporter'
    static_configs:
      - targets: ['49.212.137.46:9121']
        labels:
          instance: 'app-vps'

  # backend /metrics（nginx 経由で app.salesanchor.jp からスクレイプ）
  - job_name: 'backend'
    scheme: https
    metrics_path: /metrics
    tls_config:
      server_name: app.salesanchor.jp
    static_configs:
      - targets: ['49.212.137.46:443']
        labels:
          instance: 'app-vps'
```

### Step 3-2: アプリVPSの exporter ポートバインド変更 [Agent]

アプリVPSの exporter がパブリックIPでリッスンするように ports を変更する。

変更前:
```yaml
  node-exporter:
    ports: []  # ポート公開なし（同一 Docker ネットワーク内通信のみ）
```

変更後:
```yaml
  node-exporter:
    ports:
      - "49.212.137.46:9100:9100"  # パブリックIP でバインド（FWで制限）
```

同様に postgres-exporter (9187), nginx-exporter (9113), redis-exporter (9121) も変更する。

promtail は `PROMTAIL_LOKI_URL=http://49.212.160.98:3100/loki/api/v1/push` を環境変数として渡し、
管理室VPSの Loki へ直接 push する（`-config.expand-env=true` 必須）。

> **注意**: ファイアウォールで管理室VPSのIPからのみ許可済みであること（Phase 1 Step 1-2）。

### Step 3-3: Prometheus の設定リロード [Agent]

```bash
# 管理室VPS上
docker compose -f docker-compose.monitoring.yml restart prometheus

# または設定リロード（再起動なし）
curl -X POST http://localhost:9090/-/reload
```

**[確認]:**
```bash
# Prometheus Targets ページで全ターゲットが UP であること
curl -s http://localhost:9090/api/v1/targets | python3 -c "
import sys, json
data = json.load(sys.stdin)
for t in data['data']['activeTargets']:
    print(f\"{t['labels'].get('job','?'):20s} {t['health']:6s} {t['lastScrape']}\")
"
# → 全ての job が "up" と表示されること
```

### Step 3-4: promtail の Loki 接続先変更 [Agent]

アプリVPSの `monitoring/promtail/promtail.yml` を編集する。

変更前:
```yaml
clients:
  - url: http://loki:3100/loki/api/v1/push
```

変更後:
```yaml
clients:
  - url: http://49.212.160.98:3100/loki/api/v1/push
```

```bash
# アプリVPS上
docker compose restart promtail
```

**[確認]:**
```bash
# 管理室VPSの Grafana で Loki クエリ
# Explore → Loki → {job="containerlogs"} → 最新ログが表示されること
```

---

## Phase 4: Grafana プロキシ変更

2つの選択肢がある。PO が方針を決定する。

### 選択肢 A: 既存URL維持（`https://app.salesanchor.jp/grafana/`）

アプリVPSの nginx の location ブロックで、管理室VPSの Grafana にプロキシする。

```nginx
# アプリVPS の nginx.conf（該当 location のみ変更）
location /grafana/ {
    proxy_pass http://49.212.160.98:3000/grafana/;  # 管理室VPSに向ける
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    # WebSocket support
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
}
```

```bash
# アプリVPS上
docker compose exec nginx nginx -t  # 構文チェック
docker compose exec nginx nginx -s reload
```

### 選択肢 B: 新ドメイン移行（`https://grafana.salesanchor.jp`）

1. [PO] Cloudflare DNS で `grafana.salesanchor.jp` の A レコードを `49.212.160.98` に設定（プロキシ ON）
2. [Agent] 管理室VPSの nginx に `grafana.salesanchor.jp` の server ブロックを追加
3. [Agent] Grafana の `GF_SERVER_ROOT_URL` を `https://grafana.salesanchor.jp/` に変更
4. [Agent] アプリVPSの nginx から `/grafana/` location を削除

**[確認]:**
```bash
# 選択した URL にアクセスして Grafana ログイン画面が表示されること
curl -sI https://app.salesanchor.jp/grafana/ | head -5
# → HTTP/2 200 (または 302 redirect to login)
```

---

## Phase 5: 動作確認チェックリスト

全 Phase 完了後に確認する。

### 監視スタック [Agent]

- [ ] Prometheus Targets: 全ジョブが `up`
  ```bash
  curl -s http://49.212.160.98:9090/api/v1/targets | python3 -c "
  import sys, json
  data = json.load(sys.stdin)
  for t in data['data']['activeTargets']:
      print(f\"{t['labels'].get('job','?'):20s} {t['health']}\")
  "
  ```
- [ ] Grafana: ダッシュボードにメトリクスが表示される
- [ ] Grafana: Discord アラート通知テスト成功
  - Alerting → Contact points → discord-ops → Test
- [ ] Loki: アプリVPSのログが検索できる
  - Explore → Loki → `{job="containerlogs"}` → ログが表示される
- [ ] Uptime Kuma: `app.salesanchor.jp` と `api.salesanchor.jp` を監視中
- [ ] Uptime Kuma: テスト通知が Discord に届く

### アプリVPS [Agent]

- [ ] 全アプリコンテナが正常稼働
  ```bash
  ssh <USER>@49.212.137.46 "docker compose ps"
  # nginx, backend, frontend, postgres, redis, celery-worker, celery-beat, certbot, discord-gateway
  ```
- [ ] メモリ使用量が減少している
  ```bash
  ssh <USER>@49.212.137.46 "free -h"
  # available が 500MB 以上増えていること
  ```
- [ ] exporter がローカルで稼働している
  ```bash
  ssh <USER>@49.212.137.46 "docker compose ps | grep exporter"
  ```

### セキュリティ [Agent]

- [ ] exporter ポートが外部に公開されていない
  ```bash
  # 第三者のIP（自宅PCなど）から確認
  nmap -p 9100,9187,9113,9121 49.212.137.46
  # → 全て filtered/closed であること
  ```
- [ ] Loki ポートが外部に公開されていない
  ```bash
  nmap -p 3100 49.212.160.98
  # → 管理室VPS以外からは filtered/closed であること
  ```

### ブラウザ確認 [PO]

- [ ] Grafana にアクセスしてログインできる
- [ ] ダッシュボードにグラフが表示されている
- [ ] Uptime Kuma のステータスページが表示される
- [ ] アプリ（`app.salesanchor.jp`）が正常動作する

---

## Phase 6: アプリVPSの exporter 専用 docker-compose 分離

アプリVPSの `docker-compose.yml` が肥大化しているため、exporter 群を専用ファイルに分離する。

### Step 6-1: docker-compose.exporters.yml 作成 [Agent]

アプリVPSに `docker-compose.exporters.yml` を新規作成し、以下のコンテナ定義を `docker-compose.yml` から移動する:

- node-exporter
- postgres-exporter
- nginx-exporter
- redis-exporter
- promtail

### Step 6-2: docker-compose.yml から exporter 定義を削除 [Agent]

`docker-compose.yml` から上記 5 コンテナの定義と関連 volumes を削除する。

### Step 6-3: 起動コマンドの変更 [Agent]

```bash
# アプリVPS上
# 変更前
docker compose up -d

# 変更後（両方のファイルを指定）
docker compose -f docker-compose.yml -f docker-compose.exporters.yml up -d
```

> **Tip**: `.env` に `COMPOSE_FILE=docker-compose.yml:docker-compose.exporters.yml` を設定すると、`docker compose up -d` だけで両方読み込まれる。

**[確認]:**
```bash
docker compose -f docker-compose.yml -f docker-compose.exporters.yml ps
# → 全コンテナが healthy/running
```

---

## Phase 7: アプリVPSから旧監視コンテナを撤去

> **注意**: Phase 5 の動作確認チェックリストが全て完了してから実施する。

### Step 7-1: 旧監視コンテナの停止 [Agent]

```bash
# アプリVPS上
docker compose stop prometheus grafana loki uptime-kuma gha-exporter

# コンテナを削除（ボリュームはまだ残す）
docker compose rm -f prometheus grafana loki uptime-kuma gha-exporter
```

### Step 7-2: docker-compose.yml から監視コンテナ定義を削除 [Agent]

以下のサービス定義を `docker-compose.yml` から削除:
- prometheus
- grafana
- loki
- uptime-kuma
- gha-exporter

以下の volumes 定義も削除:
- prometheus_data
- grafana_data
- loki_data
- uptime_kuma_data

### Step 7-3: nginx.conf から監視系プロキシを削除 [Agent]

アプリVPSの `nginx.conf` から以下を削除（選択肢 B を選んだ場合）:
- `/grafana/` の location ブロック
- `/status/` の location ブロック（Uptime Kuma）
- `monitor.salesanchor.jp` の server ブロック

> **選択肢 A** を選んだ場合、`/grafana/` の location は管理室VPSへのプロキシに変更済みのため残す。

### Step 7-4: 旧ボリュームの削除 [PO 確認後]

> **不可逆操作**: PO 確認必須

管理室VPSで監視データが正常に蓄積されていることを確認した後（1週間程度運用してから）:

```bash
# アプリVPS上（PO確認後のみ実行）
docker volume rm salesanchor_prometheus_data
docker volume rm salesanchor_grafana_data
docker volume rm salesanchor_loki_data
docker volume rm salesanchor_uptime_kuma_data
```

**[確認]:**
```bash
# アプリVPS上
docker compose ps
# → 監視コンテナが表示されないこと

free -h
# → available が移行前より 500MB 以上増えていること

docker volume ls
# → prometheus_data, grafana_data, loki_data, uptime_kuma_data が存在しないこと（削除済みの場合）
```

---

## ロールバック手順

移行後に問題が発生した場合、アプリVPSの監視コンテナを復活させる。

### 条件
- 管理室VPSの監視が正常に動かない場合
- Phase 7 で旧ボリュームを削除していない場合のみフルロールバック可能

### 手順

```bash
# 1. アプリVPSの docker-compose.yml を git から復元
ssh <USER>@49.212.137.46
cd /path/to/salesanchor
git checkout develop -- docker-compose.yml nginx/conf.d/

# 2. 監視コンテナを再起動
docker compose up -d prometheus grafana loki promtail uptime-kuma gha-exporter

# 3. promtail の Loki 接続先を元に戻す（ローカルの loki に戻す）
# monitoring/promtail/promtail.yml の clients.url を http://loki:3100/loki/api/v1/push に変更
docker compose restart promtail

# 4. nginx のプロキシ先を元に戻す
docker compose exec nginx nginx -s reload

# 5. 管理室VPSの監視コンテナを停止
ssh <USER>@49.212.160.98
cd /opt/salesanchor-monitoring
docker compose -f docker-compose.monitoring.yml down
```

### 部分ロールバック（特定コンポーネントのみ）

Grafana だけが問題の場合:
```bash
# 管理室VPSの Grafana を停止
ssh <USER>@49.212.160.98 "cd /opt/salesanchor-monitoring && docker compose -f docker-compose.monitoring.yml stop grafana"

# アプリVPSの Grafana を再起動
ssh <USER>@49.212.137.46 "cd /path/to/salesanchor && docker compose up -d grafana"

# nginx のプロキシ先を元に戻す
ssh <USER>@49.212.137.46 "docker compose exec nginx nginx -s reload"
```

---

## 所要時間目安

| Phase | 作業内容 | 時間目安 | 担当 |
|-------|---------|---------|------|
| Phase 0 | 設計確認 | 10分 | PO + Agent |
| Phase 1 | VPS契約・ファイアウォール・Docker | 60分 | PO 30分 + Agent 30分 |
| Phase 2 | 監視スタック起動 | 60分 | Agent |
| Phase 3 | Prometheus scrape + promtail | 30分 | Agent |
| Phase 4 | Grafana プロキシ変更 | 20分 | PO 10分 + Agent 10分 |
| Phase 5 | 動作確認 | 30分 | PO + Agent |
| Phase 6 | exporter 分離 | 30分 | Agent |
| Phase 7 | 旧コンテナ撤去 | 20分 | Agent（PO確認後） |
| **合計** | | **約4〜6時間** | |

---

## 参照ドキュメント

- ADR-080: `docs/adr/ADR-080-monitoring-vps-separation.md`
- ADR-079: `docs/adr/ADR-079-claude-code-monitoring-access.md`（claude-monitor 設定）
- ADR-078: `docs/adr/ADR-078-vps-runner-registration.md`（runner 登録手順）
- 既存監視 runbook: `docs/runbooks/monitoring-step7-vps.md`
- VPS runner runbook: `docs/runbooks/vps-runner-setup.md`
- ガバナンスチェックリスト: `docs/B-13_mgmt-vps-governance.md`
