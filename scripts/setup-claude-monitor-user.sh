#!/usr/bin/env bash
# setup-claude-monitor-user.sh: Claude Code 専用 VPS 読み取り専用ユーザーのセットアップ
#
# 使用方法（VPS 上で実行）:
#   bash setup-claude-monitor-user.sh <公開鍵文字列>
#
# 例:
#   bash setup-claude-monitor-user.sh "ssh-ed25519 AAAAC3Nza... claude-code-reader"
#
# 事前準備（ローカル Mac で実行）:
#   ssh-keygen -t ed25519 -f ~/.ssh/salesanchor-claude -N "" -C "claude-code-reader"
#   cat ~/.ssh/salesanchor-claude.pub  # この出力を引数として渡す
#
# 関連 ADR: ADR-079
# 関連 runbook: docs/runbooks/claude-monitor-access.md

set -euo pipefail

# ---- 設定 ----------------------------------------------------------------
MONITOR_USER="claude-monitor"
ALLOWED_COMMANDS='docker stats --no-stream; free -h; df -h; uptime'
# --------------------------------------------------------------------------

PUBLIC_KEY="${1:?ERROR: 公開鍵を第1引数で指定してください。
  例: bash setup-claude-monitor-user.sh \"ssh-ed25519 AAAA... claude-code-reader\"
  公開鍵の取得: cat ~/.ssh/salesanchor-claude.pub}"

echo "=== Claude Code 専用監視ユーザー セットアップ ==="
echo "ユーザー名: ${MONITOR_USER}"
echo ""

# ---- Step 1: ユーザー作成（冪等性: 既存なら skip）----------------------
if id "${MONITOR_USER}" &>/dev/null; then
  echo "[1/4] ユーザー '${MONITOR_USER}' は既に存在します。スキップします。"
else
  echo "[1/4] ユーザー '${MONITOR_USER}' を作成中..."
  sudo useradd \
    --system \
    --shell /bin/bash \
    --no-create-home \
    --comment "Claude Code read-only monitor (ADR-079)" \
    "${MONITOR_USER}"
  echo "      ユーザー作成完了"
fi

# ---- Step 2: SSH ディレクトリ・authorized_keys 設定 ---------------------
echo "[2/4] SSH 設定を構成中..."
sudo mkdir -p "/home/${MONITOR_USER}/.ssh"
sudo chmod 700 "/home/${MONITOR_USER}/.ssh"

# ForceCommand で実行可能コマンドを制限
# no-pty: 対話的シェルを禁止
# no-port-forwarding / no-X11-forwarding / no-agent-forwarding: トンネリング禁止
AUTHORIZED_KEY_ENTRY="command=\"${ALLOWED_COMMANDS}\",no-port-forwarding,no-X11-forwarding,no-agent-forwarding,no-pty ${PUBLIC_KEY}"

AUTHORIZED_KEYS_FILE="/home/${MONITOR_USER}/.ssh/authorized_keys"

# 同じ鍵が既に登録されている場合は追加しない（冪等性）
if sudo test -f "${AUTHORIZED_KEYS_FILE}" && sudo grep -qF "${PUBLIC_KEY}" "${AUTHORIZED_KEYS_FILE}"; then
  echo "      公開鍵は既に登録されています。スキップします。"
else
  echo "${AUTHORIZED_KEY_ENTRY}" | sudo tee -a "${AUTHORIZED_KEYS_FILE}" > /dev/null
  echo "      公開鍵を登録しました（ForceCommand 付き）"
fi

sudo chmod 600 "${AUTHORIZED_KEYS_FILE}"
sudo chown -R "${MONITOR_USER}:${MONITOR_USER}" "/home/${MONITOR_USER}/.ssh"

# ---- Step 3: docker コマンド実行権限（docker グループへの追加）----------
echo "[3/4] docker グループへの追加中..."
if groups "${MONITOR_USER}" | grep -q docker; then
  echo "      既に docker グループのメンバーです。スキップします。"
else
  sudo usermod -aG docker "${MONITOR_USER}"
  echo "      docker グループに追加しました"
fi

# ---- Step 4: 動作確認 ---------------------------------------------------
echo "[4/4] 設定確認..."
echo ""
echo "=== セットアップ完了 ==="
echo ""
echo "登録された authorized_keys エントリ:"
sudo cat "${AUTHORIZED_KEYS_FILE}"
echo ""
echo "ユーザー情報:"
id "${MONITOR_USER}"
echo ""
echo "【ローカル Mac での接続テスト】"
echo "  ssh -i ~/.ssh/salesanchor-claude ${MONITOR_USER}@49.212.137.46"
echo ""
echo "【破壊的コマンドの拒否確認】"
echo "  ssh -i ~/.ssh/salesanchor-claude ${MONITOR_USER}@49.212.137.46 'rm /etc/passwd'"
echo "  → 'Permission denied' または ForceCommand により拒否されることを確認"
