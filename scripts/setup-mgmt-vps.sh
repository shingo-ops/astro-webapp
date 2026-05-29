#!/usr/bin/env bash
# setup-mgmt-vps.sh: 管理室VPS 初期セットアップスクリプト
#
# 使用方法（管理室VPS 上で実行）:
#   bash setup-mgmt-vps.sh
#
# 実行前提:
#   - Ubuntu 24.04 LTS
#   - sudo 権限を持つユーザーで実行
#
# 関連 ADR: ADR-080
# 関連 runbook: docs/runbooks/monitoring-vps-migration.md

set -euo pipefail

LOG_FILE="/tmp/setup-mgmt-vps.log"
exec > >(tee -a "$LOG_FILE") 2>&1

echo "=== 管理室VPS 初期セットアップ 開始 ==="
echo "日時: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# ---- Step 1: システム更新 ------------------------------------------------
echo "[1/6] システムパッケージを更新中..."
sudo apt-get update -q
sudo apt-get upgrade -y -q
echo "      完了"

# ---- Step 2: Docker インストール（冪等性: 既存なら skip）-----------------
echo "[2/6] Docker をインストール中..."
if command -v docker &>/dev/null; then
  echo "      Docker は既にインストール済みです: $(docker --version)"
else
  # 公式インストールスクリプト使用
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker ubuntu
  echo "      Docker インストール完了: $(docker --version)"
fi

# Docker サービス起動・自動起動設定
sudo systemctl enable docker
sudo systemctl start docker
echo "      Docker サービス: $(sudo systemctl is-active docker)"

# ---- Step 3: ディレクトリ構造作成 ----------------------------------------
echo "[3/6] ディレクトリ構造を作成中..."
DIRS=(
  "/opt/salesanchor-monitoring"
  "/opt/salesanchor-monitoring/prometheus"
  "/opt/salesanchor-monitoring/grafana"
  "/opt/salesanchor-monitoring/grafana/provisioning"
  "/opt/salesanchor-monitoring/grafana/provisioning/datasources"
  "/opt/salesanchor-monitoring/grafana/provisioning/dashboards"
  "/opt/salesanchor-monitoring/grafana/provisioning/alerting"
  "/opt/salesanchor-monitoring/loki"
  "/opt/salesanchor-monitoring/uptime-kuma"
  "/opt/salesanchor-monitoring/runner"
)

for dir in "${DIRS[@]}"; do
  if [ ! -d "$dir" ]; then
    sudo mkdir -p "$dir"
    echo "      作成: $dir"
  else
    echo "      既存: $dir"
  fi
done

sudo chown -R ubuntu:ubuntu /opt/salesanchor-monitoring
echo "      ディレクトリ構造作成完了"

# ---- Step 4: Docker ボリューム作成 ----------------------------------------
echo "[4/6] Docker ボリュームを作成中..."
VOLUMES=(
  "mgmt_grafana_data"
  "mgmt_prometheus_data"
  "mgmt_loki_data"
  "mgmt_uptime_kuma_data"
)

for vol in "${VOLUMES[@]}"; do
  if ! docker volume inspect "$vol" &>/dev/null; then
    docker volume create "$vol"
    echo "      作成: $vol"
  else
    echo "      既存: $vol"
  fi
done

# ---- Step 5: UFW ファイアウォール設定 ------------------------------------
echo "[5/6] ファイアウォールを設定中..."
if command -v ufw &>/dev/null; then
  # デフォルトポリシー
  sudo ufw default deny incoming
  sudo ufw default allow outgoing

  # SSH（必須）
  sudo ufw allow 22/tcp comment 'SSH'

  # HTTP/HTTPS（Grafana 公開用）
  sudo ufw allow 80/tcp comment 'HTTP'
  sudo ufw allow 443/tcp comment 'HTTPS'

  # Grafana（直接アクセス用 - Cloudflare Tunnel 使用時は不要）
  sudo ufw allow 3000/tcp comment 'Grafana'

  # UFW 有効化（既に有効なら skip）
  echo "y" | sudo ufw enable 2>/dev/null || true
  echo "      UFW 設定完了"
  sudo ufw status
else
  echo "      UFW が見つかりません。スキップします"
fi

# ---- Step 6: 基本パッケージインストール ----------------------------------
echo "[6/6] 基本パッケージをインストール中..."
sudo apt-get install -y -q \
  curl \
  wget \
  git \
  jq \
  nmap \
  htop \
  unzip
echo "      完了"

# ---- 完了 ----------------------------------------------------------------
echo ""
echo "=== セットアップ完了 ==="
echo ""
echo "確認コマンド:"
echo "  docker --version"
echo "  docker ps"
echo "  ls /opt/salesanchor-monitoring/"
echo "  sudo ufw status"
echo ""
echo "次のステップ:"
echo "  1. docker-compose.monitoring.yml を /opt/salesanchor-monitoring/ に配置"
echo "  2. .env.monitoring を作成"
echo "  3. docker compose -f docker-compose.monitoring.yml up -d"
echo ""
echo "ログ保存先: $LOG_FILE"
