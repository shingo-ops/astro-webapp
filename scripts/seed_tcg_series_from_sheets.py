#!/usr/bin/env python3
"""
sheets/raw/<TCG>.csv 群 → public.tcg_series_master の冪等 UPSERT SQL を生成する。
(QA 2026-05-31 / ADR-083) Pokemon BB を含む全 TCG のシリーズを取り込む汎用版。

各 CSV 共通レイアウト: A列 Mark → series_code / Japanese Title → name_ja /
English Title → name_en（発売日は不要 = NULL）。tcg_type は下表のコードに対応。
データの無い CSV（シリーズ 0 件）は種別のみ migration 086 で登録され、本スクリプトは
何も出力しない。

使い方（標準出力に SQL。DB ドライバ不要）:
  python3 scripts/seed_tcg_series_from_sheets.py \
    | ssh ubuntu@<VPS> "docker exec -i astro-webapp-postgres-1 psql -U jarvis -d jarvis_db -v ON_ERROR_STOP=1"

冪等: ON CONFLICT (tcg_type, series_code) DO UPDATE。CSV は sheets/(gitignore) 配下。
"""
from __future__ import annotations

import csv
import os
import sys

# CSV ファイル名（拡張子なし） → tcg_type_master.code
GAMES: dict[str, str] = {
    "Pokemon_BB": "pokemon_booster_box",
    "One_Piece": "one_piece",
    "Dragon_Ball": "dragon_ball",
    "Yu-Gi-Oh!": "yugioh",
    "Union_Arena": "union_arena",
    "GUNDUM": "gundam",
    "Weiss_Shwarz": "weiss_schwarz",
    "Degimon": "digimon",
    "hololive": "hololive",
    "LORCANA": "lorcana",
    "Xross_Stars": "xross_stars",
}

_RAW_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sheets", "raw"
)


def _sql_str(value: str | None) -> str:
    if value is None:
        return "NULL"
    v = value.strip()
    if not v:
        return "NULL"
    return "'" + v.replace("'", "''") + "'"


def main() -> int:
    lines: list[str] = ["BEGIN;"]
    total = 0
    for fname, tcg_type in GAMES.items():
        path = os.path.join(_RAW_DIR, f"{fname}.csv")
        if not os.path.exists(path):
            print(f"-- skip (not found): {fname}.csv", file=sys.stderr)
            continue
        n = 0
        with open(path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                mark = (row.get("Mark") or "").strip()
                name_ja = (row.get("Japanese Title") or "").strip()
                name_en = (row.get("English Title") or "").strip()
                if not mark or not name_ja:
                    continue
                lines.append(
                    "INSERT INTO public.tcg_series_master "
                    "(tcg_type, series_code, name_ja, name_en) VALUES "
                    f"({_sql_str(tcg_type)}, {_sql_str(mark)}, "
                    f"{_sql_str(name_ja)}, {_sql_str(name_en)}) "
                    "ON CONFLICT (tcg_type, series_code) DO UPDATE SET "
                    "name_ja = EXCLUDED.name_ja, name_en = EXCLUDED.name_en, "
                    "updated_at = NOW();"
                )
                n += 1
        total += n
        print(f"-- {fname}: {n} rows (tcg_type={tcg_type})", file=sys.stderr)
    lines.append("COMMIT;")
    lines.append(f"-- total series rows: {total}")
    print("\n".join(lines))
    print(f"-- total {total} series rows across {len(GAMES)} games", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
