"""Super-admin Discord Inbound 一覧 / 詳細 API テスト (Sprint 5 F5)。

AC 対応:
  - AC5.5 backend: GET /api/v1/super-admin/inbound/discord で require_super_admin
                   + 時系列降順 + parse_status filter + supplier_id filter
  - 403 ガード: is_super_admin=false の user は 403

実 PostgreSQL + 実 FastAPI app。SQLite モック禁止 (memory: feedback_evaluator_gap_2026_05_15)。
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone

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


@pytest.fixture
async def seed_inbound_messages(engine):
    """3 件の inbound メッセージ + supplier を seed。"""
    from sqlalchemy import text

    sup_name = f"sprint5_api_sup_{uuid.uuid4().hex[:6]}"
    channel_id = f"c_api_{uuid.uuid4().hex[:10]}"
    msg_ids = [f"sprint5_api_{i}_{uuid.uuid4().hex[:6]}" for i in range(3)]

    async with engine.begin() as conn:
        exists = (await conn.execute(text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name='discord_inbound_messages'"
        ))).scalar_one_or_none()
        if not exists:
            pytest.skip("public.discord_inbound_messages 未作成 (migration 059 必要)")

        result = await conn.execute(text("""
            INSERT INTO public.suppliers (name, supplier_type, default_language)
            VALUES (:n, 'corporate', 'ja')
            RETURNING id
        """), {"n": sup_name})
        sup_id = result.scalar_one()

        # 3 件投入、parse_status バリエーション
        statuses = ["pending", "parsed_rule_only", "ignored_routing"]
        for i, (mid, st) in enumerate(zip(msg_ids, statuses)):
            await conn.execute(text("""
                INSERT INTO public.discord_inbound_messages
                    (discord_message_id, discord_channel_id, supplier_id,
                     raw_content, parse_status, received_at)
                VALUES (:mid, :ch, :sid, :raw, :st, NOW() - (:delay || ' seconds')::interval)
            """), {
                "mid": mid, "ch": channel_id,
                "sid": sup_id if st != "ignored_routing" else None,
                "raw": f"sample content {i} for {mid}",
                "st": st,
                "delay": i * 10,
            })

    yield {
        "supplier_id": sup_id,
        "channel_id": channel_id,
        "msg_ids": msg_ids,
    }

    # cleanup
    async with engine.begin() as conn:
        await conn.execute(text(
            "DELETE FROM public.discord_inbound_messages WHERE discord_channel_id = :ch"
        ), {"ch": channel_id})
        await conn.execute(text(
            "DELETE FROM public.suppliers WHERE id = :sid"
        ), {"sid": sup_id})


async def test_list_inbound_returns_seeded_rows(engine, seed_inbound_messages):
    """AC5.5: GET /super-admin/inbound/discord で seed 3 件が降順で返る。

    実 FastAPI app + AsgiTransport で叩く。
    require_super_admin は dependency_overrides で bypass する。
    """
    from fastapi.testclient import TestClient
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    from app.auth.dependencies import require_super_admin
    from app.models import User

    ctx = seed_inbound_messages

    # is_super_admin=true な User を override で注入
    async def _fake_super_admin() -> User:
        u = User()
        u.id = 1
        u.is_super_admin = True
        u.role = "admin"
        u.tenant_id = 6
        return u

    app.dependency_overrides[require_super_admin] = _fake_super_admin
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            # 全件
            resp = await client.get("/api/v1/super-admin/inbound/discord?per_page=100")
            assert resp.status_code == 200, resp.text
            data = resp.json()

            # seed した 3 件全てが含まれる
            returned_ids = {item["discord_message_id"] for item in data}
            for mid in ctx["msg_ids"]:
                assert mid in returned_ids, f"{mid} not in {returned_ids}"

            # 時系列降順 (received_at が新しい順)
            recv_times = [item["received_at"] for item in data if item["discord_message_id"] in set(ctx["msg_ids"])]
            assert recv_times == sorted(recv_times, reverse=True)

            # parse_status filter
            resp_filter = await client.get(
                "/api/v1/super-admin/inbound/discord?parse_status=ignored_routing&per_page=100"
            )
            assert resp_filter.status_code == 200
            filtered = resp_filter.json()
            ignored_in_ctx = {
                item for item in filtered
                if item["discord_message_id"] in set(ctx["msg_ids"])
            }
            # seed では ignored_routing は 1 件
            assert len(ignored_in_ctx) == 1
    finally:
        app.dependency_overrides.pop(require_super_admin, None)


async def test_list_inbound_403_without_super_admin(engine, seed_inbound_messages):
    """is_super_admin=false の user は 403。"""
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    from app.auth.dependencies import require_super_admin, get_current_user
    from fastapi import HTTPException, status
    from app.models import User

    async def _fake_non_super_admin() -> User:
        u = User()
        u.id = 2
        u.is_super_admin = False
        u.role = "admin"
        u.tenant_id = 6
        return u

    # get_current_user を override し、require_super_admin の本来の判定を通す
    app.dependency_overrides[get_current_user] = _fake_non_super_admin
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/super-admin/inbound/discord?per_page=10")
            assert resp.status_code == 403, resp.text
    finally:
        app.dependency_overrides.pop(get_current_user, None)


# ---------------------------------------------------------------------------
# PR5c: 取込候補で unit / condition / language を取得する（実 PG）
# ---------------------------------------------------------------------------
@pytest.fixture
async def seed_inbound_for_import(engine):
    """parse_result_json に unit/condition 付きの items を持つ 1 件を seed。

    - 日本語名（carton×2 → mode=case, condition=shrink）
    - 英語名（BOX → box, condition なし）
    どちらも商品マスタ未登録になるよう uuid 付きユニーク名にする。
    """
    from sqlalchemy import text

    channel_id = f"c_imp_{uuid.uuid4().hex[:10]}"
    msg_id = f"imp_{uuid.uuid4().hex[:8]}"
    jp_name = f"テスト取込_{uuid.uuid4().hex[:8]}"
    en_name = f"TestImport {uuid.uuid4().hex[:8]}"
    parse_result = {
        "items": [
            {"product_name": jp_name, "raw_line": f"{jp_name} 2カートン", "unit": "carton", "condition": "Shrink"},
            {"product_name": jp_name, "raw_line": f"{jp_name} 1カートン", "unit": "carton", "condition": "shrink"},
            {"product_name": en_name, "raw_line": f"{en_name} 1box", "unit": "BOX", "condition": None},
        ]
    }

    async with engine.begin() as conn:
        exists = (await conn.execute(text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name='discord_inbound_messages'"
        ))).scalar_one_or_none()
        if not exists:
            pytest.skip("public.discord_inbound_messages 未作成 (migration 059 必要)")
        # PR5b の unit 列が無い環境ではスキップ（migration 未適用）。
        has_unit = (await conn.execute(text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name='products' AND column_name='unit'"
        ))).scalar_one_or_none()
        if not has_unit:
            pytest.skip("public.products.unit 未作成 (PR5b migration 必要)")

        await conn.execute(text("""
            INSERT INTO public.discord_inbound_messages
                (discord_message_id, discord_channel_id,
                 raw_content, parse_status, parse_result_json, received_at)
            VALUES (:mid, :ch, :raw, 'parsed_rule_only', CAST(:prj AS jsonb), NOW())
        """), {"mid": msg_id, "ch": channel_id, "raw": "import test",
               "prj": json.dumps(parse_result)})

    yield {"channel_id": channel_id, "jp_name": jp_name, "en_name": en_name}

    async with engine.begin() as conn:
        await conn.execute(text(
            "DELETE FROM public.discord_inbound_messages WHERE discord_channel_id = :ch"
        ), {"ch": channel_id})
        await conn.execute(text(
            "DELETE FROM public.products WHERE name IN (:jp, :en)"
        ), {"jp": jp_name, "en": en_name})


async def test_import_candidates_and_apply_capture_unit_condition_language(
    engine, seed_inbound_for_import
):
    """PR5c: 候補で unit(carton→case)/condition、apply で products へ転記。
    言語は全件デフォルト ja（2026-06-02 方針）、apply で en へ上書き可。

    - jp_name: unit=case(carton正規化), condition=shrink, language=ja(既定)
    - en_name: unit=box(BOX小文字化), language=ja(既定) → apply で languages 上書き en
    """
    from httpx import AsyncClient, ASGITransport
    from sqlalchemy import text
    from app.main import app
    from app.auth.dependencies import require_super_admin
    from app.models import User

    ctx = seed_inbound_for_import
    jp_name, en_name = ctx["jp_name"], ctx["en_name"]

    async def _fake_super_admin() -> User:
        u = User()
        u.id = 1
        u.is_super_admin = True
        u.role = "admin"
        u.tenant_id = 6
        return u

    app.dependency_overrides[require_super_admin] = _fake_super_admin
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/super-admin/inbound/product-candidates")
            assert resp.status_code == 200, resp.text
            by_name = {c["name"]: c for c in resp.json()["candidates"]}
            assert jp_name in by_name and en_name in by_name

            jp = by_name[jp_name]
            assert jp["unit"] == "case"          # carton → case 正規化
            assert jp["condition"] == "shrink"   # 小文字化 + mode
            assert jp["language"] == "ja"         # 既定 ja

            en = by_name[en_name]
            assert en["unit"] == "box"           # BOX → box 小文字化
            assert en["language"] == "ja"         # 既定 ja（自動判定は廃止）

            # apply: en_name の言語をオペレータが en に修正したケース
            resp2 = await client.post(
                "/api/v1/super-admin/inbound/product-candidates/apply",
                json={"names": [jp_name, en_name], "languages": {en_name: "en"}},
            )
            assert resp2.status_code == 200, resp2.text
            assert resp2.json()["inserted"] == 2

        async with engine.begin() as conn:
            rows = (await conn.execute(text(
                "SELECT name, unit, condition, language FROM public.products "
                "WHERE name IN (:jp, :en)"
            ), {"jp": jp_name, "en": en_name})).mappings().all()
        got = {r["name"]: r for r in rows}
        assert got[jp_name]["unit"] == "case"
        assert got[jp_name]["condition"] == "shrink"
        assert got[jp_name]["language"] == "ja"   # 上書きなし → 既定 ja
        assert got[en_name]["unit"] == "box"
        assert got[en_name]["language"] == "en"   # languages 上書きが優先
    finally:
        app.dependency_overrides.pop(require_super_admin, None)
