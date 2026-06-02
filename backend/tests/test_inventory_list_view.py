"""ADR-093 Phase 2: 在庫表ビュー GET /inventory のバリデーションテスト。

スコープ:
  - クエリパラメータ (sort / order / page / per_page) の 422 バリデーション

データ正しさ (status='in_stock' / 18h 失効 / JOIN 結果) は public.inventory が
SQLite に存在しないため実 PostgreSQL での E2E (Playwright) で検証する設計。
本ファイルは DB アクセス前に short-circuit する param 検証経路に限定する
(memory: feedback_evaluator_gap_2026_05_15 / test_inventory_offers_rbac と同方針)。
"""


class TestInventoryViewValidation:
    """GET /inventory のクエリパラメータ検証 (DB アクセス前に 422)。"""

    async def test_invalid_order_returns_422(self, client):
        """order は asc/desc のみ。それ以外は 422。"""
        res = await client.get("/api/v1/inventory", params={"order": "sideways"})
        assert res.status_code == 422

    async def test_invalid_sort_returns_422(self, client):
        """sort は name のみ許可。それ以外は 422。"""
        res = await client.get("/api/v1/inventory", params={"sort": "price"})
        assert res.status_code == 422

    async def test_page_zero_returns_422(self, client):
        """page は 1 以上。0 は 422。"""
        res = await client.get("/api/v1/inventory", params={"page": 0})
        assert res.status_code == 422

    async def test_per_page_too_large_returns_422(self, client):
        """per_page は最大 200。超過は 422。"""
        res = await client.get("/api/v1/inventory", params={"per_page": 999})
        assert res.status_code == 422

    async def test_invalid_offer_type_returns_422(self, client):
        """offer_type は in_stock/pre_order のみ（ADR-093 Phase 3）。それ以外は 422。"""
        res = await client.get("/api/v1/inventory", params={"offer_type": "bogus"})
        assert res.status_code == 422
