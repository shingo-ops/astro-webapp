"""ADR-072 Phase 2: 残 router の `reset_tenant_context()` 呼び出し導入を回帰保護する。

PR #780 (Phase 1) で `app.auth.dependencies` に公開された `reset_tenant_context`
を、Phase 2 で `shifts.py` / `suppliers.py` / `staff.py` / `roles.py` の
write endpoint に展開した。本ファイルは「各 router で reset_tenant_context が
import されている」「`await db.commit()` 後の呼び出し数が期待値と一致する」を
ソース解析で確認する。

dashboard.py は read-only (`commit()` ゼロ件) のため Phase 2 対象外。
"""
from __future__ import annotations

import inspect

import pytest

from app.routers import roles, shifts, staff, suppliers


@pytest.mark.parametrize("module", [shifts, suppliers, staff, roles])
def test_phase_2_routers_import_reset_tenant_context(module):
    """4 router 全てで `reset_tenant_context` を import している。"""
    src = inspect.getsource(module)
    assert "reset_tenant_context" in src, (
        f"{module.__name__} should import reset_tenant_context from app.auth.dependencies"
    )


_EXPECTED_RESET_CALLS = {
    # router_module_name: count of `await reset_tenant_context(db, tenant_id)`
    # staff.py: create / update / delete / patch-me-profile の 4 箇所
    #   (L228 / L252 は public.users 操作なので Phase 2 対象外)
    "staff": 4,
    # suppliers.py: create / update / delete の 3 箇所
    "suppliers": 3,
    # roles.py: create / update / delete / set_permissions / set_user_roles の 5 箇所
    "roles": 5,
    # shifts.py: create / delete の 2 箇所
    "shifts": 2,
}


@pytest.mark.parametrize("name,expected", list(_EXPECTED_RESET_CALLS.items()))
def test_phase_2_routers_reset_call_count(name, expected):
    """各 router の `reset_tenant_context(db, tenant_id)` 呼び出し数が期待値と一致する。

    削除されたり commit と reset の対応が崩れると Phase 2 の意図が消えるため
    回帰保護として件数で固定する (ADR-072 §「決定」§5 / Phase 2 移行計画)。
    """
    mod = __import__(f"app.routers.{name}", fromlist=[""])
    src = inspect.getsource(mod)
    actual = src.count("await reset_tenant_context(db, tenant_id)")
    assert actual == expected, (
        f"{name}.py: expected {expected} reset_tenant_context() calls, got {actual}. "
        f"ADR-072 Phase 2 の意図が崩れている可能性。`docs/adr/ADR-072-*.md` §5 参照。"
    )


def test_dashboard_router_is_read_only():
    """ADR-072 Phase 2: dashboard.py は read-only (`commit()` ゼロ件) のため reset_tenant_context 不要。"""
    from app.routers import dashboard

    src = inspect.getsource(dashboard)
    assert "await db.commit()" not in src, (
        "dashboard.py is expected to be read-only (no commit). "
        "もし commit が追加されたなら ADR-072 Phase 2 の判定を更新すること。"
    )
