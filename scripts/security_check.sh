#!/bin/bash
# ===================================
# Sales Anchor セキュリティチェックスクリプト
# ===================================
# 用途: ペネトレーションテスト前の自動セキュリティ検証
# 実行場所: VPS側（本番サーバー）
# 使い方: bash scripts/security_check.sh https://jarvis-claude.uk
#
# 前提: curl, openssl, nmap がインストール済みであること

set -euo pipefail

TARGET_URL="${1:-https://jarvis-claude.uk}"
PASS=0
FAIL=0
WARN=0

print_result() {
    local status=$1
    local message=$2
    case $status in
        PASS) echo "  ✓ PASS: $message"; PASS=$((PASS + 1)) ;;
        FAIL) echo "  ✗ FAIL: $message"; FAIL=$((FAIL + 1)) ;;
        WARN) echo "  ! WARN: $message"; WARN=$((WARN + 1)) ;;
    esac
}

echo "============================================"
echo "Sales Anchor セキュリティチェック"
echo "対象: $TARGET_URL"
echo "日時: $(date '+%Y-%m-%d %H:%M:%S')"
echo "============================================"
echo ""

# --- 1. セキュリティヘッダー検証 ---
echo "[1/5] セキュリティヘッダー検証"
HEADERS=$(curl -sI "$TARGET_URL" 2>/dev/null)

check_header() {
    local header_name=$1
    local expected_value=$2
    if echo "$HEADERS" | grep -qi "$header_name"; then
        if [ -n "$expected_value" ]; then
            if echo "$HEADERS" | grep -qi "$header_name.*$expected_value"; then
                print_result PASS "$header_name: $expected_value"
            else
                print_result WARN "$header_name が存在するが値が異なる"
            fi
        else
            print_result PASS "$header_name が設定済み"
        fi
    else
        print_result FAIL "$header_name が未設定"
    fi
}

check_header "Strict-Transport-Security" "max-age="
check_header "X-Frame-Options" "DENY"
check_header "X-Content-Type-Options" "nosniff"
check_header "Referrer-Policy" ""
check_header "Permissions-Policy" ""
check_header "Content-Security-Policy" ""
check_header "X-XSS-Protection" ""

# server_tokens off の確認
if echo "$HEADERS" | grep -qi "^server:.*nginx/"; then
    print_result FAIL "Nginxバージョンが露出している（server_tokens off 未設定）"
else
    print_result PASS "Nginxバージョン非公開（server_tokens off）"
fi

echo ""

# --- 2. SSL/TLS 設定検証 ---
echo "[2/5] SSL/TLS 設定検証"
DOMAIN=$(echo "$TARGET_URL" | sed 's|https://||' | sed 's|/.*||')

# TLS 1.2以上のみ許可されているか
if openssl s_client -connect "$DOMAIN:443" -tls1_2 </dev/null 2>/dev/null | grep -q "CONNECTED"; then
    print_result PASS "TLS 1.2 対応"
else
    print_result FAIL "TLS 1.2 未対応"
fi

if openssl s_client -connect "$DOMAIN:443" -tls1_3 </dev/null 2>/dev/null | grep -q "CONNECTED"; then
    print_result PASS "TLS 1.3 対応"
else
    print_result WARN "TLS 1.3 未対応"
fi

# 古いプロトコルが無効か
if openssl s_client -connect "$DOMAIN:443" -tls1 </dev/null 2>/dev/null | grep -q "CONNECTED"; then
    print_result FAIL "TLS 1.0 が有効（脆弱）"
else
    print_result PASS "TLS 1.0 無効"
fi

if openssl s_client -connect "$DOMAIN:443" -tls1_1 </dev/null 2>/dev/null | grep -q "CONNECTED"; then
    print_result FAIL "TLS 1.1 が有効（脆弱）"
else
    print_result PASS "TLS 1.1 無効"
fi

# 証明書の有効期限
CERT_EXPIRY=$(echo | openssl s_client -servername "$DOMAIN" -connect "$DOMAIN:443" 2>/dev/null | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2)
if [ -n "$CERT_EXPIRY" ]; then
    EXPIRY_EPOCH=$(date -j -f "%b %d %H:%M:%S %Y %Z" "$CERT_EXPIRY" "+%s" 2>/dev/null || date -d "$CERT_EXPIRY" "+%s" 2>/dev/null || echo "0")
    NOW_EPOCH=$(date "+%s")
    DAYS_LEFT=$(( (EXPIRY_EPOCH - NOW_EPOCH) / 86400 ))
    if [ "$DAYS_LEFT" -gt 30 ]; then
        print_result PASS "SSL証明書有効: 残り${DAYS_LEFT}日"
    elif [ "$DAYS_LEFT" -gt 0 ]; then
        print_result WARN "SSL証明書の期限切れ間近: 残り${DAYS_LEFT}日"
    else
        print_result FAIL "SSL証明書が期限切れ"
    fi
