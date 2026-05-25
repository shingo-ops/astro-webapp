"""ADR-072 Phase 3: scripts/lint_tenant_schema.py の単体テスト。

positive (違反検出) / negative (clean) ケースを文字列で in-memory に与えて、
linter の出力を確認する。
"""
from __future__ import annotations

import sys
import tempfile
import textwrap
from pathlib import Path

# scripts/ を sys.path に追加 (CI / ローカル両方で動くように)
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from lint_tenant_schema import lint_file  # noqa: E402


def _write_tmp(src: str) -> Path:
    """tmp .py を作って lint_file に渡せる Path を返す。"""
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8")
    f.write(textwrap.dedent(src))
    f.close()
    return Path(f.name)


# ──────────────────────────────────────────────────────────────────
# Negative cases (clean): 違反ゼロ
# ──────────────────────────────────────────────────────────────────


def test_get_endpoint_no_commit_is_clean():
    """read-only endpoint で bare-table があっても commit がなければ違反なし。"""
    p = _write_tmp("""
        from sqlalchemy import text

        @router.get("/leads")
        async def list_leads(
            db: AsyncSession = Depends(get_db),
            tenant_id: int = Depends(get_current_tenant),
        ):
            await db.execute(text("SELECT * FROM leads"))
            return []
    """)
    assert lint_file(p) == []


def test_endpoint_with_tenant_table_ref_is_clean():
    """tenant_table_ref を使っている案 A 採用関数は違反なし。"""
    p = _write_tmp("""
        from sqlalchemy import text

        @router.post("/leads")
        async def create_lead(
            db: AsyncSession = Depends(get_db),
            tenant_id: int = Depends(get_current_tenant),
        ):
            leads_t = tenant_table_ref(db, tenant_id, "leads")
            await db.execute(text(f"INSERT INTO {leads_t} ..."))
            await db.commit()
            return {}
    """)
    assert lint_file(p) == []


def test_endpoint_with_reset_tenant_context_is_clean():
    """reset_tenant_context を呼んでいる案 B 採用関数は違反なし。"""
    p = _write_tmp("""
        from sqlalchemy import text

        @router.delete("/staff/{sid}")
        async def delete_staff(
            sid: int,
            db: AsyncSession = Depends(get_db),
            tenant_id: int = Depends(get_current_tenant),
        ):
            await db.execute(text("DELETE FROM staff WHERE id = :id"), {"id": sid})
            await db.commit()
            await reset_tenant_context(db, tenant_id)
    """)
    assert lint_file(p) == []


def test_endpoint_without_tenant_id_dep_is_skipped():
    """tenant_id 依存なし (super_admin 系) は対象外。"""
    p = _write_tmp("""
        from sqlalchemy import text

        @router.post("/super-admin/foo")
        async def create_foo(
            db: AsyncSession = Depends(get_db),
        ):
            await db.execute(text("INSERT INTO leads ..."))
            await db.commit()
    """)
    assert lint_file(p) == []


def test_non_router_function_is_skipped():
    """通常の async 関数 (内部 helper) は endpoint と認識しない。"""
    p = _write_tmp("""
        from sqlalchemy import text

        async def _internal_helper(db, tenant_id: int):
            await db.execute(text("SELECT * FROM staff"))
            await db.commit()
    """)
    assert lint_file(p) == []


# ──────────────────────────────────────────────────────────────────
# Positive cases (violation): 検出されるべき
# ──────────────────────────────────────────────────────────────────


def test_rule_a_bare_table_with_commit_no_helper():
    """commit を含む endpoint で bare-table、helper も reset もなし → Rule A 違反。"""
    p = _write_tmp("""
        from sqlalchemy import text

        @router.post("/leads")
        async def create_lead(
            db: AsyncSession = Depends(get_db),
            tenant_id: int = Depends(get_current_tenant),
        ):
            await db.execute(text("INSERT INTO leads (id) VALUES (1)"))
            await db.commit()
    """)
    violations = lint_file(p)
    rules = [v.rule for v in violations]
    assert "A" in rules
    assert any("leads" in v.message for v in violations)


def test_rule_b_write_endpoint_commit_without_reset():
    """write endpoint で commit > reset → Rule B 違反。"""
    p = _write_tmp("""
        from sqlalchemy import text

        @router.post("/foo")
        async def create_foo(
            db: AsyncSession = Depends(get_db),
            tenant_id: int = Depends(get_current_tenant),
        ):
            await db.execute(text("SELECT 1"))
            await db.commit()
    """)
    violations = lint_file(p)
    rules = [v.rule for v in violations]
    assert "B" in rules


def test_rule_b_partial_reset_still_violation():
    """commit が 2 つあって reset が 1 つだけなら不足分が違反。"""
    p = _write_tmp("""
        from sqlalchemy import text

        @router.patch("/foo")
        async def update_foo(
            db: AsyncSession = Depends(get_db),
            tenant_id: int = Depends(get_current_tenant),
        ):
            await db.execute(text("SELECT 1"))
            await db.commit()
            await db.execute(text("SELECT 2"))
            await db.commit()
            await reset_tenant_context(db, tenant_id)
    """)
    violations = lint_file(p)
    rules = [v.rule for v in violations]
    assert "B" in rules


def test_schema_qualified_text_is_not_flagged():
    """f-string で schema 修飾済の text は Rule A 違反にならない。"""
    p = _write_tmp("""
        from sqlalchemy import text

        @router.post("/leads")
        async def create_lead(
            db: AsyncSession = Depends(get_db),
            tenant_id: int = Depends(get_current_tenant),
        ):
            leads_t = tenant_table_ref(db, tenant_id, "leads")
            await db.execute(text(f"INSERT INTO {leads_t} ..."))
            await db.commit()
    """)
    violations = lint_file(p)
    # has_helper=True なので Rule A も Rule B も発火しないはず
    assert violations == []
