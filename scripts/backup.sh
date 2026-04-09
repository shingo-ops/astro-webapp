#!/bin/bash
# PostgreSQL 日次バックアップスクリプト
# cronで毎日深夜3:00に実行: 0 3 * * * /home/deploy/myapp/scripts/backup.sh
#
# 使い方:
#   手動実行: bash /home/deploy/myapp/scripts/backup.sh
#   リストア: gunzip < /home/deploy/backups/myapp_db_XXXXXXXX_XXXXXX.sql.gz \
#             | docker compose exec -T postgres psql -U myapp_user -d myapp_db

set -euo pipefail

DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="/home/deploy/backups"
COMPOSE_FILE="/home/deploy/myapp/docker-compose.yml"
DB_USER="myapp_user"
DB_NAME="myapp_db"
RETENTION_DAYS=30

mkdir -p "${BACKUP_DIR}"

BACKUP_FILE="${BACKUP_DIR}/myapp_db_${DATE}.sql.gz"

# PostgreSQLのフルバックアップ（圧縮）
docker compose -f "${COMPOSE_FILE}" exec -T postgres \
  pg_dump -U "${DB_USER}" "${DB_NAME}" \
  | gzip > "${BACKUP_FILE}"

# ファイルの権限を制限（所有者のみ読み書き可能）
chmod 600 "${BACKUP_FILE}"

# 保持期間を超えたバックアップを自動削除
find "${BACKUP_DIR}" -name 'myapp_db_*.sql.gz' -mtime +${RETENTION_DAYS} -delete

# ログに記録
FILESIZE=$(du -h "${BACKUP_FILE}" | cut -f1)
echo "[$(date)] Backup completed: myapp_db_${DATE}.sql.gz (${FILESIZE})" \
  >> "${BACKUP_DIR}/backup.log"
