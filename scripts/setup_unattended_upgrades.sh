#!/usr/bin/env bash
# =============================================================
# B-5: unattended-upgrades セットアップスクリプト
#
# 目的:
#   OSのセキュリティパッチを自動適用する。
#   CVE公開後54%が1週間以内に悪用されるため、手動では間に合わない。
#
# 使い方（VPS上でroot権限で実行）:
#   sudo bash scripts/setup_unattended_upgrades.sh
#
# 対象OS: Ubuntu 24.04 LTS
# =============================================================

set -euo pipefail

echo "=== unattended-upgrades セットアップ開始 ==="

# 1. パッケージインストール
apt-get update
apt-get install -y unattended-upgrades apt-listchanges

# 2. 自動更新の有効化
cat > /etc/apt/apt.conf.d/20auto-upgrades << 'APTCONF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::Download-Upgradeable-Packages "1";
APT::Periodic::AutocleanInterval "7";
APTCONF

# 3. unattended-upgrades の設定
cat > /etc/apt/apt.conf.d/50unattended-upgrades << 'APTCONF'
Unattended-Upgrade::Allowed-Origins {
    "${distro_id}:${distro_codename}";
    "${distro_id}:${distro_codename}-security";
    "${distro_id}ESMApps:${distro_codename}-apps-security";
    "${distro_id}ESM:${distro_codename}-infra-security";
};

// セキュリティ更新のみ（機能更新は含めない）
Unattended-Upgrade::Package-Blacklist {
};

// 自動再起動の設定（深夜4:00に再起動が必要な場合のみ）
Unattended-Upgrade::Automatic-Reboot "true";
Unattended-Upgrade::Automatic-Reboot-Time "04:00";

// 未使用の依存パッケージを自動削除
Unattended-Upgrade::Remove-Unused-Dependencies "true";
Unattended-Upgrade::Remove-New-Unused-Dependencies "true";

// メール通知（設定する場合）
// Unattended-Upgrade::Mail "admin@example.com";
// Unattended-Upgrade::MailReport "on-change";
APTCONF

# 4. 設定の検証
echo ""
echo "=== 設定の検証 ==="
unattended-upgrades --dry-run --debug 2>&1 | tail -5

# 5. サービスの有効化
systemctl enable unattended-upgrades
systemctl restart unattended-upgrades

echo ""
echo "=== セットアップ完了 ==="
echo "  - セキュリティパッチが毎日自動適用されます"
echo "  - 再起動が必要な場合は毎日4:00に自動再起動します"
echo "  - ログ確認: cat /var/log/unattended-upgrades/unattended-upgrades.log"
