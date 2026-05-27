#!/bin/bash
# Uptime Kuma 初期モニター設定スクリプト
# Uptime KumaのAPI経由で監視対象を自動登録する
#
# 前提条件:
#   1. Uptime Kumaが起動済みで、初回セットアップ（admin作成）が完了していること
#   2. 以下の環境変数を設定:
#      - UPTIME_KUMA_URL: Uptime KumaのURL（例: https://monitor.salesanchor.jp）
#      - UPTIME_KUMA_USER: 管理者ユーザー名
#      - UPTIME_KUMA_PASS: 管理者パスワード
#
# 使い方:
#   UPTIME_KUMA_URL=https://monitor.salesanchor.jp \
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

# 1. App（本番フロントエンド）
add_monitor \
  "App（本番）" \
  "http" \
  "https://app.salesanchor.jp/" \
  30 \
  '"method": "GET", "expectedStatusCodes": [200], "maxretries": 3'

# 2. API ヘルスチェック（最重要）
add_monitor \
  "API Health Check" \
  "http" \
  "https://api.salesanchor.jp/api/health" \
  30 \
  '"method": "GET", "expectedStatusCodes": [200], "maxretries": 3'

# 3. LP（ランディングページ）
add_monitor \
  "LP（salesanchor.jp）" \
  "http" \
  "https://salesanchor.jp/" \
  60 \
  '"method": "GET", "expectedStatusCodes": [200], "maxretries": 3'

# 4. PostgreSQL（TCP死活）
add_monitor \
  "PostgreSQL" \
  "port" \
  "localhost" \
  60 \
  '"port": 5432, "maxretries": 3'

# 5. Redis（TCP死活）
add_monitor \
  "Redis" \
  "port" \
  "localhost" \
  60 \
  '"port": 6379, "maxretries": 3'

# 6. Meta Graph API（外部サービス）
# 認証なしでアクセスすると 400 が返るため、200/400 どちらも正常とみなす
add_monitor \
  "Meta Graph API" \
  "http" \
  "https://graph.facebook.com/" \
  300 \
  '"method": "GET", "expectedStatusCodes": [200, 400], "maxretries": 3'

# 7. Firebase Auth（認証基盤）
# auth.salesanchor.jp は Firebase Auth のカスタムドメイン
add_monitor \
  "Firebase Auth" \
  "http" \
  "https://auth.salesanchor.jp" \
  120 \
  '"method": "GET", "expectedStatusCodes": [200, 302, 404], "maxretries": 3'

# 8. Google Calendar API（外部サービス）
# ドメイン到達確認のみ（実APIは叩かない — コスト発生防止）
add_monitor \
  "Google Calendar API" \
  "http" \
  "https://www.googleapis.com/" \
  300 \
  '"method": "GET", "expectedStatusCodes": [200, 404], "maxretries": 2'

# 9. Gemini AI（外部サービス）
# ドメイン到達確認のみ（実APIは叩かない — コスト発生防止）
add_monitor \
  "Gemini AI" \
  "http" \
  "https://generativelanguage.googleapis.com/" \
  300 \
  '"method": "GET", "expectedStatusCodes": [200, 404], "maxretries": 2'

echo ""
echo "=== 設定完了 ==="
echo "Uptime Kuma UI で確認: ${KUMA_URL}"
echo "※ Discord などの通知設定はUI上で追加してください"
