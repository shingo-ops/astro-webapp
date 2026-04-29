#!/bin/bash
# PostgreSQL 日次バックアップスクリプト
# cronで毎日深夜3:00に実行: 0 3 * * * /home/ubuntu/salesanchor/scripts/backup.sh
#
# 使い方:
#   手動実行: bash /home/ubuntu/salesanchor/scripts/backup.sh
#   リストア: bash /home/ubuntu/salesanchor/scripts/restore.sh <バックアップファイル>

set -euo pipefail

DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="/home/ubuntu/backups/postgres"
COMPOSE_FILE="/home/ubuntu/salesanchor/docker-compose.yml"
DB_USER="${POSTGRES_USER:-jarvis}"
DB_NAME="${POSTGRES_DB:-jarvis_db}"
RETENTION_DAYS=30

mkdir -p "${BACKUP_DIR}"

BACKUP_FILE="${BACKUP_DIR}/jarvis_db_${DATE}.sql.gz"

# PostgreSQLのフルバックアップ（圧縮）
docker compose -f "${COMPOSE_FILE}" exec -T postgres \
  pg_dump -U "${DB_USER}" "${DB_NAME}" \
  | gzip > "${BACKUP_FILE}"

# ファイルの権限を制限（所有者のみ読み書き可能）
chmod 600 "${BACKUP_FILE}"

# 保持期間を超えたバックアップを自動削除
find "${BACKUP_DIR}" -name 'jarvis_db_*.sql.gz' -mtime +${RETENTION_DAYS} -delete

# ログに記録
FILESIZE=$(du -h "${BACKUP_FILE}" | cut -f1)
echo "[$(date)] Backup completed: jarvis_db_${DATE}.sql.gz (${FILESIZE})" \
  >> "${BACKUP_DIR}/backup.log"