fi

echo ""

# --- 3. API認証検証 ---
echo "[3/5] API認証検証"

# 未認証アクセスの拒否確認
# GETメソッドのエンドポイントのみ（POSTのみのエンドポイントは405を返すため除外）
ENDPOINTS=("/api/v1/customers" "/api/v1/deals" "/api/v1/orders" "/api/v1/dashboard")
for endpoint in "${ENDPOINTS[@]}"; do
    STATUS=$(curl -so /dev/null -w "%{http_code}" "$TARGET_URL$endpoint" 2>/dev/null)
    if [ "$STATUS" = "401" ] || [ "$STATUS" = "403" ]; then
        print_result PASS "未認証拒否: $endpoint (${STATUS})"
    else
        print_result FAIL "未認証アクセス可能: $endpoint (${STATUS})"
    fi
done

# POSTエンドポイントの未認証拒否確認
STATUS=$(curl -so /dev/null -w "%{http_code}" -X POST "$TARGET_URL/api/v1/admin/tenants" -H "Content-Type: application/json" -d '{}' 2>/dev/null)
if [ "$STATUS" = "401" ] || [ "$STATUS" = "403" ]; then
    print_result PASS "未認証拒否: /api/v1/admin/tenants POST (${STATUS})"
else
    print_result FAIL "未認証アクセス可能: /api/v1/admin/tenants POST (${STATUS})"
fi

# ヘルスチェックはアクセス可能
STATUS=$(curl -so /dev/null -w "%{http_code}" "$TARGET_URL/api/health" 2>/dev/null)
if [ "$STATUS" = "200" ]; then
    print_result PASS "ヘルスチェック公開: /api/health (200)"
else
    print_result WARN "ヘルスチェック応答異常: /api/health (${STATUS})"
fi

# Swagger UIが本番で無効か
STATUS=$(curl -so /dev/null -w "%{http_code}" "$TARGET_URL/docs" 2>/dev/null)
if [ "$STATUS" = "404" ] || [ "$STATUS" = "301" ] || [ "$STATUS" = "302" ]; then
    print_result PASS "Swagger UI無効（本番）"
else
    print_result WARN "Swagger UIが公開されている可能性 (${STATUS})"
fi

echo ""

# --- 4. ポートスキャン ---
echo "[4/5] 公開ポート確認"
if command -v nmap &> /dev/null; then
    OPEN_PORTS=$(nmap -sT -p 1-1024 "$DOMAIN" 2>/dev/null | grep "open" | awk '{print $1}' | cut -d/ -f1 | tr '\n' ',')
    EXPECTED_PORTS="22,80,443"
    for port in 22 80 443; do
        if echo "$OPEN_PORTS" | grep -q "$port"; then
            print_result PASS "ポート $port 公開（想定通り）"
        else
            print_result WARN "ポート $port が閉じている"
        fi
    done
    # 想定外のポートが開いていないか
    UNEXPECTED=$(echo "$OPEN_PORTS" | tr ',' '\n' | grep -vE "^(22|80|443|)$" | tr '\n' ',' | sed 's/,$//')
    if [ -n "$UNEXPECTED" ]; then
        print_result FAIL "想定外のポートが公開: $UNEXPECTED"
    else
        print_result PASS "想定外のポートなし"
    fi
else
    print_result WARN "nmapがインストールされていないためスキップ"
fi

echo ""

# --- 5. レート制限確認 ---
echo "[5/5] レート制限テスト"
RATE_FAIL=0
for i in $(seq 1 15); do
    STATUS=$(curl -so /dev/null -w "%{http_code}" -X POST "$TARGET_URL/api/v1/auth/login" -H "Content-Type: application/json" -d '{"email":"test@test.com","password":"test"}' 2>/dev/null)
    if [ "$STATUS" = "429" ]; then
        RATE_FAIL=1
        break
    fi
done

if [ "$RATE_FAIL" = "1" ]; then
    print_result PASS "レート制限動作確認（${i}リクエスト目で429）"
else
    print_result WARN "レート制限が確認できなかった（15リクエスト以内で429にならず）"
fi

echo ""

# --- 結果サマリー ---
echo "============================================"
echo "結果サマリー"
echo "============================================"
echo "  合格: $PASS"
echo "  警告: $WARN"
echo "  不合格: $FAIL"
echo ""

TOTAL=$((PASS + FAIL + WARN))
if [ "$FAIL" -eq 0 ]; then
    echo "  全チェック合格 - ペネトレーションテスト準備完了"
else
    echo "  不合格項目あり - 修正後に再実行してください"
fi
echo "============================================"

exit $FAIL
