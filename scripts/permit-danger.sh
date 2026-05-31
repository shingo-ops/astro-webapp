#!/bin/bash
# 危険操作ワンタイム許可チケット発行スクリプト
# Usage: bash scripts/permit-danger.sh "<operation>"
# 例:    bash scripts/permit-danger.sh "gh pr merge"
#
# ~/.claude/permits/danger-permit-*.json を生成（30分有効・1回消費）

if [ -z "${1:-}" ]; then
  echo "Usage: bash scripts/permit-danger.sh \"<operation>\"" >&2
  echo "例:    bash scripts/permit-danger.sh \"gh pr merge\"" >&2
  exit 1
fi

OP="$1"
PERMITS_DIR="$HOME/.claude/permits"
mkdir -p "$PERMITS_DIR"

SAFE_OP=$(echo "$OP" | tr ' /' '__' | tr -cd '[:alnum:]_-')
TICKET_FILE="$PERMITS_DIR/danger-permit-${SAFE_OP}-$(date -u +%Y%m%dT%H%M%S).json"

python3 - "$OP" "$TICKET_FILE" <<'PYEOF'
import sys, json
from datetime import datetime, timezone, timedelta

op = sys.argv[1]
out = sys.argv[2]

now = datetime.now(timezone.utc)
expires = now + timedelta(minutes=30)

data = {
    "op": op,
    "created_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    "expires_at": expires.strftime("%Y-%m-%dT%H:%M:%SZ"),
    "created_by": "manual"
}

with open(out, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print(f"✅ 許可チケット発行: {op}")
print(f"   有効期限: {data['expires_at']} (30分)")
print(f"   ファイル: {out}")
PYEOF
