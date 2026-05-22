"""Sprint 9 / F9 v1.2: /super-admin/phase-switch エンドポイントの RBAC + 切替テスト。

spec.md v1.2 F9 / AC9.3 / AC9.4:
  - GET: 現在 Phase 取得（is_super_admin only）
  - PUT 'A': 成功 (冪等、audit_log 記録)
  - PUT 'B' / 'C': 400 phase_out_of_scope (Out-of-scope、別 ADR)
  - is_super_admin=false: 403

SQLite モック禁止 (memory: feedback_evaluator_gap_2026_05_15)。
"""

from __future__ import annotations

import os
import uuid

import pytest

TEST_PG_URL = os.getenv("TEST_PG_URL")

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not TEST_PG_URL,
        reason="実 PostgreSQL 環境が必要 (TEST_PG_URL 未設定)。",
    ),
]


@pytest.fixture
async def engine():
    from sqlalchemy.ext.asyncio import create_async_engine

    eng = create_async_engine(TEST_PG_URL, echo=False)
    yield eng
    await eng.dispose()


async def _ensure_tenant(engine, tenant_code: str) -> int:
    from sqlalchemy import text

    async with engine.begin() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT id FROM public.tenants WHERE tenant_code = :code"
                ),
                {"code": tenant_code},
            )
        ).first()
        if row is not None:
            return int(row[0])
        row = (
            await conn.execute(
                text(
                    "INSERT INTO public.tenants (tenant_code, company_name, is_active) "
                    "VALUES (:code, :name, TRUE) RETURNING id"
                ),
                {"code": tenant_code, "name": f"phase_switch_test_{tenant_code}"},
            )
        ).first()
        if row is None:
            raise RuntimeError("tenants INSERT failed")
        return int(row[0])


def _client_with_overrides(
    engine,
    *,
    super_admin_id: int = 9201,
    is_super_admin: bool = True,
):
    """ASGITransport クライアント + get_db を PG engine で差し替え。"""
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    from app.database import get_db
    from app.auth.dependencies import require_super_admin, get_current_user
    from app.models import User

    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    async def override_get_db():
        async with SessionLocal() as session:
            yield session

    async def fake_user() -> User:
        u = User()
        u.id = super_admin_id
        u.is_super_admin = is_super_admin
        u.role = "admin" if is_super_admin else "ops"
        u.tenant_id = 6
        return u

    async def fake_super_admin() -> User:
        from fastapi import HTTPException, status

        if not is_super_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="この操作にはJarvis運用admin（中央admin）権限が必要です",
            )
        return await fake_user()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_super_admin] = fake_super_admin
    app.dependency_overrides[get_current_user] = fake_user

    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test"), app


async def test_get_phase_returns_a_default(engine):
    """AC9.5: GET /super-admin/phase-switch/{tenant_id} → 現在 Phase A を返す。"""
    from sqlalchemy import text

    tag = uuid.uuid4().hex[:8]
    tenant_id = await _ensure_tenant(engine, f"sw_get_{tag}")
    # seed: Phase=A
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO public.tenant_settings (tenant_id, spreadsheet_phase) "
                "VALUES (:tid, 'A') "
                "ON CONFLICT (tenant_id) DO UPDATE SET spreadsheet_phase='A'"
            ),
            {"tid": tenant_id},
        )

    client, app = _client_with_overrides(engine)
    try:
        async with client as c:
            r = await c.get(f"/api/v1/super-admin/phase-switch/{tenant_id}")
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["phase"] == "A"
            assert body["allowed_phases"] == ["A", "B", "C"]
            assert body["scoped_phases"] == ["A"]
    finally:
        app.dependency_overrides.clear()
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM public.tenant_settings WHERE tenant_id = :tid"),
                {"tid": tenant_id},
            )


