#!/usr/bin/env bash
# =============================================================
# B-7: 月次nmapスキャンスクリプト
#
# 目的:
#   外部公開ポートを定期的に確認し、意図しないポートが
#   開いていないかチェックする。
#
# 使い方（ローカルPCから実行）:
#   bash scripts/nmap_scan.sh
#
# cron登録（毎月1日 10:00）:
#   0 10 1 * * /path/to/scripts/nmap_scan.sh >> /var/log/nmap_scan.log 2>&1
#
# 前提:
#   - nmapがインストール済み（brew install nmap / apt install nmap）
# =============================================================

set -euo pipefail

TARGET="jarvis-claude.uk"
EXPECTED_PORTS="22,80,443"
DATE_TAG=$(date +%Y%m%d)

echo "=== nmap スキャン開始: $(date) ==="
echo "  対象: ${TARGET}"
echo "  許可ポート: ${EXPECTED_PORTS}"
echo ""

# TCPポートスキャン（上位1000ポート）
echo "--- TCP スキャン ---"
SCAN_RESULT=$(nmap -Pn -sT --top-ports 1000 "$TARGET" 2>&1)
echo "$SCAN_RESULT"

# 開いているポートを抽出
OPEN_PORTS=$(echo "$SCAN_RESULT" | grep "^[0-9]" | grep "open" | awk -F/ '{print $1}' | sort -n)

echo ""
echo "--- 結果判定 ---"

UNEXPECTED=""
for PORT in $OPEN_PORTS; do
  if ! echo "$EXPECTED_PORTS" | grep -qw "$PORT"; then
    UNEXPECTED="${UNEXPECTED} ${PORT}"
  fi
done

if [ -z "$UNEXPECTED" ]; then
  echo "OK: 許可されたポートのみ開いています（${EXPECTED_PORTS}）"
else
  echo "WARNING: 想定外のポートが開いています:${UNEXPECTED}"
  echo "  → 即座に確認し、不要なポートはUFWで閉じてください"
  echo "  → 対応: sudo ufw deny <ポート番号>"
fi

echo ""
echo "=== nmap スキャン完了: $(date) ==="
