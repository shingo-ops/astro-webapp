#!/usr/bin/env bash
# scripts/check-task-state.sh
#
# tasks/todo.md と docs/runbooks/monitoring-vps-migration.md の構造チェック。
# CI (task-state-check.yml) と手元確認の両方で使用する。
#
# Exit code:
#   0 = pass
#   1 = structure error (see output)

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TODO="$REPO_ROOT/tasks/todo.md"
MONITORING_RUNBOOK="$REPO_ROOT/docs/runbooks/monitoring-vps-migration.md"
ERRORS=0

echo "=== check-task-state.sh ==="

# ------------------------------------------------------------------
# 1. tasks/todo.md
# ------------------------------------------------------------------
echo ""
echo "--- tasks/todo.md ---"

if [[ ! -f "$TODO" ]]; then
  echo "ERROR: tasks/todo.md not found"
  ERRORS=$((ERRORS + 1))
else
  # Required column headers
  for col in "現在地" "次の一手" "根拠" "更新日" "担当"; do
    if grep -qF "$col" "$TODO"; then
      echo "OK: column '$col' header found"
    else
      echo "ERROR: missing column '$col' in tasks/todo.md"
      ERRORS=$((ERRORS + 1))
    fi
  done

  # Detect forbidden placeholder values in active-task section
  # Extract lines between "## 進行中" and next "## " section
  ACTIVE_SECTION=$(python3 - <<'PYEOF'
import sys
with open("tasks/todo.md", encoding="utf-8") as f:
    lines = f.readlines()
in_section = False
for line in lines:
    if line.startswith("## 進行中"):
        in_section = True
        continue
    if in_section and line.startswith("## "):
        break
    if in_section and line.startswith("|"):
        sys.stdout.write(line)
PYEOF
)

  if [[ -n "$ACTIVE_SECTION" ]]; then
    # Check for ??? or TBD
    if echo "$ACTIVE_SECTION" | grep -qE '\?\?\?|TBD'; then
      echo "ERROR: active tasks contain ??? or TBD placeholders"
      echo "$ACTIVE_SECTION" | grep -E '\?\?\?|TBD'
      ERRORS=$((ERRORS + 1))
    else
      echo "OK: no forbidden placeholders in active tasks"
    fi

    # Count data rows (exclude header and divider lines)
    DATA_ROWS=$(echo "$ACTIVE_SECTION" | grep -cvE '^\|[-|]+\|$' || true)
    # Subtract 1 for the header row
    DATA_ROWS=$((DATA_ROWS - 1))
    if [[ $DATA_ROWS -gt 0 ]]; then
      echo "OK: $DATA_ROWS active task row(s) found"
    else
      echo "OK: active tasks section exists but no data rows"
    fi
  else
    echo "OK: no active tasks (skipping row check)"
  fi
fi

# ------------------------------------------------------------------
# 2. monitoring-vps-migration.md
# ------------------------------------------------------------------
echo ""
echo "--- docs/runbooks/monitoring-vps-migration.md ---"

if [[ ! -f "$MONITORING_RUNBOOK" ]]; then
  echo "ERROR: monitoring-vps-migration.md not found"
  ERRORS=$((ERRORS + 1))
else
  if grep -qF "スプリント状態" "$MONITORING_RUNBOOK"; then
    echo "OK: sprint state section found"
  else
    echo "ERROR: sprint state section missing in monitoring-vps-migration.md"
    ERRORS=$((ERRORS + 1))
  fi

  for sprint in M1 M2 M3 M4 M5 M6 M7 M8; do
    if grep -qF "| $sprint " "$MONITORING_RUNBOOK"; then
      echo "OK: sprint $sprint row found"
    else
      echo "ERROR: sprint $sprint row missing in monitoring-vps-migration.md"
      ERRORS=$((ERRORS + 1))
    fi
  done
fi

# ------------------------------------------------------------------
echo ""
if [[ $ERRORS -eq 0 ]]; then
  echo "=== OK: all checks passed ==="
  exit 0
else
  echo "=== FAIL: $ERRORS error(s) ==="
  exit 1
fi
