#!/usr/bin/env bash
# setup-vps-runner.sh: GitHub Actions self-hosted runner 登録スクリプト
#
# 使用方法:
#   RUNNER_TOKEN=<token> bash scripts/setup-vps-runner.sh
#
# トークン取得（ローカルの gh CLI で）:
#   gh api --method POST /repos/shingo-ops/salesanchor/actions/runners/registration-token --jq '.token'
#
# セキュリティ注意: トークンは必ず環境変数で渡すこと。
# CLI 引数（--token <value>）は ps aux で他のプロセスから見えるため禁止。
#
# 関連 ADR: ADR-078 / ADR-029
# 関連 runbook: docs/runbooks/vps-runner-setup.md

set -euo pipefail

# ---- 設定 ----------------------------------------------------------------
RUNNER_DIR="${HOME}/actions-runner"
RUNNER_NAME="salesanchor-vps"
RUNNER_LABELS="self-hosted,Linux,X64,salesanchor-vps"
REPO_URL="https://github.com/shingo-ops/salesanchor"
# --------------------------------------------------------------------------

# 必須環境変数チェック
: "${RUNNER_TOKEN:?ERROR: RUNNER_TOKEN env var must be set.
  取得コマンド: gh api --method POST /repos/shingo-ops/salesanchor/actions/runners/registration-token --jq '.token'
  有効期限: 1時間}"

echo "=== GitHub Actions Runner セットアップ ==="
echo "対象リポジトリ : ${REPO_URL}"
echo "ランナー名     : ${RUNNER_NAME}"
echo "ラベル         : ${RUNNER_LABELS}"
echo ""

# ---- Step 1: ディレクトリ・バイナリ準備 ----------------------------------
mkdir -p "${RUNNER_DIR}"
cd "${RUNNER_DIR}"

if [ ! -f "${RUNNER_DIR}/config.sh" ]; then
  echo "[1/4] runner バイナリをダウンロード中..."
  RUNNER_VERSION=$(curl -fsSL https://api.github.com/repos/actions/runner/releases/latest \
    | python3 -c "import sys,json; print(json.load(sys.stdin)['tag_name'].lstrip('v'))")
  echo "      バージョン: ${RUNNER_VERSION}"

  curl -fsSLo "actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz" \
    "https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz"

  tar xzf "./actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz"
  echo "      ダウンロード・展開 完了"
else
  echo "[1/4] runner バイナリは既に存在します。スキップします。"
fi

# ---- Step 2: 既存登録チェック → 冪等性（--replace）--------------------
REPLACE_FLAG=""
if [ -f "${RUNNER_DIR}/.runner" ]; then
  echo "[2/4] 既存の runner 設定を検出。--replace フラグを使用します。"
  REPLACE_FLAG="--replace"
else
  echo "[2/4] 既存設定なし。新規登録します。"
fi

# ---- Step 3: runner 設定 -------------------------------------------------
echo "[3/4] runner を設定中..."
# shellcheck disable=SC2086
"${RUNNER_DIR}/config.sh" \
  --url "${REPO_URL}" \
  --token "${RUNNER_TOKEN}" \
  --name "${RUNNER_NAME}" \
  --labels "${RUNNER_LABELS}" \
  --work _work \
  --unattended \
  ${REPLACE_FLAG}

# トークンをメモリから消去
unset RUNNER_TOKEN
echo "      トークンを unset しました"

# ---- Step 4: systemd サービス化 -----------------------------------------
echo "[4/4] systemd サービスをインストール・起動中..."
sudo "${RUNNER_DIR}/svc.sh" install
sudo "${RUNNER_DIR}/svc.sh" start

echo ""
echo "=== セットアップ完了 ==="
sudo "${RUNNER_DIR}/svc.sh" status
echo ""
echo "GitHub で確認:"
echo "  https://github.com/shingo-ops/salesanchor/settings/actions/runners"
echo ""
echo "CLI で確認:"
echo "  gh api /repos/shingo-ops/salesanchor/actions/runners --jq '.runners[] | {name:.name, status:.status}'"
