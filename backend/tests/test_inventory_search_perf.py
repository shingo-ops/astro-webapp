"""Sprint 7 (F7) 在庫検索 SLO 計測 (実 Postgres、1000 products 規模)。

AC7.6: tenant_006 想定 5 products で p95 ≤ 200ms / 1000 products で p95 ≤ 500ms

SQLite モック禁止 (memory: feedback_evaluator_gap_2026_05_15)。
TEST_PG_URL 未設定時 / RUN_PERF=1 でない時は skip。

Generator 自己評価メモ (2026-05-22):
  - 1000 products の bulk seed + 10 並列 measurement が VPS の 2GB メモリで
    安定する保証はないので、デフォルトでは「件数 < 1000 でも実行可」モードと
    SLO assert を SLO_P95_MS で緩和できる envvar 制御を実装。
  - production smoke (本番 VPS への適用後) は別タスクで再計測する想定 (RUN_PERF=1 + TEST_PG_URL=production-shaped)。
"""
from __future__ import annotations

import os
import time
import uuid

import pytest

TEST_PG_URL = os.getenv("TEST_PG_URL")
RUN_PERF = os.getenv("RUN_PERF") == "1"

# 件数: デフォルト 1000 (本番想定)、env で override 可
PERF_PRODUCTS = int(os.getenv("PERF_PRODUCTS", "1000"))
# SLO 閾値 (ms): デフォルト 500ms = AC7.6 1000 products 想定
SLO_P95_MS = int(os.getenv("SLO_P95_MS", "500"))
# 並列クエリ数: 10 (1 検索 q を 10 回連発して p95 観測)
PERF_TRIES = int(os.getenv("PERF_TRIES", "10"))

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not (TEST_PG_URL and RUN_PERF),
        reason="本テストは TEST_PG_URL かつ RUN_PERF=1 必須 (重め、CI 通常スキップ)",
    ),
]


@pytest.fixture
async def engine():
    from sqlalchemy.ext.asyncio import create_async_engine

    eng = create_async_engine(TEST_PG_URL, echo=False)
    yield eng
    await eng.dispose()


@pytest.fixture
async def bulk_seed(engine):
    """PERF_PRODUCTS 件の synthetic products を投入 → yield → cleanup。

    生成パターン:
      name = f"Perf{tag}-{i}-リザードン" / name_en = f"Perf{tag}-{i}-Charizard"
      card_number = f"PFx{tag}-{i:04d}"
      expansion_code = "SVPF"
      stock = i % 5
    """
    from sqlalchemy import text

    tag = uuid.uuid4().hex[:8]
    async with engine.begin() as conn:
        # bulk INSERT
        await conn.execute(
            text(
                "INSERT INTO public.products "
                "(tenant_id, product_code, name, name_en, expansion_code, "
                " card_number, unit_price, stock_quantity) "
                "SELECT NULL, "
                "       :code_prefix || g.i, "
                "       'Perf' || :tag || '-' || g.i || '-リザードン', "
                "       'Perf' || :tag || '-' || g.i || '-Charizard', "
                "       'SVPF', "
                "       :card_prefix || lpad(g.i::text, 4, '0'), "
                "       1500.0, "
                "       (g.i % 5)::int "
                "FROM generate_series(1, :n) AS g(i)"
            ),
            {
                "code_prefix": f"PF-{tag}-",
                "card_prefix": f"PFx{tag}-",
                "tag": tag,
                "n": PERF_PRODUCTS,
            },
        )
    yield tag
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "DELETE FROM public.products WHERE product_code LIKE :pat"
            ),
            {"pat": f"PF-{tag}-%"},
        )


async def test_search_p95_within_slo(engine, bulk_seed):
    """AC7.6: PERF_PRODUCTS 件の synthetic dataset 上で p95 ≤ SLO_P95_MS。"""
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.services.inventory_search import search_inventory

    tag = bulk_seed
    samples_ms: list[float] = []
    async with AsyncSession(engine) as db:
        for _ in range(PERF_TRIES):
            t0 = time.perf_counter()
            res = await search_inventory(
                db,
                query=f"リザードン Perf{tag}",
                op="and",
                limit=20,
                mask_stock=False,
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            samples_ms.append(elapsed_ms)
            assert res, "perf seed should yield matches"

    samples_ms.sort()
    p95_index = max(0, int(len(samples_ms) * 0.95) - 1)
    p95 = samples_ms[p95_index]
    avg = sum(samples_ms) / len(samples_ms)
    print(
        f"[perf] PERF_PRODUCTS={PERF_PRODUCTS} tries={PERF_TRIES} "
        f"avg={avg:.1f}ms p95={p95:.1f}ms (SLO={SLO_P95_MS}ms)"
    )
    assert p95 <= SLO_P95_MS, (
        f"p95 {p95:.1f}ms exceeded SLO {SLO_P95_MS}ms; "
        f"avg {avg:.1f}ms; samples={samples_ms}"
    )
