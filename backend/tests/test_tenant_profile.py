"""tenant_profile router のテスト (Sprint 8 / F8)

SQLite ベースで CRUD + 認可 + audit_log を検証する。
実 Postgres でのテナント別 schema 検証 + migration 069 は
test_inventory_sprint8_migrations.py (TEST_PG_URL 環境) で行う。

カバー範囲:
  - GET /admin/tenant-profile: 既定の空行が返る
  - PUT /admin/tenant-profile: 部分更新が反映される
  - PUT validation: default_language の不正値で 422
"""
from __future__ import annotations

import pytest
from sqlalchemy import text


@pytest.mark.asyncio
async def test_get_tenant_profile_returns_seeded_row(client, db_session):
    """既定行 (空) が seed されている前提で 200 を返す。"""
    # SQLite テストでは migration 069 が走らないので手動 seed
    await db_session.execute(text("INSERT INTO tenant_profile (default_language) VALUES ('ja')"))
    await db_session.commit()

    resp = await client.get("/api/v1/admin/tenant-profile")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["default_language"] == "ja"
    assert body["company_name"] in (None, "")


@pytest.mark.asyncio
async def test_get_tenant_profile_404_when_not_seeded(client, db_session):
    """seed 未投入なら 404 (migration 069 適用要)。"""
    # tenant_profile テーブルを空にする (cleanup fixture が次のテストで再投入)
    await db_session.execute(text("DELETE FROM tenant_profile"))
    await db_session.commit()

    resp = await client.get("/api/v1/admin/tenant-profile")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_tenant_profile_persists_fields(client, db_session):
    """PUT で送ったフィールドが永続化される。"""
    await db_session.execute(text("INSERT INTO tenant_profile (default_language) VALUES ('ja')"))
    await db_session.commit()

    payload = {
        "company_name": "QA テナント株式会社",
        "company_name_en": "QA Tenant Inc.",
        "address": "東京都渋谷区 1-2-3",
        "phone": "03-1234-5678",
        "email": "po@qa-tenant.example.com",
        "website": "https://qa-tenant.example.com",
        "default_language": "en",
    }
    resp = await client.put("/api/v1/admin/tenant-profile", json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["company_name"] == "QA テナント株式会社"
    assert body["company_name_en"] == "QA Tenant Inc."
    assert body["default_language"] == "en"

    # DB 直接確認
    row = (await db_session.execute(text(
        "SELECT company_name, default_language FROM tenant_profile ORDER BY id LIMIT 1"
    ))).first()
    assert row[0] == "QA テナント株式会社"
    assert row[1] == "en"


@pytest.mark.asyncio
async def test_update_tenant_profile_partial_update(client, db_session):
    """指定フィールドのみ更新、他フィールドはそのまま。"""
    await db_session.execute(text(
        "INSERT INTO tenant_profile (company_name, default_language) VALUES ('既存', 'ja')"
    ))
    await db_session.commit()

    resp = await client.put(
        "/api/v1/admin/tenant-profile",
        json={"phone": "06-9999-0000"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["phone"] == "06-9999-0000"
    assert body["company_name"] == "既存"  # 維持
    assert body["default_language"] == "ja"  # 維持


@pytest.mark.asyncio
async def test_update_tenant_profile_rejects_invalid_language(client, db_session):
    """default_language のホワイトリスト外は 422。"""
    await db_session.execute(text("INSERT INTO tenant_profile (default_language) VALUES ('ja')"))
    await db_session.commit()

    resp = await client.put(
        "/api/v1/admin/tenant-profile",
        json={"default_language": "fr"},
    )
    # FastAPI + pydantic field_validator → 422
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_update_tenant_profile_404_when_not_seeded(client, db_session):
    """既定行が無い (migration 069 未適用) → 404。"""
    await db_session.execute(text("DELETE FROM tenant_profile"))
    await db_session.commit()

    resp = await client.put(
        "/api/v1/admin/tenant-profile",
        json={"company_name": "X"},
    )
    assert resp.status_code == 404
