#!/usr/bin/env python3
"""
Phase 1-B-2 手動レビュー用 CSV エクスポート。

salesanchor/sheets/customers_master.csv の全 52件について、
自動名寄せ結果（正規化キー・重複グループ・個人顧客判定）を付与した
レビュー CSV を出力する。しんごさんが Excel で開いて修正欄に記入する。

出力:
    salesanchor/sheets/dedup_review_output.csv

実行方法:
    python3 scripts/data_migration/export_dedup_review.py

出力列:
    顧客ID, B_Name, D_Name, 支払い名義, 連絡ツール, 販売先, 登録日時,
    [正規化会社名], [重複グループ], [is_individual_auto],
    [override_company_code], [override_is_individual], [override_notes]

override_* 列はしんごさんが必要に応じて記入する空欄。
- override_company_code: この顧客を統合したい既存会社の company_code
- override_is_individual: TRUE/FALSE（auto判定を覆したい場合）
- override_notes: しんごさん自由記述（判断理由メモ等）
"""
from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path

# 同ディレクトリの analyze_company_names から関数を流用
sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze_company_names import normalize_company_name, looks_like_individual  # noqa: E402

SHEETS_DIR = Path(__file__).resolve().parent.parent.parent / "sheets"
INPUT_CSV = SHEETS_DIR / "customers_master.csv"
OUTPUT_CSV = SHEETS_DIR / "dedup_review_output.csv"


def main() -> int:
    if not INPUT_CSV.exists():
        print(f"❌ 入力 CSV not found: {INPUT_CSV}", file=sys.stderr)
        return 1

    rows = []
    with INPUT_CSV.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            if not (r.get("顧客ID") or "").strip():
                continue
            if not (r.get("顧客ID") or "").startswith("CT-"):
                continue
            rows.append(r)

    # 正規化キーで GROUP BY
    groups = defaultdict(list)
    for row in rows:
        company = (row.get("B Name") or row.get("D Name") or row.get("支払い名義") or "").strip()
        key = normalize_company_name(company) or "(空欄)"
        groups[key].append(row["顧客ID"])

    # group_id 割り当て（重複のあるグループのみ番号を付ける）
    group_ids: dict[str, str] = {}
    g_counter = 1
    for key, cust_ids in sorted(groups.items(), key=lambda x: (-len(x[1]), x[0])):
        if len(cust_ids) > 1:
            group_ids[key] = f"GROUP-{g_counter:02d}"
            g_counter += 1

    # 出力
    out_fieldnames = [
        "顧客ID",
        "B_Name（会社名）",
        "D_Name（配送先名）",
        "支払い名義",
        "連絡ツール",
        "販売先",
        "登録日時",
        "【自動】正規化会社名",
        "【自動】重複グループ",
        "【自動】is_individual",
        "【記入】統合先company_code",
        "【記入】is_individual上書き",
        "【記入】備考・判断理由",
    ]

    with OUTPUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=out_fieldnames, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        for row in rows:
            company = (row.get("B Name") or row.get("D Name") or row.get("支払い名義") or "").strip()
            normalized = normalize_company_name(company)
            key = normalized if normalized else "(空欄)"
            is_indiv = looks_like_individual(
                (row.get("B Name") or "").strip(),
                (row.get("D Name") or "").strip(),
                (row.get("支払い名義") or "").strip(),
            )
            writer.writerow({
                "顧客ID": row["顧客ID"],
                "B_Name（会社名）": (row.get("B Name") or "").strip(),
                "D_Name（配送先名）": (row.get("D Name") or "").strip(),
                "支払い名義": (row.get("支払い名義") or "").strip(),
                "連絡ツール": (row.get("連絡ツール") or "").strip(),
                "販売先": (row.get("販売先") or "").strip(),
                "登録日時": (row.get("登録日時") or "").strip(),
                "【自動】正規化会社名": normalized,
                "【自動】重複グループ": group_ids.get(key, ""),
                "【自動】is_individual": "TRUE" if is_indiv else "FALSE",
                "【記入】統合先company_code": "",
                "【記入】is_individual上書き": "",
                "【記入】備考・判断理由": "",
            })

    print(f"✓ レビュー用 CSV を出力: {OUTPUT_CSV}")
    print(f"  件数: {len(rows)}")
    print(f"  重複グループ: {len(group_ids)}")
    print()
    print("しんごさんへの記入依頼:")
    print("  1. 【自動】重複グループ 列を確認し、同じ会社なら OK、違うなら【記入】統合先company_code を空のまま")
    print("  2. 【自動】is_individual 列を確認し、FALSE 法人判定に変更したい場合は【記入】is_individual上書き に FALSE")
    print("  3. Ocean Harvest Seafood のような自動検出漏れは【記入】統合先company_code に target company code を記入")
    print("  4. 編集したら dedup_review_input.csv にリネームして保存、import_manual_review.py で取り込み")
    print()
    print("  注意: 本 CSV は個人情報を含むため、sheets/ フォルダから外に出さないこと")
    return 0


if __name__ == "__main__":
    sys.exit(main())
