#!/usr/bin/env python3
"""
sheets/raw/API解析.csv の 7 行目 ♻️[Knowledge] (0-based row index 6) から、
仕入先ごとの Gemini 解析プロンプトを public.supplier_prompts に取り込む冪等 UPSERT SQL を生成する。
(QA 2026-05-31 / ADR-085)

CSV は転置構造（論理 9 行 × 46 列）:
  - row[0] = 仕入元（col1.. に仕入先名 45 件）
  - row[6] = ♻️[Knowledge]（col1.. に各仕入先のプロンプト本文。非空 33 件）

突合キーは仕入先名（public.suppliers.name）。CSV のヘッダは末尾空白・表記ゆれが
あるため、生成 SQL 側で TRIM(name) と strip 済み名を比較する。名前が一致しない仕入先は
INSERT 対象 0 行（=スキップ）になる。

使い方（標準出力に SQL。DB ドライバ不要）:
  python3 scripts/seed_supplier_prompts_from_sheet.py \
    | ssh ubuntu@<VPS> "docker exec -i astro-webapp-postgres-1 psql -U jarvis -d jarvis_db -v ON_ERROR_STOP=1"
"""
from __future__ import annotations

import csv
import os
import sys

_CSV = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "sheets",
    "raw",
    "API解析.csv",
)
_KNOWLEDGE_ROW = 6  # 0-based: 7 行目 ♻️[Knowledge]


def _q(value: str) -> str:
    """SQL 単一引用符リテラル（' をエスケープ。改行はそのまま許容）。"""
    return "'" + value.replace("'", "''") + "'"


def main() -> int:
    if not os.path.exists(_CSV):
        print(f"-- CSV not found: {_CSV}", file=sys.stderr)
        return 1
    rows = list(csv.reader(open(_CSV, encoding="utf-8")))
    if len(rows) <= _KNOWLEDGE_ROW:
        print("-- unexpected CSV shape", file=sys.stderr)
        return 1
    names = rows[0]
    prompts = rows[_KNOWLEDGE_ROW]

    out = ["BEGIN;"]
    n = 0
    for col in range(1, len(names)):
        name = (names[col] or "").strip()
        prompt = prompts[col] if col < len(prompts) else ""
        if not name or not prompt.strip():
            continue
        # 名前一致で supplier_id を解決して UPSERT（不一致は 0 行 = スキップ）
        out.append(
            "INSERT INTO public.supplier_prompts (supplier_id, prompt) "
            f"SELECT id, {_q(prompt)} FROM public.suppliers WHERE TRIM(name) = {_q(name)} "
            "ON CONFLICT (supplier_id) DO UPDATE SET "
            "prompt = EXCLUDED.prompt, updated_at = NOW();"
        )
        n += 1
    out.append("COMMIT;")
    out.append(f"-- supplier prompts emitted: {n}")
    print("\n".join(out))
    print(f"-- emitted {n} supplier prompt upserts", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
