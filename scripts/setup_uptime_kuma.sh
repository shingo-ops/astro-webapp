#!/bin/bash
# Uptime Kuma 初期モニター設定スクリプト
# Uptime KumaのAPI経由で監視対象を自動登録する
#
# 前提条件:
#   1. Uptime Kumaが起動済みで、初回セットアップ（admin作成）が完了していること
#   2. 以下の環境変数を設定:
#      - UPTIME_KUMA_URL: Uptime KumaのURL（例: http://localhost:3001）
#      - UPTIME_KUMA_USER: 管理者ユーザー名
#      - UPTIME_KUMA_PASS: 管理者パスワード
#
# 使い方:
#   UPTIME_KUMA_URL=http://localhost:3001 \
#   UPTIME_KUMA_USER=admin \
#   UPTIME_KUMA_PASS=yourpassword \
#   bash scripts/setup_uptime_kuma.sh

set -euo pipefail

KUMA_URL="${UPTIME_KUMA_URL:?環境変数 UPTIME_KUMA_URL を設定してください}"
KUMA_USER="${UPTIME_KUMA_USER:?環境変数 UPTIME_KUMA_USER を設定してください}"
KUMA_PASS="${UPTIME_KUMA_PASS:?環境変数 UPTIME_KUMA_PASS を設定してください}"

# jqの存在確認
if ! command -v jq &> /dev/null; then
  echo "ERROR: jq がインストールされていません。apt install jq でインストールしてください。"
  exit 1
fi

echo "=== Uptime Kuma モニター自動設定 ==="

# ログイン（セッションCookieを取得）
COOKIE_JAR=$(mktemp)
trap "rm -f ${COOKIE_JAR}" EXIT

LOGIN_RESPONSE=$(curl -s -c "${COOKIE_JAR}" -X POST "${KUMA_URL}/api/login" \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"${KUMA_USER}\",\"password\":\"${KUMA_PASS}\"}")

TOKEN=$(echo "${LOGIN_RESPONSE}" | jq -r '.token // empty')
if [ -z "${TOKEN}" ]; then
  echo "ERROR: ログインに失敗しました。ユーザー名・パスワードを確認してください。"
  echo "Response: ${LOGIN_RESPONSE}"
  exit 1
fi
echo "✅ ログイン成功"

AUTH_HEADER="Authorization: Bearer ${TOKEN}"

# モニター追加関数
add_monitor() {
  local name="$1"
  local type="$2"
  local url="$3"
  local interval="${4:-60}"
  local extra="${5:-}"

  local body="{
    \"name\": \"${name}\",
    \"type\": \"${type}\",
    \"url\": \"${url}\",
    \"interval\": ${interval},
    \"retryInterval\": 30,
    \"maxretries\": 3,
    \"active\": true
    ${extra:+,$extra}
  }"

  RESPONSE=$(curl -s -b "${COOKIE_JAR}" -X POST "${KUMA_URL}/api/monitors" \
    -H "Content-Type: application/json" \
    -H "${AUTH_HEADER}" \
    -d "${body}")

  local monitor_id=$(echo "${RESPONSE}" | jq -r '.id // empty')
  if [ -n "${monitor_id}" ]; then
    echo "  ✅ ${name} (ID: ${monitor_id})"
  else
    local msg=$(echo "${RESPONSE}" | jq -r '.msg // .message // "unknown error"')
    echo "  ⚠️  ${name}: ${msg}"
  fi
}

echo ""
echo "--- モニターを登録中 ---"

# 1. APIヘルスチェック（最重要）
add_monitor \
  "API Health Check" \
  "http" \
  "https://jarvis-claude.uk/api/health" \
  60 \
  '"method": "GET", "expectedStatusCodes": [200]'

# 2. フロントエンド応答確認
add_monitor \
  "Frontend" \
  "http" \
  "https://jarvis-claude.uk/" \
  60 \
  '"method": "GET", "expectedStatusCodes": [200]'

# 3. HTTPS証明書監視（有効期限30日前に警告）
add_monitor \
  "SSL Certificate" \
  "http" \
  "https://jarvis-claude.uk/" \
  3600 \
  '"method": "GET", "expectedStatusCodes": [200], "expiryNotification": true, "maxTlsCertDaysRemaining": 30'

# 4. Grafana死活確認
add_monitor \
  "Grafana" \
  "http" \
  "https://jarvis-claude.uk/grafana/api/health" \
  120 \
  '"method": "GET", "expectedStatusCodes": [200]'

# 5. ログインAPI応答確認（429でもOK = レート制限が効いている証拠）
add_monitor \
  "Auth API" \
  "http" \
  "https://jarvis-claude.uk/api/v1/auth/me" \
  120 \
  '"method": "GET", "expectedStatusCodes": [401, 403]'

echo ""
echo "=== 設定完了 ==="
echo "Uptime Kuma UI で確認: ${KUMA_URL}"
echo "※ Slackなどの通知設定はUI上で追加してください"
