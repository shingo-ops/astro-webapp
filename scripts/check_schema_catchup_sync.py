"""Validate that schema catch-up migration lists stay in sync.

The repo currently maintains identical catch-up migration filenames in:
- scripts/setup_tenant.py
- scripts/db/sync_tenant_schema.py

If those lists drift, schema-check can stop reflecting the real catch-up path.
This check fails fast in CI and prints the exact mismatch.
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class MigrationList:
    name: str
    filenames: tuple[str, ...]


def _extract_migration_lists(source_path: Path) -> dict[str, MigrationList]:
    source = source_path.read_text(encoding="utf-8")
    module = ast.parse(source, filename=str(source_path))

    found: dict[str, MigrationList] = {}
    for node in ast.walk(module):
        if isinstance(node, ast.Assign):
            targets = [
                target.id
                for target in node.targets
                if isinstance(target, ast.Name) and target.id in {"public_migrations", "tenant_migrations"}
            ]
            value = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target.id] if node.target.id in {"public_migrations", "tenant_migrations"} else []
            value = node.value
        else:
            continue

        if not targets:
            continue
        if not isinstance(value, (ast.List, ast.Tuple)):
            raise ValueError(
                f"{source_path}: {targets[0]} は list/tuple literal で定義してください"
            )
        filenames = tuple(
            _extract_first_string(item, source_path, targets[0]) for item in value.elts
        )
        found[targets[0]] = MigrationList(targets[0], filenames)

    missing = {"public_migrations", "tenant_migrations"} - set(found)
    if missing:
        raise ValueError(f"{source_path}: {', '.join(sorted(missing))} が見つかりません")
    return found


def _extract_first_string(node: ast.AST, source_path: Path, list_name: str) -> str:
    if not isinstance(node, ast.Tuple) or not node.elts:
        raise ValueError(f"{source_path}: {list_name} の各要素は (filename, description) の tuple にしてください")
    first = node.elts[0]
    if not isinstance(first, ast.Constant) or not isinstance(first.value, str):
        raise ValueError(f"{source_path}: {list_name} の filename は文字列リテラルにしてください")
    return first.value


def _compare_lists(label: str, left: MigrationList, right: MigrationList) -> list[str]:
    errors: list[str] = []
    if left.filenames != right.filenames:
        left_set = set(left.filenames)
        right_set = set(right.filenames)
        missing = sorted(right_set - left_set)
        extra = sorted(left_set - right_set)
        if missing:
            errors.append(f"{label}: setup_tenant.py に存在しない migration: {missing}")
        if extra:
            errors.append(f"{label}: sync_tenant_schema.py に存在しない migration: {extra}")
        if not missing and not extra:
            errors.append(f"{label}: migration 順序が一致していません")
    return errors


def check_schema_catchup_sync(repo_root: Path | None = None) -> None:
    root = repo_root or Path(__file__).resolve().parents[1]
    setup_path = root / "scripts" / "setup_tenant.py"
    sync_path = root / "scripts" / "db" / "sync_tenant_schema.py"
    migrations_dir = root / "migrations"

    setup_lists = _extract_migration_lists(setup_path)
    sync_lists = _extract_migration_lists(sync_path)

    # setup_tenant.py には新規テナント専用の初期化 migration が含まれる。
    # ここでは sync_tenant_schema.py と共有すべき catch-up migration だけを比較する。
    setup_public = tuple(
        filename for filename in setup_lists["public_migrations"].filenames if filename != "014_create_current_tenant_id_function.sql"
    )
    setup_tenant = tuple(
        filename for filename in setup_lists["tenant_migrations"].filenames if filename != "011_add_phase5_tenant_tables.sql"
    )

    errors: list[str] = []
    shared_lists = {
        "public_migrations": (setup_public, sync_lists["public_migrations"].filenames),
        "tenant_migrations": (setup_tenant, sync_lists["tenant_migrations"].filenames),
    }
    for list_name, (left, right) in shared_lists.items():
        errors.extend(_compare_lists(list_name, MigrationList(list_name, left), MigrationList(list_name, right)))
        for filename in left:
            if not (migrations_dir / filename).exists():
                errors.append(f"{list_name}: migrations/{filename} が存在しません")

    # setup_tenant.py 固有の初期化 migration も存在確認だけは行う。
    for filename in ("014_create_current_tenant_id_function.sql", "011_add_phase5_tenant_tables.sql"):
        if not (migrations_dir / filename).exists():
            errors.append(f"setup_tenant.py 専用: migrations/{filename} が存在しません")

    if errors:
        raise SystemExit("schema catch-up lists are out of sync:\n- " + "\n- ".join(errors))


def main(argv: Iterable[str] | None = None) -> int:
    try:
        check_schema_catchup_sync()
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        return 1
    except Exception as exc:  # pragma: no cover - defensive
        print(f"schema catch-up sync check failed: {exc}", file=sys.stderr)
        return 1
    print("✅ schema catch-up migration lists are in sync")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
