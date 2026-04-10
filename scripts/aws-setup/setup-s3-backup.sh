#!/usr/bin/env bash
# =============================================================
# AWS S3バックアップセットアップスクリプト
#
# 用途: Jarvis CRMのS3バックアップ環境をワンステップでセットアップ
#
# 前提:
#   1. AWSアカウントを作成済み
#   2. IAMユーザー「jarvis-backup」を作成し、このディレクトリの
#      iam-policy.json をアタッチ済み
#   3. アクセスキーを発行済み
#
# 実行場所: VPS側
# 使い方: bash scripts/aws-setup/setup-s3-backup.sh
# =============================================================

set -euo pipefail

BUCKET_NAME="jarvis-crm-backups"
REGION="ap-northeast-1"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "============================================"
echo "Jarvis CRM S3バックアップセットアップ"
echo "============================================"
echo ""

# ステップ1: AWS CLIインストール確認
echo "[1/6] AWS CLIインストール確認..."
if ! command -v aws &> /dev/null; then
    echo "  ✗ AWS CLIが未インストール"
    echo "  以下のコマンドでインストールしてください:"
    echo "    sudo apt update && sudo apt install -y awscli"
    exit 1
fi
echo "  ✓ AWS CLI: $(aws --version)"
echo ""

# ステップ2: AWS認証情報確認
echo "[2/6] AWS認証情報確認..."
if ! aws sts get-caller-identity &> /dev/null; then
    echo "  ✗ AWS認証情報が未設定"
    echo "  以下のコマンドで設定してください:"
    echo "    aws configure"
    echo ""
    echo "  入力項目:"
    echo "    AWS Access Key ID: （IAMユーザーのアクセスキー）"
    echo "    AWS Secret Access Key: （シークレット）"
    echo "    Default region name: ${REGION}"
    echo "    Default output format: json"
    exit 1
fi
IDENTITY=$(aws sts get-caller-identity --output text --query Arn)
echo "  ✓ 認証情報: ${IDENTITY}"
echo ""

# ステップ3: S3バケット作成
echo "[3/6] S3バケット作成..."
if aws s3api head-bucket --bucket "$BUCKET_NAME" 2>/dev/null; then
    echo "  ✓ バケット既存: ${BUCKET_NAME}"
else
    aws s3api create-bucket \
        --bucket "$BUCKET_NAME" \
        --region "$REGION" \
        --create-bucket-configuration LocationConstraint="$REGION"
    echo "  ✓ バケット作成完了: ${BUCKET_NAME}"
fi
echo ""

# ステップ4: バケット設定（暗号化・パブリックアクセスブロック）
echo "[4/6] バケットセキュリティ設定..."

# サーバーサイド暗号化（AES-256）
aws s3api put-bucket-encryption \
    --bucket "$BUCKET_NAME" \
    --server-side-encryption-configuration '{
        "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]
    }'
echo "  ✓ サーバーサイド暗号化を有効化（AES-256）"

# パブリックアクセスを完全ブロック
aws s3api put-public-access-block \
    --bucket "$BUCKET_NAME" \
    --public-access-block-configuration \
        "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"
echo "  ✓ パブリックアクセスを完全ブロック"

# バージョニング有効化（誤削除対策）
aws s3api put-bucket-versioning \
    --bucket "$BUCKET_NAME" \
    --versioning-configuration Status=Enabled
echo "  ✓ バージョニング有効化（誤削除対策）"

# HTTPS強制ポリシー
aws s3api put-bucket-policy \
    --bucket "$BUCKET_NAME" \
    --policy "file://${SCRIPT_DIR}/s3-bucket-policy.json"
echo "  ✓ HTTPS強制ポリシー適用"
echo ""

# ステップ5: ライフサイクル設定（90日後自動削除）
echo "[5/6] ライフサイクル設定..."
aws s3api put-bucket-lifecycle-configuration \
    --bucket "$BUCKET_NAME" \
    --lifecycle-configuration "file://${SCRIPT_DIR}/s3-lifecycle.json"
echo "  ✓ 90日後自動削除を設定"
echo ""

# ステップ6: 動作確認
echo "[6/6] 動作確認..."
TEST_FILE="/tmp/jarvis-s3-test-$(date +%s).txt"
echo "test" > "$TEST_FILE"
aws s3 cp "$TEST_FILE" "s3://${BUCKET_NAME}/test/" --quiet
aws s3 rm "s3://${BUCKET_NAME}/test/$(basename "$TEST_FILE")" --quiet
rm "$TEST_FILE"
echo "  ✓ アップロード/削除テスト成功"
echo ""

echo "============================================"
echo "セットアップ完了"
echo "============================================"
echo ""
echo "次のステップ:"
echo "  1. 手動でバックアップ転送をテスト:"
echo "     bash /home/ubuntu/astro-webapp/scripts/backup_to_s3.sh"
echo ""
echo "  2. cronに登録（毎日3:30実行）:"
echo "     crontab -e"
echo "     30 3 * * * /home/ubuntu/astro-webapp/scripts/backup_to_s3.sh >> /var/log/s3_backup.log 2>&1"
echo ""
echo "  3. S3コンソールで確認:"
echo "     https://s3.console.aws.amazon.com/s3/buckets/${BUCKET_NAME}"
