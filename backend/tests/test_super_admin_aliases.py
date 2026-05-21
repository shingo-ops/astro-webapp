"""Super-admin supplier_aliases ルーターのテスト。

spec.md v1.1 F1 AC1.2 / F2 AC2.6:
  - UNIQUE(supplier_id, alias_text, language) で 23505 が返ることを確認
  - CSV import の inserted/skipped 計数が xmax = 0 で正しく行単位判定される
    (Sprint 2 Reviewer F1 / PR #510 fix)

実 PostgreSQL 必須。
"""
from __future__ import annotations

import os
from pathlib import Path

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


async def test_supplier_aliases_unique_constraint(engine):
    """AC1.2 確認: 同一 (supplier_id, alias_text, language) は重複不可。"""
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    async with engine.connect() as conn:
        exists = (await conn.execute(text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name='supplier_aliases'"
        ))).scalar_one_or_none()
    if not exists:
        pytest.skip("public.supplier_aliases 未作成 (migration 057 が必要)")

    # 任意の supplier を 1 行用意 / なければ skip
    async with engine.connect() as conn:
        sup = (await conn.execute(text(
            "SELECT id FROM public.suppliers WHERE is_active = TRUE LIMIT 1"
        ))).scalar_one_or_none()
    if not sup:
        pytest.skip("public.suppliers が空。Sprint 1 seed が未走行か?")

    test_alias = "TEST_AC1_2_RIZA_eX_SAR"

    # cleanup: 既存があれば消す
    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM public.supplier_aliases WHERE alias_text = :a"),
            {"a": test_alias},
        )

    async with engine.begin() as conn:
        await conn.execute(text("""
            INSERT INTO public.supplier_aliases
                (supplier_id, alias_text, language, source)
            VALUES (:sid, :alias, 'ja', 'manual')
        """), {"sid": sup, "alias": test_alias})

    # 同じ supplier_id × alias × language で再 INSERT → IntegrityError
    raised = False
    try:
        async with engine.begin() as conn:
            await conn.execute(text("""
                INSERT INTO public.supplier_aliases
                    (supplier_id, alias_text, language, source)
                VALUES (:sid, :alias, 'ja', 'manual')
            """), {"sid": sup, "alias": test_alias})
    except IntegrityError as exc:
        raised = True
        assert "23505" in str(exc.orig) or "duplicate" in str(exc.orig).lower()

    assert raised, "UNIQUE 制約が動作していない"

    # cleanup
    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM public.supplier_aliases WHERE alias_text = :a"),
            {"a": test_alias},
        )


