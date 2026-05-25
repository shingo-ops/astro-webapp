#!/usr/bin/env bash
# =============================================================
# B-8: S3遠隔バックアップスクリプト
#
# 目的:
#   PostgreSQLバックアップをAWS S3に転送する。
#   VPS障害時の復旧手段として、3-2-1ルールに対応する。
#   （3コピー、2種類の媒体、1つはオフサイト）
#
# 使い方:
#   既存のbackup.shの後に実行する。
#
# cron登録（毎日 3:30 = backup.sh完了後）:
#   30 3 * * * /path/to/scripts/backup_to_s3.sh >> /var/log/s3_backup.log 2>&1
#
# 前提:
#   - AWS CLI v2 がインストール済み
#   - IAMユーザーに s3:PutObject, s3:GetObject, s3:ListBucket 権限
#   - 環境変数 or ~/.aws/credentials に認証情報を設定済み
# =============================================================

set -euo pipefail

# --- 設定 ---
S3_BUCKET="${S3_BACKUP_BUCKET:-salesanchor-backups}"
S3_PREFIX="postgres-backups"
LOCAL_BACKUP_DIR="/home/ubuntu/backups/postgres"
RETENTION_DAYS=90  # S3上の保持日数

echo "=== S3バックアップ転送開始: $(date) ==="

# 1. 最新のバックアップファイルを特定
LATEST_BACKUP=$(ls -t "$LOCAL_BACKUP_DIR"/*.gz 2>/dev/null | head -1)

if [ -z "$LATEST_BACKUP" ]; then
  echo "ERROR: バックアップファイルが見つかりません: ${LOCAL_BACKUP_DIR}"
  exit 1
fi

FILENAME=$(basename "$LATEST_BACKUP")
echo "  転送対象: ${FILENAME}"

# 2. S3に転送
echo "  S3にアップロード中..."
aws s3 cp "$LATEST_BACKUP" "s3://${S3_BUCKET}/${S3_PREFIX}/${FILENAME}" \
  --storage-class STANDARD_IA \
  --only-show-errors

# 3. アップロード検証
S3_SIZE=$(aws s3api head-object --bucket "$S3_BUCKET" --key "${S3_PREFIX}/${FILENAME}" --query ContentLength --output text 2>/dev/null)
LOCAL_SIZE=$(stat -c%s "$LATEST_BACKUP" 2>/dev/null || stat -f%z "$LATEST_BACKUP")

if [ "$S3_SIZE" = "$LOCAL_SIZE" ]; then
  echo "  OK: サイズ一致（${LOCAL_SIZE} bytes）"
else
  echo "  ERROR: サイズ不一致 local=${LOCAL_SIZE} s3=${S3_SIZE}"
  exit 1
fi

# 4. 古いS3オブジェクトの削除（90日以上前）
echo "  古いバックアップを削除中（${RETENTION_DAYS}日以上前）..."
CUTOFF_DATE=$(date -d "-${RETENTION_DAYS} days" +%Y-%m-%d 2>/dev/null || date -v-${RETENTION_DAYS}d +%Y-%m-%d)

aws s3api list-objects-v2 \
  --bucket "$S3_BUCKET" \
  --prefix "${S3_PREFIX}/" \
  --query "Contents[?LastModified<='${CUTOFF_DATE}'].Key" \
  --output text 2>/dev/null | while read -r KEY; do
    [ "$KEY" = "None" ] && continue
    [ -z "$KEY" ] && continue
    echo "    削除: ${KEY}"
    aws s3api delete-object --bucket "$S3_BUCKET" --key "$KEY"
done

echo "=== S3バックアップ転送完了: $(date) ==="
