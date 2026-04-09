#!/bin/bash
# audit_logs 90日アーカイブスクリプト
# 90日以上前のaudit_logsをCSV出力後に削除する
# cronで毎月1日に実行: 0 4 1 * * /home/deploy/myapp/scripts/archive_audit_logs.sh
#
# 使い方:
#   手動実行: bash /home/deploy/myapp/scripts/archive_audit_logs.sh
#   アーカイブ先: /home/deploy/backups/audit_archives/

set -euo pipefail

COMPOSE_FILE="/home/deploy/myapp/docker-compose.yml"
DB_USER="myapp_user"
DB_NAME="myapp_db"
ARCHIVE_DIR="/home/deploy/backups/audit_archives"
DATE=$(date +%Y%m%d)
RETENTION_DAYS=90

mkdir -p "${ARCHIVE_DIR}"

# テナントスキーマの一覧を取得
SCHEMAS=$(docker compose -f "${COMPOSE_FILE}" exec -T postgres \
  psql -U "${DB_USER}" -d "${DB_NAME}" -t -A -c \
  "SELECT schema_name FROM information_schema.schemata WHERE schema_name LIKE 'tenant_%' ORDER BY schema_name;")

TOTAL_ARCHIVED=0

for SCHEMA in ${SCHEMAS}; do
  # 90日以上前のレコード数を確認
  COUNT=$(docker compose -f "${COMPOSE_FILE}" exec -T postgres \
    psql -U "${DB_USER}" -d "${DB_NAME}" -t -A -c \
    "SELECT COUNT(*) FROM ${SCHEMA}.audit_logs WHERE created_at < NOW() - INTERVAL '${RETENTION_DAYS} days';")

  if [ "${COUNT}" -gt 0 ]; then
    ARCHIVE_FILE="${ARCHIVE_DIR}/${SCHEMA}_audit_logs_${DATE}.csv.gz"

    # CSVでエクスポート（圧縮）
    docker compose -f "${COMPOSE_FILE}" exec -T postgres \
      psql -U "${DB_USER}" -d "${DB_NAME}" -c \
      "COPY (SELECT * FROM ${SCHEMA}.audit_logs WHERE created_at < NOW() - INTERVAL '${RETENTION_DAYS} days' ORDER BY created_at) TO STDOUT WITH CSV HEADER;" \
      | gzip > "${ARCHIVE_FILE}"

    chmod 600 "${ARCHIVE_FILE}"

    # エクスポート成功後に削除
    docker compose -f "${COMPOSE_FILE}" exec -T postgres \
      psql -U "${DB_USER}" -d "${DB_NAME}" -c \
      "DELETE FROM ${SCHEMA}.audit_logs WHERE created_at < NOW() - INTERVAL '${RETENTION_DAYS} days';"

    TOTAL_ARCHIVED=$((TOTAL_ARCHIVED + COUNT))
    echo "[$(date)] ${SCHEMA}: ${COUNT}件のaudit_logsをアーカイブ → ${ARCHIVE_FILE}"
  fi
done

# auth_events（publicスキーマ）も同様に処理
AUTH_COUNT=$(docker compose -f "${COMPOSE_FILE}" exec -T postgres \
  psql -U "${DB_USER}" -d "${DB_NAME}" -t -A -c \
  "SELECT COUNT(*) FROM public.auth_events WHERE created_at < NOW() - INTERVAL '${RETENTION_DAYS} days';" 2>/dev/null || echo "0")

if [ "${AUTH_COUNT}" -gt 0 ]; then
  AUTH_ARCHIVE="${ARCHIVE_DIR}/auth_events_${DATE}.csv.gz"

  docker compose -f "${COMPOSE_FILE}" exec -T postgres \
    psql -U "${DB_USER}" -d "${DB_NAME}" -c \
    "COPY (SELECT * FROM public.auth_events WHERE created_at < NOW() - INTERVAL '${RETENTION_DAYS} days' ORDER BY created_at) TO STDOUT WITH CSV HEADER;" \
    | gzip > "${AUTH_ARCHIVE}"

  chmod 600 "${AUTH_ARCHIVE}"

  docker compose -f "${COMPOSE_FILE}" exec -T postgres \
    psql -U "${DB_USER}" -d "${DB_NAME}" -c \
    "DELETE FROM public.auth_events WHERE created_at < NOW() - INTERVAL '${RETENTION_DAYS} days';"

  TOTAL_ARCHIVED=$((TOTAL_ARCHIVED + AUTH_COUNT))
  echo "[$(date)] auth_events: ${AUTH_COUNT}件をアーカイブ → ${AUTH_ARCHIVE}"
fi

# アーカイブファイルも1年で自動削除
find "${ARCHIVE_DIR}" -name '*.csv.gz' -mtime +365 -delete

# ログに記録
echo "[$(date)] Audit log archive completed: ${TOTAL_ARCHIVED}件をアーカイブ" \
  >> "${ARCHIVE_DIR}/archive.log"