async def test_csv_import_xmax_counts_inserted_vs_skipped(engine):
    """Sprint 2 Reviewer F1 (PR #510) fix の SQL レベル検証。

    `INSERT ... ON CONFLICT DO NOTHING RETURNING id, (xmax = 0)` を使うと、
    新規挿入 = xmax 0、既存衝突 = xmax != 0 で行単位の判定ができることを
    実 PostgreSQL で確認する（旧実装は UNIQUE 衝突を IntegrityError で検出
    しようとしていたが、ON CONFLICT DO NOTHING は IntegrityError を出さ
    ないため UNIQUE 衝突行も inserted にカウントしていた）。
    """
    from sqlalchemy import text

    async with engine.connect() as conn:
        exists = (await conn.execute(text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name='supplier_aliases'"
        ))).scalar_one_or_none()
    if not exists:
        pytest.skip("public.supplier_aliases 未作成 (migration 057 が必要)")

    async with engine.connect() as conn:
        sup = (await conn.execute(text(
            "SELECT id FROM public.suppliers WHERE is_active = TRUE LIMIT 1"
        ))).scalar_one_or_none()
    if not sup:
        pytest.skip("public.suppliers が空")

    aliases = [
        "TEST_F1_FIX_ALPHA",
        "TEST_F1_FIX_BRAVO",
        "TEST_F1_FIX_CHARLIE",
    ]

    # 事前 cleanup
    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM public.supplier_aliases WHERE alias_text = ANY(:as)"),
            {"as": aliases},
        )

    # Round 1: 3 件すべて新規 → 3 inserted
    inserted_r1 = 0
    skipped_r1 = 0
    async with engine.begin() as conn:
        for at in aliases:
            row = (await conn.execute(text(
                "INSERT INTO public.supplier_aliases "
                "(supplier_id, alias_text, language, source) "
                "VALUES (:sid, :at, 'ja', 'manual') "
                "ON CONFLICT (supplier_id, alias_text, language) DO NOTHING "
                "RETURNING id, (xmax = 0) AS inserted_flag"
            ), {"sid": sup, "at": at})).mappings().first()
            if row is None:
                skipped_r1 += 1
            elif row["inserted_flag"]:
                inserted_r1 += 1
            else:
                skipped_r1 += 1
    assert inserted_r1 == 3, f"Round 1 で 3 件新規挿入されるはず: inserted={inserted_r1}"
    assert skipped_r1 == 0, f"Round 1 では skip 0 のはず: skipped={skipped_r1}"

    # Round 2: 同じ 3 件 + 新規 1 件 = 4 件投入 → 1 inserted / 3 skipped
    aliases_r2 = list(aliases) + ["TEST_F1_FIX_DELTA"]
    inserted_r2 = 0
    skipped_r2 = 0
    async with engine.begin() as conn:
        for at in aliases_r2:
            row = (await conn.execute(text(
                "INSERT INTO public.supplier_aliases "
                "(supplier_id, alias_text, language, source) "
                "VALUES (:sid, :at, 'ja', 'manual') "
                "ON CONFLICT (supplier_id, alias_text, language) DO NOTHING "
                "RETURNING id, (xmax = 0) AS inserted_flag"
            ), {"sid": sup, "at": at})).mappings().first()
            if row is None:
                skipped_r2 += 1
            elif row["inserted_flag"]:
                inserted_r2 += 1
            else:
                skipped_r2 += 1
    assert inserted_r2 == 1, (
        f"Round 2 では DELTA 1 件だけ新規のはず: inserted={inserted_r2}"
    )
    assert skipped_r2 == 3, (
        f"Round 2 では ALPHA/BRAVO/CHARLIE の 3 件がスキップされるはず: "
        f"skipped={skipped_r2}"
    )

    # cleanup
    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM public.supplier_aliases WHERE alias_text = ANY(:as)"),
            {"as": aliases_r2},
        )


async def test_supplier_aliases_different_language_allowed(engine):
    """同じ alias_text でも language が異なれば許容される（en 版と ja 版を共存）。"""
    from sqlalchemy import text

    async with engine.connect() as conn:
        exists = (await conn.execute(text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name='supplier_aliases'"
        ))).scalar_one_or_none()
    if not exists:
        pytest.skip("public.supplier_aliases 未作成")

    async with engine.connect() as conn:
        sup = (await conn.execute(text(
            "SELECT id FROM public.suppliers WHERE is_active = TRUE LIMIT 1"
        ))).scalar_one_or_none()
    if not sup:
        pytest.skip("public.suppliers が空")

    test_alias = "TEST_AC2_LANG_SPLIT"

    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM public.supplier_aliases WHERE alias_text = :a"),
            {"a": test_alias},
        )

    async with engine.begin() as conn:
        await conn.execute(text("""
            INSERT INTO public.supplier_aliases
                (supplier_id, alias_text, language, source)
            VALUES (:sid, :alias, 'ja', 'manual')
        """), {"sid": sup, "alias": test_alias})
        # 同じ alias、 en 版は OK
        await conn.execute(text("""
            INSERT INTO public.supplier_aliases
                (supplier_id, alias_text, language, source)
            VALUES (:sid, :alias, 'en', 'manual')
        """), {"sid": sup, "alias": test_alias})

    async with engine.connect() as conn:
        cnt = (await conn.execute(
            text("SELECT COUNT(*) FROM public.supplier_aliases WHERE alias_text = :a"),
            {"a": test_alias},
        )).scalar_one()
    assert cnt == 2, "ja と en が両方挿入されているはず"

    # cleanup
    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM public.supplier_aliases WHERE alias_text = :a"),
            {"a": test_alias},
        )
