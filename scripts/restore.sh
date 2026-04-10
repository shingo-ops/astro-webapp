#!/bin/bash
# PostgreSQL リストアスクリプト
# 障害時にバックアップからデータベースを復元する
#
# 使い方:
#   bash /home/ubuntu/astro-webapp/scripts/restore.sh /home/ubuntu/backups/postgres/jarvis_db_20260410_030000.sql.gz

set -euo pipefail

COMPOSE_FILE="/home/ubuntu/astro-webapp/docker-compose.yml"
DB_USER="${POSTGRES_USER:-jarvis}"
DB_NAME="${POSTGRES_DB:-jarvis_db}"

if [ $# -ne 1 ]; then
  echo "使い方: $0 <バックアップファイルのパス>"
  echo "例:     $0 /home/ubuntu/backups/postgres/jarvis_db_20260410_030000.sql.gz"
  echo ""
  echo "利用可能なバックアップ一覧:"
  ls -lh /home/ubuntu/backups/postgres/jarvis_db_*.sql.gz 2>/dev/null || echo "  バックアップが見つかりません"
  exit 1
fi

BACKUP_FILE="$1"

if [ ! -f "${BACKUP_FILE}" ]; then
  echo "エラー: ファイルが見つかりません: ${BACKUP_FILE}"
  exit 1
fi

echo "=========================================="
echo "  PostgreSQL リストア"
echo "=========================================="
echo "バックアップ: ${BACKUP_FILE}"
echo "データベース: ${DB_NAME}"
echo ""
echo "警告: 現在のデータベースの内容は上書きされます。"
read -p "本当に実行しますか？ (yes/no): " CONFIRM

if [ "${CONFIRM}" != "yes" ]; then
  echo "キャンセルしました。"
  exit 0
fi

echo ""
echo "リストアを開始します..."

gunzip < "${BACKUP_FILE}" \
  | docker compose -f "${COMPOSE_FILE}" exec -T postgres \
    psql -U "${DB_USER}" -d "${DB_NAME}"

echo ""
echo "リストアが完了しました。"
echo "動作確認: curl https://jarvis-claude.uk/api/health"
