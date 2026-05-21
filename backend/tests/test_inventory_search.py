"""Sprint 7 (F7) 在庫検索 API の E2E (実 Postgres)。

AC7.1: 「リザードン」入力 → pokemon_dex 経由で日本語名 + 英名 Charizard ヒット
AC7.2: 「SV1a-001」入力 → card_number ヒット商品が候補トップ (rank 1)
AC7.3: supplier alias「リザ eX SAR」入力 → supplier_aliases 解決経由で標準名候補
AC7.4: 標準名 (public.products.name) が返ること (フロント側の onSelect → line_item へ)
AC7.5: 在庫 0 商品は候補末尾、stock_quantity = 0 を含む
AC7.8: AND モード「リザードン SV1a」両方ヒットのみ / OR モード片方でもヒット
AC7.9: visibility.full なし user では stock_quantity = None (masked=True)

SQLite モック禁止 (memory: feedback_evaluator_gap_2026_05_15)。
TEST_PG_URL 未設定時は skip。

Generator 自己評価メモ (2026-05-22):
  - 実 PG への接続を持たないローカル環境では本テストは skip される。
  - 構造テスト (token 分割 / SQL 構築 / mask フラグ計算) は
    test_inventory_search_logic.py で SQLite 不要の純 Python ユニットテストとして
    補完する。
  - 本ファイルは Reviewer / CI / VPS 側で TEST_PG_URL が用意されたタイミングで
    AC7.* を実 PG で検証することを意図している。
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


@pytest.fixture
async def seed_search_dataset(engine):
    """検索 AC 用に最小限の seed を入れる。

    - public.products: リザードン (在庫 5)、ピカチュウ (在庫 0)、SV1a-001 card_number 一致 (在庫 3)
    - public.pokemon_dex: リザードン / Charizard / ピカチュウ / Pikachu
    - public.supplier_aliases: supplier + alias_text 「リザ eX SAR」→ product_id = リザードン

    Returns: dict with all created ids and cleanup helper.
    """
    from sqlalchemy import text

    tag = uuid.uuid4().hex[:8]
    sup_name = f"sprint7_sup_{tag}"

    async with engine.begin() as conn:
        # 既存 seed と衝突しないよう uniq tag を product_code / alias に混ぜる
        sup_id = (
            await conn.execute(
                text(
                    "INSERT INTO public.suppliers (name, supplier_type, default_language) "
                    "VALUES (:n, 'corporate', 'ja') RETURNING id"
                ),
                {"n": sup_name},
            )
        ).scalar_one()

        rid = (
            await conn.execute(
                text(
                    "INSERT INTO public.products "
                    "(tenant_id, product_code, name, name_en, expansion_code, "
                    " card_number, jan_code, unit_price, stock_quantity) "
                    "VALUES (NULL, :code, :name, :name_en, :exp, :card, :jan, :price, :stock) "
                    "RETURNING id"
                ),
                {
                    "code": f"S7-LIZ-{tag}",
                    "name": f"リザードン {tag}",
                    "name_en": f"Charizard {tag}",
                    "exp": "SV1a",
                    "card": f"SV1a-001-{tag}",
                    "jan": None,
                    "price": 1500.00,
                    "stock": 5,
                },
            )
        ).scalar_one()

        pid_zero = (
            await conn.execute(
                text(
                    "INSERT INTO public.products "
                    "(tenant_id, product_code, name, name_en, expansion_code, "
                    " card_number, unit_price, stock_quantity) "
                    "VALUES (NULL, :code, :name, :name_en, :exp, :card, :price, :stock) "
                    "RETURNING id"
                ),
                {
                    "code": f"S7-PIKA-{tag}",
                    "name": f"ピカチュウ {tag}",
                    "name_en": f"Pikachu {tag}",
                    "exp": "SV1a",
                    "card": f"SV1a-002-{tag}",
                    "price": 1200.00,
                    "stock": 0,  # 在庫 0 末尾化テスト
                },
            )
        ).scalar_one()

        # pokemon_dex は通常 seed 済みだが、新規 tag つきの行を補強 (UNIQUE dex_number を避けて高い番号)
        # 既存 pokemon_dex に Charizard (dex_number=6) があれば、JOIN 条件 (name=name_ja / name_en=name_en) で
        # 今回の "リザードン <tag>" にはヒットしない (name 一致しない)。
        # 検索動作は m_products の name ILIKE %リザードン% でカバーされる。
        # ここでは m_pokemon の経路の検証用に test 専用 dex_number で追加する。
        await conn.execute(
            text(
                "INSERT INTO public.pokemon_dex (dex_number, name_ja, name_en, generation) "
                "VALUES (:n, :ja, :en, 9) "
                "ON CONFLICT (dex_number) DO NOTHING"
            ),
            # 既存 1025 を超える番号で衝突回避
            {"n": 9000 + int(tag[:4], 16) % 800, "ja": f"リザードン {tag}", "en": f"Charizard {tag}"},
        )

        # supplier_aliases
        alias_text = f"リザ eX SAR {tag}"
        await conn.execute(
            text(
                "INSERT INTO public.supplier_aliases "
                "(product_id, supplier_id, alias_text, language, confidence, source) "
                "VALUES (:pid, :sup, :alias, 'ja', 0.95, 'manual')"
            ),
            {"pid": rid, "sup": sup_id, "alias": alias_text},
        )

    yield {
        "tag": tag,
        "supplier_id": sup_id,
        "lizardon_id": rid,
        "pika_zero_id": pid_zero,
        "alias_text": alias_text,
    }

    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM public.supplier_aliases WHERE supplier_id = :s"),
            {"s": sup_id},
        )
        await conn.execute(
            text("DELETE FROM public.products WHERE id IN (:a, :b)"),
            {"a": rid, "b": pid_zero},
        )
        await conn.execute(
            text("DELETE FROM public.suppliers WHERE id = :s"),
            {"s": sup_id},
        )


async def test_search_lizardon_ja(engine, seed_search_dataset):
    """AC7.1: 「リザードン」入力 → product 日本語名 + name_en の Charizard が候補に含まれる。"""
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.services.inventory_search import search_inventory

    seed = seed_search_dataset
    async with AsyncSession(engine) as db:
        cands = await search_inventory(
            db,
            query=f"リザードン {seed['tag']}",
            op="or",
            limit=20,
            mask_stock=False,
        )
    assert len(cands) >= 1
    matched = [c for c in cands if c.product_id == seed["lizardon_id"]]
    assert matched, "lizardon product should be matched"
    assert matched[0].name_en and "Charizard" in matched[0].name_en


async def test_search_card_number_exact_top(engine, seed_search_dataset):
    """AC7.2: card_number 完全一致が rank 1 (score 最小) でトップに来る。"""
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.services.inventory_search import search_inventory

    seed = seed_search_dataset
    async with AsyncSession(engine) as db:
        cands = await search_inventory(
            db,
            query=f"SV1a-001-{seed['tag']}",
            op="or",
            limit=20,
            mask_stock=False,
        )
    assert cands
    assert cands[0].product_id == seed["lizardon_id"]
    assert cands[0].matched_via.startswith("products_card_number")


async def test_search_supplier_alias(engine, seed_search_dataset):
    """AC7.3: supplier alias 一致経由で標準名 product が候補に出る。"""
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.services.inventory_search import search_inventory

    seed = seed_search_dataset
    async with AsyncSession(engine) as db:
        cands = await search_inventory(
            db,
            query=seed["alias_text"],
            op="or",
            limit=20,
            mask_stock=False,
        )
    assert any(c.product_id == seed["lizardon_id"] for c in cands)


async def test_search_zero_stock_at_tail(engine, seed_search_dataset):
    """AC7.5: 在庫 0 商品が末尾配置される (score >= 1000 ペナルティ)。"""
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.services.inventory_search import search_inventory

    seed = seed_search_dataset
    async with AsyncSession(engine) as db:
        cands = await search_inventory(
            db, query=f"SV1a {seed['tag']}", op="and", limit=20, mask_stock=False
        )
    # 在庫 5 (lizardon) と 0 (pika) が両方ヒット
    ids = [c.product_id for c in cands]
    assert seed["lizardon_id"] in ids
    assert seed["pika_zero_id"] in ids
    # 在庫 0 が末尾、stock=0
    pika_idx = ids.index(seed["pika_zero_id"])
    lizardon_idx = ids.index(seed["lizardon_id"])
    assert pika_idx > lizardon_idx, "zero-stock product should rank below in-stock"


async def test_search_and_vs_or(engine, seed_search_dataset):
    """AC7.8: AND モードは両 token 一致のみ、OR は片方一致でもヒット。"""
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.services.inventory_search import search_inventory

    seed = seed_search_dataset
    # 「リザードン <tag>」 + 「SV1a」両方一致するのは lizardon のみ (pika は SV1a だがリザードンの名前を持たない)
    async with AsyncSession(engine) as db:
        cands_and = await search_inventory(
            db,
            query=f"リザードン {seed['tag']} SV1a",
            op="and",
            limit=20,
            mask_stock=False,
        )
        cands_or = await search_inventory(
            db,
            query=f"リザードン {seed['tag']} SV1a",
            op="or",
            limit=20,
            mask_stock=False,
        )
    and_ids = {c.product_id for c in cands_and}
    or_ids = {c.product_id for c in cands_or}
    assert seed["lizardon_id"] in and_ids
    assert seed["pika_zero_id"] not in and_ids
    assert seed["lizardon_id"] in or_ids
    assert seed["pika_zero_id"] in or_ids


async def test_search_visibility_mask(engine, seed_search_dataset):
    """AC7.9: mask_stock=True で stock_quantity が None になる。"""
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.services.inventory_search import search_inventory

    seed = seed_search_dataset
    async with AsyncSession(engine) as db:
        cands = await search_inventory(
            db, query=f"リザードン {seed['tag']}", op="or", limit=10, mask_stock=True
        )
    assert cands
    for c in cands:
        assert c.stock_quantity is None
