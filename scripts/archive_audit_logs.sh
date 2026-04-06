#!/usr/bin/env bash
# =============================================================
# audit_logs / auth_events 90日アーカイブスクリプト
#
# 目的:
#   監査ログとauth_eventsの肥大化を防ぐ。
#   90日より古いレコードをCSVにエクスポートしてからDBから削除する。
#
# 使い方:
#   crontab -e で以下を追加（毎月1日 4:00に実行）:
#   0 4 1 * * /path/to/scripts/archive_audit_logs.sh >> /var/log/audit_archive.log 2>&1
#
# 前提:
#   - PostgreSQLコンテナ名: astro-webapp-postgres-1
#   - DB名: myapp_db / ユーザー: myapp_user
# =============================================================

set -euo pipefail

CONTAINER="astro-webapp-postgres-1"
DB_NAME="myapp_db"
DB_USER="myapp_user"
ARCHIVE_DIR="/home/ubuntu/backups/audit_archive"
RETENTION_DAYS=90
DATE_TAG=$(date +%Y%m%d)

mkdir -p "$ARCHIVE_DIR"

echo "=== audit_logs アーカイブ開始: $(date) ==="

# --- 1. public.auth_events のアーカイブ ---
echo "  auth_events: 90日以上前のレコードをエクスポート..."
docker exec "$CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -c \
  "\\COPY (SELECT * FROM public.auth_events WHERE created_at < NOW() - INTERVAL '${RETENTION_DAYS} days') TO STDOUT WITH CSV HEADER" \
  > "$ARCHIVE_DIR/auth_events_${DATE_TAG}.csv" 2>/dev/null

AUTH_COUNT=$(wc -l < "$ARCHIVE_DIR/auth_events_${DATE_TAG}.csv")
AUTH_COUNT=$((AUTH_COUNT - 1))  # ヘッダー行を除く
if [ "$AUTH_COUNT" -gt 0 ]; then
  echo "  auth_events: ${AUTH_COUNT}件をエクスポート → 削除..."
  docker exec "$CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -c \
    "DELETE FROM public.auth_events WHERE created_at < NOW() - INTERVAL '${RETENTION_DAYS} days';"
else
  echo "  auth_events: アーカイブ対象なし"
  rm -f "$ARCHIVE_DIR/auth_events_${DATE_TAG}.csv"
fi

# --- 2. 各テナントスキーマの audit_logs アーカイブ ---
SCHEMAS=$(docker exec "$CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -t -c \
  "SELECT schema_name FROM information_schema.schemata WHERE schema_name LIKE 'tenant_%' ORDER BY schema_name;")

for SCHEMA in $SCHEMAS; do
  SCHEMA=$(echo "$SCHEMA" | xargs)  # trim
  [ -z "$SCHEMA" ] && continue

  echo "  ${SCHEMA}.audit_logs: エクスポート..."
  docker exec "$CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -c \
    "\\COPY (SELECT * FROM ${SCHEMA}.audit_logs WHERE created_at < NOW() - INTERVAL '${RETENTION_DAYS} days') TO STDOUT WITH CSV HEADER" \
    > "$ARCHIVE_DIR/${SCHEMA}_audit_logs_${DATE_TAG}.csv" 2>/dev/null

  TENANT_COUNT=$(wc -l < "$ARCHIVE_DIR/${SCHEMA}_audit_logs_${DATE_TAG}.csv")
  TENANT_COUNT=$((TENANT_COUNT - 1))
  if [ "$TENANT_COUNT" -gt 0 ]; then
    echo "  ${SCHEMA}.audit_logs: ${TENANT_COUNT}件をエクスポート → 削除..."
    docker exec "$CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -c \
      "DELETE FROM ${SCHEMA}.audit_logs WHERE created_at < NOW() - INTERVAL '${RETENTION_DAYS} days';"
  else
    echo "  ${SCHEMA}.audit_logs: アーカイブ対象なし"
    rm -f "$ARCHIVE_DIR/${SCHEMA}_audit_logs_${DATE_TAG}.csv"
  fi
done

# --- 3. アーカイブCSVの圧縮 ---
if ls "$ARCHIVE_DIR"/*_${DATE_TAG}.csv 1>/dev/null 2>&1; then
  echo "  CSVファイルを圧縮..."
  gzip "$ARCHIVE_DIR"/*_${DATE_TAG}.csv
fi

# --- 4. 1年以上前のアーカイブファイルを削除 ---
find "$ARCHIVE_DIR" -name "*.csv.gz" -mtime +365 -delete

echo "=== audit_logs アーカイブ完了: $(date) ==="
