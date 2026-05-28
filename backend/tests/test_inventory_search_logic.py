"""Sprint 7 (F7) 検索ロジックの純 Python ユニットテスト (DB 不要)。

実 Postgres を必要としない単純な構造テストで、CI / ローカル両方で常に走る。

カバー範囲:
  - _tokenize の挙動 (whitespace 分割 / 重複除去 / MAX_TOKENS / MAX_QUERY_LEN)
  - build_search_sql が CTE / UNION ALL / score 列を含むことを文字列レベルで確認
  - InventorySearchResponse schema の往復 (masked / stock_quantity None / matched_via)

実 PG 必須なテスト (token 横断 / ranking / visibility 効果) は
test_inventory_search.py 側で TEST_PG_URL 環境下のみ走らせる。
"""
from __future__ import annotations

import pytest

from app.services.inventory_search import (
    MAX_QUERY_LEN,
    MAX_TOKENS,
    _tokenize,
    build_search_sql,
)
from app.schemas.inventory_search import (
    InventorySearchCandidate,
    InventorySearchResponse,
)


class TestTokenize:
    def test_empty(self):
        assert _tokenize("") == []
        assert _tokenize("   ") == []

    def test_basic_split(self):
        assert _tokenize("リザードン SV1a") == ["リザードン", "SV1a"]

    def test_dedup_case_insensitive(self):
        # 同一 token は 1 つに
        tokens = _tokenize("SV1a sv1a SV1A")
        assert len(tokens) == 1

    def test_max_tokens(self):
        many = " ".join(f"t{i}" for i in range(MAX_TOKENS + 5))
        assert len(_tokenize(many)) == MAX_TOKENS

    def test_max_query_len(self):
        # 超長クエリは切り詰めれる (truncate)
        big = "a" * (MAX_QUERY_LEN + 50)
        result = _tokenize(big)
        # 1 トークン化されるが、token の長さは MAX_QUERY_LEN 以内
        assert len(result) <= MAX_TOKENS
        if result:
            assert len(result[0]) <= MAX_QUERY_LEN


class TestBuildSearchSql:
    def test_contains_seven_ctes(self):
        params: dict = {}
        sql = build_search_sql(["リザードン", "SV1a"], "and", 20, params)
        # 7 種横断 = m_products / m_card / m_jan / m_exp / m_pokemon / m_trainer / m_tcg / m_alias
        for cte in (
            "m_products",
            "m_card",
            "m_jan",
            "m_exp",
            "m_pokemon",
            "m_trainer",
            "m_tcg",
            "m_alias",
        ):
            assert cte in sql, f"CTE {cte} missing from generated SQL"

    def test_union_all(self):
        params: dict = {}
        sql = build_search_sql(["X"], "or", 5, params)
        # UNION ALL で 7 CTE をまとめる
        assert sql.count("UNION ALL") >= 7

    def test_and_uses_AND_connector(self):
        params: dict = {}
        sql = build_search_sql(["a", "b"], "and", 10, params)
        # AND モードは tokens を AND で繋ぐ
        assert " AND " in sql

    def test_or_uses_OR_connector(self):
        params: dict = {}
        sql = build_search_sql(["a", "b"], "or", 10, params)
        assert " OR " in sql

    def test_score_column_present(self):
        params: dict = {}
        sql = build_search_sql(["a"], "or", 10, params)
        # score 算出 + 在庫 0 ペナルティ (1000)
        assert "score" in sql.lower()
        assert "1000" in sql

    def test_limit_param(self):
        params: dict = {}
        build_search_sql(["a"], "or", 7, params)
        assert params["limit"] == 7

    def test_first_token_lower(self):
        params: dict = {}
        build_search_sql(["SV1a"], "or", 10, params)
        assert params["first_token_lower"] == "sv1a"


class TestSchema:
    def test_response_masked_true_with_none_stock(self):
        cand = InventorySearchCandidate(
            product_id=1,
            name="リザードン",
            name_en="Charizard",
            product_code="P1",
            expansion_code="SV1a",
            card_number="SV1a-001",
            jan_code=None,
            unit_price=1500.0,
            stock_quantity=None,  # masked
            supplier_default_id=10,
            supplier_name="某仕入元",
            image_url=None,
            matched_via="products_name",
            score=13.0,
        )
        resp = InventorySearchResponse(
            query="リザードン",
            op="or",
            total=1,
            masked=True,
            candidates=[cand],
        )
        dumped = resp.model_dump()
        assert dumped["masked"] is True
        assert dumped["candidates"][0]["stock_quantity"] is None

    def test_response_unmasked_with_stock(self):
        cand = InventorySearchCandidate(
            product_id=2,
            name="ピカチュウ",
            name_en="Pikachu",
            product_code=None,
            expansion_code=None,
            card_number=None,
            jan_code=None,
            unit_price=1200.0,
            stock_quantity=5,
            supplier_default_id=None,
            supplier_name=None,
            image_url=None,
            matched_via="products_name",
            score=13.0,
        )
        resp = InventorySearchResponse(
            query="ピカチュウ", op="or", total=1, masked=False, candidates=[cand]
        )
        assert resp.candidates[0].stock_quantity == 5


class TestEndpointSmoke:
    """Endpoint の存在 / 403 / 空クエリ動作の smoke。

    実 PG seed なしでも動かすため、tenant=999 / mock_user の場合の動作:
      - 空クエリ → 200 + total=0
      - q="x" → 200 + total=0 (DB に products なし)
      - 認証/権限の wiring が壊れていないこと
    """

    @pytest.mark.asyncio
    async def test_empty_query_returns_zero(self, client):
        resp = await client.get("/api/v1/inventory/search?q=")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["candidates"] == []
        # QA r7 (2026-05-28 しんごさん確定): 在庫は全テナント共通で見える。
        # マスク機能は撤廃され、masked は権限に関わらず常に False。
        assert data["masked"] is False

    @pytest.mark.asyncio
    async def test_op_validation(self, client):
        # op は and / or のみ許容
        resp = await client.get("/api/v1/inventory/search?q=test&op=xor")
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_lang_validation(self, client):
        resp = await client.get("/api/v1/inventory/search?q=test&lang=fr")
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_limit_validation(self, client):
        # limit > MAX_LIMIT
        resp = await client.get("/api/v1/inventory/search?q=test&limit=999")
        assert resp.status_code == 422
