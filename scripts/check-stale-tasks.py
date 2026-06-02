#!/usr/bin/env python3
"""
weekly-stale-tasks.yml から呼び出される陳腐化タスク検出スクリプト。
tasks/todo.md の「進行中」セクションを読み込み、
7日以上更新されていないタスクを標準出力に出力する。
"""
import sys
from datetime import datetime, timezone

TODO = "tasks/todo.md"
THRESHOLD_DAYS = 7

try:
    with open(TODO, encoding="utf-8") as f:
        lines = f.readlines()
except FileNotFoundError:
    print("SKIP: tasks/todo.md not found")
    sys.exit(0)

# 進行中セクションの行を抽出
in_section = False
rows = []
for line in lines:
    if line.startswith("## 進行中"):
        in_section = True
        continue
    if in_section and line.startswith("## "):
        break
    if in_section and line.startswith("|") and "---" not in line:
        rows.append(line.strip())

# ヘッダー行をスキップ
data_rows = [r for r in rows if not r.startswith("| タスク")]

today = datetime.now(timezone.utc)
stale = []

for row in data_rows:
    cols = [c.strip() for c in row.split("|") if c.strip()]
    if len(cols) < 6:
        continue
    task_name = cols[0]
    owner = cols[1]
    date_str = cols[5]  # 更新日（6列目）
    try:
        updated = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        diff = (today - updated).days
        if diff >= THRESHOLD_DAYS:
            stale.append(
                f"- **{task_name}** （担当: {owner}）— {diff}日更新なし（最終: {date_str}）"
            )
    except ValueError:
        continue

for s in stale:
    print(s)
