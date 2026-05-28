#!/usr/bin/env bash
# =============================================================================
# codex-auth-check.sh — Codex 認証トークンの期限チェック
# =============================================================================
# 使い方:
#   bash scripts/codex-auth-check.sh          # チェックのみ（期限切れなら exit 1）
#   bash scripts/codex-auth-check.sh --warn-days 5  # 5日以内で警告（デフォルト: 3日）
#
# codex-generator.sh から自動的に呼ばれます。
# 手動確認にも使えます。
# =============================================================================

set -euo pipefail

AUTH_FILE="${HOME}/.codex/auth.json"
WARN_DAYS=3
CODEX_BIN="${HOME}/.npm-global/bin/codex"

if [[ "${1:-}" == "--warn-days" && -n "${2:-}" ]]; then
  if [[ ! "${2}" =~ ^[0-9]+$ ]]; then
    echo "❌ --warn-days には整数を指定してください（例: --warn-days 5）"
    exit 1
  fi
  WARN_DAYS="$2"
fi

# ────────────────────────────────────────────────────────────────────────────
# auth.json の存在確認
# ────────────────────────────────────────────────────────────────────────────
if [[ ! -f "$AUTH_FILE" ]]; then
  echo ""
  echo "❌ Codex にログインしていません。"
  echo "   以下のコマンドでログインしてください:"
  echo ""
  echo "   ! ${CODEX_BIN} login --device-auth"
  echo ""
  exit 1
fi

# ────────────────────────────────────────────────────────────────────────────
# access_token の期限を JWT デコードで確認
# ────────────────────────────────────────────────────────────────────────────
python3 - <<PYEOF
import json, base64, datetime, sys

auth_file = "${AUTH_FILE}"
warn_days = ${WARN_DAYS}
codex_bin = "${CODEX_BIN}"

try:
    with open(auth_file) as f:
        data = json.load(f)
except Exception as e:
    print(f"❌ auth.json の読み込みに失敗しました: {e}")
    sys.exit(1)

tokens = data.get("tokens", {})
access_token = tokens.get("access_token", "")

if not access_token:
    print("")
    print("❌ Codex にログインしていません。")
    print("   以下のコマンドでログインしてください:")
    print("")
    print(f"   ! {codex_bin} login --device-auth")
    print("")
    sys.exit(1)

# JWT の2番目のパート（ペイロード）をデコード
try:
    parts = access_token.split(".")
    payload = parts[1]
    payload += "=" * (4 - len(payload) % 4)
    claims = json.loads(base64.urlsafe_b64decode(payload))
    exp = claims.get("exp")
    if exp is None:
        raise ValueError("exp claim not found")
except Exception:
    print("⚠️  トークンのデコードに失敗しました。codex doctor で確認してください。")
    sys.exit(0)  # デコード失敗は致命的ではないので続行

now = datetime.datetime.now()
exp_dt = datetime.datetime.fromtimestamp(exp)
remaining = exp_dt - now
remaining_days = remaining.days

if remaining_days < 0:
    # access_token 期限切れ（refresh_token で自動更新されるはず）
    # → codex 実行時に自動リフレッシュを試みる。失敗なら再ログインが必要
    last_refresh = data.get("last_refresh", "不明")
    print("")
    print("⚠️  Codex の access_token が期限切れです。")
    print(f"   最終更新: {last_refresh}")
    print("   次回 codex 実行時に自動更新されます。")
    print("   自動更新に失敗した場合は以下を実行してください:")
    print("")
    print(f"   ! {codex_bin} login --device-auth")
    print("")
    # exit 0: 自動リフレッシュに任せる
elif remaining_days <= warn_days:
    print("")
    print(f"⚠️  Codex トークンが {remaining_days} 日後（{exp_dt.strftime('%Y-%m-%d')}）に切れます。")
    print("   今のうちにログインし直すと安心です:")
    print("")
    print(f"   ! {codex_bin} login --device-auth")
    print("")
    # exit 0: 警告のみ、処理は続行
else:
    print(f"✅ Codex 認証 OK（{exp_dt.strftime('%Y-%m-%d')} まで有効・残り {remaining_days} 日）")
PYEOF
