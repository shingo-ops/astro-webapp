"""Sprint 9 / F9 v1.2: phase_gate サービスの単体テスト (実 PostgreSQL)。

spec.md v1.2 F9 / AC9.1:
  - Phase A: should_update_stock_quantity → False
  - Phase B/C: should_update_stock_quantity → True
  - tenant_settings 行が無い場合: 'A' fallback

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
    """テスト用の public.tenants 行を確保する。"""
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
        # 無ければ INSERT (テスト用)
        row = (
            await conn.execute(
                text(
                    "INSERT INTO public.tenants (tenant_code, company_name, is_active) "
                    "VALUES (:code, :name, TRUE) RETURNING id"
                ),
                {"code": tenant_code, "name": f"phase_gate_test_{tenant_code}"},
            )
        ).first()
        if row is None:
            raise RuntimeError(f"tenants INSERT failed for {tenant_code}")
        return int(row[0])


async def _cleanup(engine, tenant_id: int) -> None:
    from sqlalchemy import text

    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM public.tenant_settings WHERE tenant_id = :tid"),
            {"tid": tenant_id},
        )


async def test_get_phase_returns_a_when_no_row(engine):
    """tenant_settings 行が無い → 'A' fallback。"""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.services.phase_gate import get_phase

    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    tag = uuid.uuid4().hex[:8]
    tenant_id = await _ensure_tenant(engine, f"pg_test_{tag}")
    # 行を確実に削除
    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM public.tenant_settings WHERE tenant_id = :tid"),
            {"tid": tenant_id},
        )

    async with SessionLocal() as db:
        phase = await get_phase(tenant_id, db)
    assert phase == "A"
    await _cleanup(engine, tenant_id)


async def test_get_phase_returns_b_when_set(engine):
    """tenant_settings.spreadsheet_phase='B' → 'B' を返す。"""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.services.phase_gate import get_phase

    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    tag = uuid.uuid4().hex[:8]
    tenant_id = await _ensure_tenant(engine, f"pg_test_{tag}")
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO public.tenant_settings (tenant_id, spreadsheet_phase) "
                "VALUES (:tid, 'B') "
                "ON CONFLICT (tenant_id) DO UPDATE SET spreadsheet_phase='B'"
            ),
            {"tid": tenant_id},
        )

    async with SessionLocal() as db:
        phase = await get_phase(tenant_id, db)
    assert phase == "B"
    await _cleanup(engine, tenant_id)


async def test_should_update_stock_quantity_phase_a_false(engine):
    """Phase A → False (stock 更新 skip)。"""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.services.phase_gate import should_update_stock_quantity

    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    tag = uuid.uuid4().hex[:8]
    tenant_id = await _ensure_tenant(engine, f"pg_test_{tag}")
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO public.tenant_settings (tenant_id, spreadsheet_phase) "
                "VALUES (:tid, 'A') "
                "ON CONFLICT (tenant_id) DO UPDATE SET spreadsheet_phase='A'"
            ),
            {"tid": tenant_id},
        )

    async with SessionLocal() as db:
        result = await should_update_stock_quantity(tenant_id, db)
    assert result is False
    await _cleanup(engine, tenant_id)


async def test_should_update_stock_quantity_phase_b_true(engine):
    """Phase B → True (stock 更新する)。"""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.services.phase_gate import should_update_stock_quantity

    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    tag = uuid.uuid4().hex[:8]
    tenant_id = await _ensure_tenant(engine, f"pg_test_{tag}")
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO public.tenant_settings (tenant_id, spreadsheet_phase) "
                "VALUES (:tid, 'B') "
                "ON CONFLICT (tenant_id) DO UPDATE SET spreadsheet_phase='B'"
            ),
            {"tid": tenant_id},
        )

    async with SessionLocal() as db:
        result = await should_update_stock_quantity(tenant_id, db)
    assert result is True
    await _cleanup(engine, tenant_id)


async def test_set_phase_upserts(engine):
    """set_phase は UPSERT 動作する (新規 / 既存どちらも 1 行)。"""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.services.phase_gate import set_phase

    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    tag = uuid.uuid4().hex[:8]
    tenant_id = await _ensure_tenant(engine, f"pg_test_{tag}")
    # 初期状態: 行無し
    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM public.tenant_settings WHERE tenant_id = :tid"),
            {"tid": tenant_id},
        )

    async with SessionLocal() as db:
        applied = await set_phase(tenant_id, "B", db)
        await db.commit()
    assert applied == "B"

    # 再度 set_phase → 'A' に戻す (UPSERT)
    async with SessionLocal() as db:
        applied2 = await set_phase(tenant_id, "A", db)
        await db.commit()
    assert applied2 == "A"

    # DB 上 1 行のみであること
    async with engine.connect() as conn:
        count = (
            await conn.execute(
                text(
                    "SELECT COUNT(*) FROM public.tenant_settings WHERE tenant_id = :tid"
                ),
                {"tid": tenant_id},
            )
        ).scalar_one()
    assert count == 1
    await _cleanup(engine, tenant_id)


async def test_set_phase_invalid_raises(engine):
    """ALLOWED_PHASES 外の値は ValueError。"""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.services.phase_gate import set_phase

    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    tag = uuid.uuid4().hex[:8]
    tenant_id = await _ensure_tenant(engine, f"pg_test_{tag}")
    async with SessionLocal() as db:
        with pytest.raises(ValueError):
            await set_phase(tenant_id, "Z", db)  # type: ignore[arg-type]
    await _cleanup(engine, tenant_id)
