#!/usr/bin/env python3
"""
sheets/raw/Pokemon_BB.csv → public.tcg_series_master の冪等 UPSERT SQL を生成する。

QA 2026-05-30 / ADR-083:
  - A 列 Mark           → series_code
  - Japanese Title      → name_ja
  - English Title       → name_en
  - 発売日 (Release Date) は不要 → release_date は NULL
  - tcg_type は 'pokemon_booster_box'（種別マスタ tcg_type_master の code に一致）

使い方（標準出力に SQL を出すだけ。DB ドライバ不要）:
  # ローカルで確認
  python3 scripts/seed_tcg_series_from_pokemon_bb.py

  # 本番 (VPS) へ適用
  python3 scripts/seed_tcg_series_from_pokemon_bb.py \
    | ssh ubuntu@<VPS> "docker exec -i astro-webapp-postgres-1 psql -U jarvis -d jarvis_db -v ON_ERROR_STOP=1"

冪等: ON CONFLICT (tcg_type, series_code) DO UPDATE。再実行で name のみ最新化。
"""
from __future__ import annotations

import csv
import os
import sys

TCG_TYPE = "pokemon_booster_box"
CSV_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "sheets",
    "raw",
    "Pokemon_BB.csv",
)


def _sql_str(value: str | None) -> str:
    """シングルクォートをエスケープした SQL 文字列リテラル。空は NULL。"""
    if value is None:
        return "NULL"
    v = value.strip()
    if not v:
        return "NULL"
    return "'" + v.replace("'", "''") + "'"


def main() -> int:
    if not os.path.exists(CSV_PATH):
        print(f"-- CSV not found: {CSV_PATH}", file=sys.stderr)
        return 1

    out: list[str] = []
    out.append("BEGIN;")
    count = 0
    with open(CSV_PATH, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            mark = (row.get("Mark") or "").strip()
            name_ja = (row.get("Japanese Title") or "").strip()
            name_en = (row.get("English Title") or "").strip()
            # Mark と日本語名が無い行（区切り・注記等）はスキップ
            if not mark or not name_ja:
                continue
            out.append(
                "INSERT INTO public.tcg_series_master "
                "(tcg_type, series_code, name_ja, name_en) VALUES "
                f"({_sql_str(TCG_TYPE)}, {_sql_str(mark)}, "
                f"{_sql_str(name_ja)}, {_sql_str(name_en)}) "
                "ON CONFLICT (tcg_type, series_code) DO UPDATE SET "
                "name_ja = EXCLUDED.name_ja, name_en = EXCLUDED.name_en, "
                "updated_at = NOW();"
            )
            count += 1
    out.append("COMMIT;")
    out.append(f"-- seeded rows: {count}")
    print("\n".join(out))
    print(f"-- seeded {count} Pokemon BB series rows", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
