#!/usr/bin/env python3
"""ADR-072 Phase 3: tenant schema 修飾 linter (PoC).

検出ルール:
  - Rule A: tenant スキーマ内テーブル名が `text("... FROM <bare-table> ...")` 形式で
    出現し、かつ同 endpoint で `tenant_table_ref(...)` も `reset_tenant_context(...)`
    も呼ばれていない → 案 A / 案 B どちらの対応もない違反。
  - Rule B: write 系 endpoint (`@router.post|put|patch|delete`) で
    `await db.commit()` を呼んでいるのに、関数内の `reset_tenant_context(...)` 呼び出し
    回数が commit 数に満たない → 案 B 違反 (Issue #563 と同根のバグ候補)。

PoC は `--mode warning` (default) で違反を stderr 出力するが exit 0 を返す。
Phase 4 で `--mode strict` に切り替えて required check 昇格する。

Usage:
  python3 scripts/lint_tenant_schema.py
  python3 scripts/lint_tenant_schema.py backend/app/routers/staff.py
  python3 scripts/lint_tenant_schema.py --mode strict backend/app/routers/

参照:
  - docs/adr/ADR-072-tenant-schema-prefix-enforcement.md §4 (CI linter)
  - Issue #773 (tracker)
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path
from typing import NamedTuple


# tenant スキーマ内のテーブル名 allowlist (ADR-072 §4 で「allowlist で管理」と決定)。
# 将来は migrations/ から自動抽出するが、PoC では固定リストで開始する。
TENANT_TABLES: frozenset[str] = frozenset(
    {
        "audit_logs",
        "bots",
        "companies",
        "contacts",
        "deals",
        "discord_inbound_messages",
        "google_calendar_config",
        "goals",
        "inventory_movements",
        "invoice_items",
        "invoices",
        "leads",
        "meta_messages",
        "order_commissions",
        "order_financials",
        "order_purchase_details",
        "order_shipping_details",
        "orders",
        "products",
        "purchase_order_items",
        "purchase_orders",
        "quote_items",
        "quotes",
        "role_permissions",
        "roles",
        "shifts",
        "staff",
        "staff_permissions",
        "staff_ui_preferences",
        "supplier_discord_routing",
        "suppliers",
        "tenant_commission_settings",
        "tenant_meta_config",
        "tenant_profile",
        "user_roles",
    }
)


TENANT_TABLE_REF = "tenant_table_ref"
RESET_TENANT_CONTEXT = "reset_tenant_context"
WRITE_METHODS = frozenset({"post", "put", "patch", "delete"})


# SQL 内の bare-table 抽出パターン (FROM / INTO / UPDATE / JOIN / DELETE FROM)。
# テーブル参照は `<identifier>` が単独で来た場合のみマッチ (`tenant_NNN.xxx` /
# `public.xxx` / f-string 内の `{var}` は処理側で除外)。
_BARE_TABLE_PATTERNS = [
    re.compile(r"\bFROM\s+([A-Za-z_][A-Za-z0-9_]*)\b", re.IGNORECASE),
    re.compile(r"\bINTO\s+([A-Za-z_][A-Za-z0-9_]*)\b", re.IGNORECASE),
    re.compile(r"\bUPDATE\s+([A-Za-z_][A-Za-z0-9_]*)\b", re.IGNORECASE),
    re.compile(r"\bJOIN\s+([A-Za-z_][A-Za-z0-9_]*)\b", re.IGNORECASE),
    re.compile(r"\bDELETE\s+FROM\s+([A-Za-z_][A-Za-z0-9_]*)\b", re.IGNORECASE),
]


class Violation(NamedTuple):
    file: str
    line: int
    function: str
    rule: str  # "A" / "B" / "SYNTAX"
    message: str


def _is_router_endpoint(node: ast.AsyncFunctionDef) -> tuple[bool, bool]:
    """関数の decorator から `(is_endpoint, is_write)` を判定する。

    `@router.get(...)` / `@router.post(...)` 等の decorator を持つ async 関数のみ
    endpoint と認識。write は POST/PUT/PATCH/DELETE。
    """
    for dec in node.decorator_list:
        if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
            if (
                isinstance(dec.func.value, ast.Name)
                and dec.func.value.id == "router"
            ):
                method = dec.func.attr.lower()
                if method in WRITE_METHODS or method == "get":
                    return True, method in WRITE_METHODS
    return False, False


def _has_tenant_id_dep(node: ast.AsyncFunctionDef) -> bool:
    """関数引数に `tenant_id: int = Depends(get_current_tenant)` があるか。

    super_admin_*.py 等の public スキーマ専用 endpoint は tenant_id 依存を
    持たないため、本判定で除外する (false positive 防止)。
    """
    for arg in node.args.args + node.args.kwonlyargs:
        if arg.arg == "tenant_id":
            return True
    return False


def _extract_text_strings(func: ast.AST) -> list[tuple[int, str]]:
    """関数内の `text("...")` 引数を集める。f-string は `{var}` を `<VAR>` に
    置換した文字列を返す (bare-table 誤検出を避けるため)。"""
    results: list[tuple[int, str]] = []
    for child in ast.walk(func):
        if not (isinstance(child, ast.Call) and isinstance(child.func, ast.Name)):
            continue
        if child.func.id != "text" or not child.args:
            continue
        arg = child.args[0]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            results.append((arg.lineno, arg.value))
        elif isinstance(arg, ast.JoinedStr):  # f-string
            parts: list[str] = []
            for s in arg.values:
                if isinstance(s, ast.Constant):
                    parts.append(s.value)
                else:
                    parts.append("<VAR>")
            results.append((arg.lineno, "".join(parts)))
    return results


def _find_bare_tenant_tables(sql: str) -> set[str]:
    """SQL 文字列内に出現する bare な tenant スキーマ内テーブル名を返す。

    `tenant_NNN.xxx` / `public.xxx` / `<VAR>` (f-string 変数) は patterns の
    `\\b<keyword>\\s+([id])` で先頭文字を縛っているため間接的に除外される。
    """
    found: set[str] = set()
    for pat in _BARE_TABLE_PATTERNS:
        for m in pat.finditer(sql):
            name = m.group(1)
            if name in TENANT_TABLES:
                # 直前が `.` ならスキーマ修飾済 (e.g. `tenant_006.bots`) なのでスキップ
                start = m.start(1)
                if start >= 1 and sql[start - 1] == ".":
                    continue
                found.add(name)
    return found


def _count_commit_and_reset(func: ast.AST) -> tuple[int, int]:
    """関数内の `await db.commit()` と `reset_tenant_context(...)` の呼び出し数。"""
    commits = 0
    resets = 0
    for child in ast.walk(func):
        if not isinstance(child, ast.Call):
            continue
        # await db.commit()
        if (
            isinstance(child.func, ast.Attribute)
            and child.func.attr == "commit"
            and isinstance(child.func.value, ast.Name)
            and child.func.value.id == "db"
        ):
            commits += 1
        # reset_tenant_context(...)
        elif (
            isinstance(child.func, ast.Name)
            and child.func.id == RESET_TENANT_CONTEXT
        ):
            resets += 1
    return commits, resets


def _has_tenant_table_ref_call(func: ast.AST) -> bool:
    for child in ast.walk(func):
        if (
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Name)
            and child.func.id == TENANT_TABLE_REF
        ):
            return True
    return False


def lint_file(path: Path) -> list[Violation]:
    """1 ファイルを ast.parse して違反を返す。"""
    src = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError as e:
        return [
            Violation(str(path), e.lineno or 0, "?", "SYNTAX", f"parse failed: {e}")
        ]

    violations: list[Violation] = []

    for func in ast.walk(tree):
        if not isinstance(func, ast.AsyncFunctionDef):
            continue
        is_endpoint, is_write = _is_router_endpoint(func)
        if not is_endpoint:
            continue
        # tenant_id 依存を持たない endpoint は public スキーマ専用 / super_admin
        # 系として除外する (ADR-072 §「リスク」/ Phase 3 PoC 設計)。
        if not _has_tenant_id_dep(func):
            continue

        fn_name = func.name
        texts = _extract_text_strings(func)
        has_helper = _has_tenant_table_ref_call(func)
        commits, resets = _count_commit_and_reset(func)

        # Rule A: bare-table 検出 (commit を含む endpoint のみ違反扱い)。
        # read endpoint は commit 前なので search_path は維持されており、bare-table
        # でも実害がないため除外 (ADR-072 §4 の意図に合わせる)。
        for lineno, sql in texts:
            bare = _find_bare_tenant_tables(sql)
            if bare and commits > 0 and not has_helper and resets == 0:
                violations.append(
                    Violation(
                        str(path),
                        lineno,
                        fn_name,
                        "A",
                        f"bare tenant table(s) {sorted(bare)} in text() and no "
                        f"tenant_table_ref/reset_tenant_context (commit={commits})",
                    )
                )

        # Rule B: write endpoint の commit/reset 対称性。
        # ただし `tenant_table_ref` を使っている = 案 A 採用済なので除外。
        if (
            is_write
            and commits > 0
            and resets < commits
            and not has_helper
        ):
            violations.append(
                Violation(
                    str(path),
                    func.lineno,
                    fn_name,
                    "B",
                    f"write endpoint has {commits} `await db.commit()` but only "
                    f"{resets} `reset_tenant_context()` call(s)",
                )
            )

    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="ADR-072 tenant schema linter (Phase 3 PoC)",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        default=["backend/app/routers"],
        help="ファイル or ディレクトリ (default: backend/app/routers)",
    )
    parser.add_argument(
        "--mode",
        choices=["warning", "strict"],
        default="warning",
        help="warning (default): exit 0 で stderr に違反出力 / "
        "strict: 違反があれば exit 1 (Phase 4 で required check 昇格時に使用)",
    )
    args = parser.parse_args(argv)

    targets: list[Path] = []
    for p_str in args.paths:
        path = Path(p_str)
        if path.is_file() and path.suffix == ".py":
            targets.append(path)
        elif path.is_dir():
            targets.extend(sorted(path.rglob("*.py")))
        else:
            sys.stderr.write(f"skip: {p_str} (not a .py file or dir)\n")

    all_violations: list[Violation] = []
    for t in targets:
        all_violations.extend(lint_file(t))

    if all_violations:
        for v in all_violations:
            sys.stderr.write(
                f"{v.file}:{v.line} [Rule {v.rule}] {v.function}: {v.message}\n"
            )
        sys.stderr.write(f"\n{len(all_violations)} violation(s) found.\n")
        if args.mode == "strict":
            sys.stderr.write(
                "mode=strict: failing CI (ADR-072 Phase 4 enforcement)\n"
            )
            return 1
        sys.stderr.write(
            "mode=warning: not failing CI yet (ADR-072 Phase 3 PoC)\n"
        )
        return 0

    sys.stderr.write(f"ADR-072 lint: OK ({len(targets)} file(s) scanned)\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
