#!/usr/bin/env python3
"""
Phase 1-B-2 事前調査: 原本 customers_master.csv を会社名で GROUP BY し、
companies + contacts 分割後の件数を推定する。

実行方法（Mac 側ローカル）:
    python3 scripts/data_migration/analyze_company_names.py

出力:
    - 総顧客数
    - ユニーク会社名数
    - 重複会社（2 customer 以上が同じ会社）のリスト
    - 会社名が空（個人顧客候補）のリスト
    - 氏名のみ（company_name と billing_display_name が同じ等）の推定個人顧客

個人情報（メール・電話等）は出力しない。件数と会社名の正規化キーのみ表示。
"""
from __future__ import annotations

import csv
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

SHEETS_DIR = Path(__file__).resolve().parent.parent.parent / "sheets"
CSV_PATH = SHEETS_DIR / "customers_master.csv"

# 商号略称・接尾辞の正規化対象
COMPANY_SUFFIXES = [
    " ltd.", " ltd", " inc.", " inc", " llc",
    " co.,ltd.", " co., ltd.", " co ltd", " co,ltd",
    " corp.", " corp", " corporation",
    " limited", " pty ltd", " pty.ltd",
    "株式会社", "有限会社", "合同会社", "合資会社",
    "(株)", "（株）", "(有)", "（有）",
]

# よくある個人名パターン（苗字/名前だけ or カタカナ1語）
INDIVIDUAL_HINT_WORDS = ["氏", "様", "先生", "君"]


def normalize_company_name(name: str | None) -> str:
    """会社名の正規化キーを生成（名寄せ判定用）"""
    if not name:
        return ""
    # NFKC で全角半角統一
    s = unicodedata.normalize("NFKC", name).strip().lower()
    # 括弧書きの補足（支店名・住所）を除去: "Card Galaxy LTD(Essex)" → "Card Galaxy LTD"
    s = re.sub(r"[\(（][^)）]*[\)）]", "", s)
    # 商号略称を削除（空白または末尾）
    for suffix in COMPANY_SUFFIXES:
        pattern = re.escape(suffix.strip())
        s = re.sub(rf"\s*{pattern}\b", "", s)
    # 連続空白を単一空白に
    s = re.sub(r"\s+", " ", s)
    # 末尾の記号除去
    s = re.sub(r"[.,;:\-_]+$", "", s)
    return s.strip()


BUSINESS_KEYWORDS = [
    "card", "shop", "trade", "cards", "harvest", "seafood", "cocoa",
    "&", "ltd", "inc", "corp", "llc", "corporation", "limited", "pty",
    "company", "co.", "store", "mart", "group", "holdings",
    "株式会社", "有限会社", "合同会社", "(株)", "（株）", "(有)", "（有）",
]


def looks_like_individual(company: str, delivery_name: str, billing_name: str) -> bool:
    """
    会社名が個人名っぽいか判定:
      - 会社名が空 → 個人
      - 会社名 == 配送先名 で business keyword を含まない → 個人顧客の可能性高い
      - 会社名 == 支払い名義（B Name 記述なし）→ 同上
    """
    s = (company or "").strip()
    if not s:
        return True
    s_lower = s.lower()
    if any(kw in s_lower for kw in BUSINESS_KEYWORDS):
        return False
    # 会社名と個人名が同一なら個人顧客の可能性（B_Name=個人名で登録されている）
    if delivery_name and s == delivery_name.strip():
        return True
    if billing_name and s == billing_name.strip():
        return True
    # 短い語彙（2単語以内、各20字未満）で business keyword なし → 個人かも
    words = s.split()
    if len(words) <= 2 and all(len(w) < 20 for w in words):
        return True
    return False


def main() -> int:
    if not CSV_PATH.exists():
        print(f"❌ CSV not found: {CSV_PATH}", file=sys.stderr)
        return 1

    rows: list[dict[str, str]] = []
    with CSV_PATH.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            if not (r.get("顧客ID") or "").strip():
                continue
            if not re.match(r"^CT-\d+", (r.get("顧客ID") or "").strip()):
                continue
            rows.append(r)

    print(f"総顧客数: {len(rows)} 件")
    print()

    # 会社名で GROUP BY
    groups: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        # B Name 優先、なければ D Name、なければ 支払い名義
        company = (row.get("B Name") or row.get("D Name") or row.get("支払い名義") or "").strip()
        key = normalize_company_name(company)
        if not key:
            key = "(空欄)"
        groups[key].append(row["顧客ID"])

    # 降順ソート
    sorted_groups = sorted(groups.items(), key=lambda x: (-len(x[1]), x[0]))

    unique_companies = sum(1 for _, ids in sorted_groups if ids)
    duplicate_groups = [(k, ids) for k, ids in sorted_groups if len(ids) > 1]
    single_groups = [(k, ids) for k, ids in sorted_groups if len(ids) == 1]

    print(f"ユニーク会社名（正規化後）: {unique_companies}")
    print(f"重複会社グループ（2以上の顧客）: {len(duplicate_groups)}")
    print(f"単独会社（1顧客のみ）: {len(single_groups)}")
    print()

    if duplicate_groups:
        print("=== 重複会社候補（手動確認推奨）===")
        for key, cust_ids in duplicate_groups:
            display_key = key if key != "(空欄)" else "[会社名空欄]"
            print(f"  '{display_key}' × {len(cust_ids)}: {', '.join(cust_ids)}")
        print()

    # 個人顧客候補
    individual_candidates = []
    for row in rows:
        company = (row.get("B Name") or "").strip()
        delivery = (row.get("D Name") or "").strip()
        billing = (row.get("支払い名義") or "").strip()
        if looks_like_individual(company, delivery, billing):
            individual_candidates.append(row["顧客ID"])
    print(f"=== 個人顧客候補（is_individual=TRUE 推定）{len(individual_candidates)} 件 ===")
    print(f"  {', '.join(individual_candidates[:20])}{' ...' if len(individual_candidates) > 20 else ''}")
    print()

    # 会社名と配送先名が同一の顧客（個人っぽい）
    print("=== B Name == D Name（同一名、個人顧客の可能性）===")
    same_name_rows = []
    for row in rows:
        company = (row.get("B Name") or "").strip()
        delivery = (row.get("D Name") or "").strip()
        if company and delivery and company == delivery:
            same_name_rows.append((row["顧客ID"], company))
    print(f"  {len(same_name_rows)} 件")
    for cid, name in same_name_rows[:10]:
        print(f"    {cid}: {name}")
    if len(same_name_rows) > 10:
        print(f"    ... 他 {len(same_name_rows) - 10} 件")
    print()

    # 空欄顧客
    empty_company_ids = [row["顧客ID"] for row in rows if not (row.get("B Name") or "").strip()]
    if empty_company_ids:
        print(f"=== B Name 空欄 {len(empty_company_ids)} 件 ===")
        print(f"  {', '.join(empty_company_ids)}")
        print()

    # 推定件数まとめ
    print("=" * 50)
    print(f"推定 companies 件数: {unique_companies}")
    print(f"推定 contacts 件数: {len(rows)}（既存全customers）")
    print(f"推定 companies.is_individual=TRUE: {len(individual_candidates)}")
    print(f"手動レビューが必要な会社グループ: {len(duplicate_groups)}")
    print("=" * 50)
    return 0


if __name__ == "__main__":
    sys.exit(main())