async def test_put_phase_to_a_succeeds(engine):
    """AC9.3: PUT phase='A' → 200 OK (冪等、audit_log は best-effort 記録)。"""
    from sqlalchemy import text

    tag = uuid.uuid4().hex[:8]
    tenant_id = await _ensure_tenant(engine, f"sw_put_a_{tag}")

    client, app = _client_with_overrides(engine, super_admin_id=9202)
    try:
        async with client as c:
            r = await c.put(
                f"/api/v1/super-admin/phase-switch/{tenant_id}",
                json={"phase": "A"},
            )
            assert r.status_code == 200, r.text
            assert r.json()["phase"] == "A"

        # DB 上で 'A' になっていること
        async with engine.connect() as conn:
            phase = (
                await conn.execute(
                    text(
                        "SELECT spreadsheet_phase FROM public.tenant_settings "
                        "WHERE tenant_id = :tid"
                    ),
                    {"tid": tenant_id},
                )
            ).scalar_one()
            assert phase == "A"
    finally:
        app.dependency_overrides.clear()
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM public.tenant_settings WHERE tenant_id = :tid"),
                {"tid": tenant_id},
            )


async def test_put_phase_to_b_blocked_v1_2(engine):
    """AC9.3: PUT phase='B' → 400 phase_out_of_scope (spec v1.2 Out-of-scope)。"""
    from sqlalchemy import text

    tag = uuid.uuid4().hex[:8]
    tenant_id = await _ensure_tenant(engine, f"sw_put_b_{tag}")

    client, app = _client_with_overrides(engine)
    try:
        async with client as c:
            r = await c.put(
                f"/api/v1/super-admin/phase-switch/{tenant_id}",
                json={"phase": "B"},
            )
            assert r.status_code == 400, r.text
            body = r.json()
            # FastAPI HTTPException(detail=dict) はそのまま detail に dict が入る
            detail = body.get("detail", {})
            assert detail.get("error") == "phase_out_of_scope"
            assert "B" in detail.get("message", "")

        # DB は変化していないはず（INSERT は CHECK 制約で OK だが set_phase に到達しないこと）
        async with engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT spreadsheet_phase FROM public.tenant_settings "
                        "WHERE tenant_id = :tid"
                    ),
                    {"tid": tenant_id},
                )
            ).first()
            # 行が無い (まだ INSERT されていない) ことも、'A' のままになっていることも許容
            if row is not None:
                assert row[0] != "B"
    finally:
        app.dependency_overrides.clear()
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM public.tenant_settings WHERE tenant_id = :tid"),
                {"tid": tenant_id},
            )


async def test_put_phase_invalid_value_400(engine):
    """ALLOWED_PHASES 外 → 400 (DB CHECK の前段でブロック)。"""
    from sqlalchemy import text

    tag = uuid.uuid4().hex[:8]
    tenant_id = await _ensure_tenant(engine, f"sw_inv_{tag}")

    client, app = _client_with_overrides(engine)
    try:
        async with client as c:
            r = await c.put(
                f"/api/v1/super-admin/phase-switch/{tenant_id}",
                json={"phase": "Z"},
            )
            assert r.status_code == 400, r.text
    finally:
        app.dependency_overrides.clear()
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM public.tenant_settings WHERE tenant_id = :tid"),
                {"tid": tenant_id},
            )


async def test_rbac_non_super_admin_403(engine):
    """AC9.3: is_super_admin=false なら 403。"""
    from sqlalchemy import text

    tag = uuid.uuid4().hex[:8]
    tenant_id = await _ensure_tenant(engine, f"sw_403_{tag}")

    client, app = _client_with_overrides(
        engine, super_admin_id=9203, is_super_admin=False
    )
    try:
        async with client as c:
            r_get = await c.get(f"/api/v1/super-admin/phase-switch/{tenant_id}")
            assert r_get.status_code == 403, r_get.text

            r_put = await c.put(
                f"/api/v1/super-admin/phase-switch/{tenant_id}",
                json={"phase": "A"},
            )
            assert r_put.status_code == 403, r_put.text
    finally:
        app.dependency_overrides.clear()
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM public.tenant_settings WHERE tenant_id = :tid"),
                {"tid": tenant_id},
            )
