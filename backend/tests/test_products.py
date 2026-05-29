"""
商品・在庫管理API（products）のテスト

対象:
  - GET /products (一覧・検索・アーカイブフィルタ)
  - POST /products (作成)
  - GET /products/{id} (詳細)
  - PATCH /products/{id} (更新・アーカイブ)
  - DELETE /products/{id} (物理削除・FK参照時 409)
  - GET /products/{id}/check-inventory (在庫確認)
  - image_url バリデーション（http/https のみ）
"""

import pytest


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

class TestProductsCRUD:
    """商品の基本 CRUD"""

    async def test_create_product(self, client):
        """商品を新規作成できる"""
        res = await client.post("/api/v1/products", json={
            "name_ja": "テスト商品",
            "name_en": "Test Product",
            "category": "TCG",
            "unit_price": "1500.00",
            "quantity": 10,
        })
        assert res.status_code == 201
        data = res.json()
        assert data["name_ja"] == "テスト商品"
        assert data["name_en"] == "Test Product"
        assert data["category"] == "TCG"
        assert data["product_code"].startswith("PD-")
        assert data["is_archived"] is False

    async def test_create_product_minimal(self, client):
        """name_ja のみで作成できる（最小リクエスト）"""
        res = await client.post("/api/v1/products", json={"name_ja": "最小商品"})
        assert res.status_code == 201
        data = res.json()
        assert data["name_ja"] == "最小商品"
        assert data["quantity"] == 0
        assert data["status"] == "active"

    async def test_list_products(self, client):
        """商品一覧を取得できる"""
        await client.post("/api/v1/products", json={"name_ja": "一覧テスト商品1"})
        await client.post("/api/v1/products", json={"name_ja": "一覧テスト商品2"})

        res = await client.get("/api/v1/products")
        assert res.status_code == 200
        assert len(res.json()) >= 2

    async def test_list_products_filter_by_category(self, client):
        """category でフィルタリングできる"""
        await client.post("/api/v1/products", json={
            "name_ja": "カテゴリA商品", "category": "TCG",
        })
        await client.post("/api/v1/products", json={
            "name_ja": "カテゴリB商品", "category": "Figure",
        })

        res = await client.get("/api/v1/products", params={"category": "TCG"})
        assert res.status_code == 200
        assert all(p["category"] == "TCG" for p in res.json())

    async def test_list_products_search_by_name(self, client):
        """search で name_ja 部分一致できる"""
        await client.post("/api/v1/products", json={"name_ja": "ピカチュウカード"})
        await client.post("/api/v1/products", json={"name_ja": "リザードンカード"})

        res = await client.get("/api/v1/products", params={"search": "ピカチュウ"})
        assert res.status_code == 200
        names = [p["name_ja"] for p in res.json()]
        assert "ピカチュウカード" in names
        assert "リザードンカード" not in names

    async def test_list_products_search_by_category(self, client):
        """search で category も部分一致できる"""
        await client.post("/api/v1/products", json={
            "name_ja": "検索商品X", "category": "Pokemon TCG",
        })
        res = await client.get("/api/v1/products", params={"search": "Pokemon"})
        assert res.status_code == 200
        assert any(p["name_ja"] == "検索商品X" for p in res.json())

    async def test_get_product(self, client):
        """商品詳細を取得できる"""
        create_res = await client.post("/api/v1/products", json={
            "name_ja": "詳細テスト商品",
        })
        product_id = create_res.json()["id"]

        res = await client.get(f"/api/v1/products/{product_id}")
        assert res.status_code == 200
        assert res.json()["id"] == product_id

    async def test_get_product_not_found(self, client):
        """存在しない商品IDは 404"""
        res = await client.get("/api/v1/products/99999")
        assert res.status_code == 404

    async def test_update_product(self, client):
        """商品を更新できる"""
        create_res = await client.post("/api/v1/products", json={"name_ja": "更新前"})
        product_id = create_res.json()["id"]

        res = await client.patch(f"/api/v1/products/{product_id}", json={
            "name_ja": "更新後",
            "quantity": 50,
            "unit_price": "2000.00",
        })
        assert res.status_code == 200
        data = res.json()
        assert data["name_ja"] == "更新後"
        assert data["quantity"] == 50
        assert float(data["unit_price"]) == 2000.0

    async def test_update_product_not_found(self, client):
        """存在しない商品の更新は 404"""
        res = await client.patch("/api/v1/products/99999", json={"quantity": 10})
        assert res.status_code == 404

    async def test_update_product_no_fields_returns_400(self, client):
        """更新フィールドなしは 400"""
        create_res = await client.post("/api/v1/products", json={"name_ja": "フィールドなし"})
        product_id = create_res.json()["id"]

        res = await client.patch(f"/api/v1/products/{product_id}", json={})
        assert res.status_code == 400

    async def test_delete_product(self, client):
        """FK 参照のない商品を物理削除できる"""
        create_res = await client.post("/api/v1/products", json={"name_ja": "削除テスト"})
        product_id = create_res.json()["id"]

        res = await client.delete(f"/api/v1/products/{product_id}")
        assert res.status_code == 204

        res = await client.get(f"/api/v1/products/{product_id}")
        assert res.status_code == 404

    async def test_delete_product_not_found(self, client):
        """存在しない商品の削除は 404"""
        res = await client.delete("/api/v1/products/99999")
        assert res.status_code == 404


# ---------------------------------------------------------------------------
# アーカイブ（論理削除）
# ---------------------------------------------------------------------------

class TestProductsArchive:
    """is_archived フラグと archived_at の自動管理"""

    async def test_archive_sets_archived_at(self, client):
        """is_archived=true にすると archived_at が自動設定される"""
        create_res = await client.post("/api/v1/products", json={"name_ja": "アーカイブ対象"})
        product_id = create_res.json()["id"]

        res = await client.patch(f"/api/v1/products/{product_id}", json={"is_archived": True})
        assert res.status_code == 200
        data = res.json()
        assert data["is_archived"] is True
        assert data["archived_at"] is not None

    async def test_unarchive_clears_archived_at(self, client):
        """is_archived=false に戻すと archived_at が NULL になる"""
        create_res = await client.post("/api/v1/products", json={"name_ja": "復活対象"})
        product_id = create_res.json()["id"]

        await client.patch(f"/api/v1/products/{product_id}", json={"is_archived": True})
        res = await client.patch(f"/api/v1/products/{product_id}", json={"is_archived": False})
        assert res.status_code == 200
        data = res.json()
        assert data["is_archived"] is False
        assert data["archived_at"] is None

    async def test_list_excludes_archived_by_default(self, client):
        """デフォルトではアーカイブ商品が一覧に含まれない"""
        # 通常商品
        await client.post("/api/v1/products", json={"name_ja": "通常商品X"})
        # アーカイブ済み商品
        ar_res = await client.post("/api/v1/products", json={"name_ja": "廃番商品X"})
        ar_id = ar_res.json()["id"]
        await client.patch(f"/api/v1/products/{ar_id}", json={"is_archived": True})

        res = await client.get("/api/v1/products")
        assert res.status_code == 200
        names = [p["name_ja"] for p in res.json()]
        assert "通常商品X" in names
        assert "廃番商品X" not in names

    async def test_list_includes_archived_when_requested(self, client):
        """?archived=true でアーカイブ商品も含まれる"""
        ar_res = await client.post("/api/v1/products", json={"name_ja": "廃番商品Y"})
        ar_id = ar_res.json()["id"]
        await client.patch(f"/api/v1/products/{ar_id}", json={"is_archived": True})

        res = await client.get("/api/v1/products", params={"archived": "true"})
        assert res.status_code == 200
        names = [p["name_ja"] for p in res.json()]
        assert "廃番商品Y" in names


# ---------------------------------------------------------------------------
# 在庫確認
# ---------------------------------------------------------------------------

class TestProductsInventory:
    """check-inventory エンドポイント"""

    async def test_check_inventory_sufficient(self, client):
        """在庫が十分な場合 available=true を返す"""
        create_res = await client.post("/api/v1/products", json={
            "name_ja": "在庫十分商品",
            "quantity": 100,
        })
        product_id = create_res.json()["id"]

        res = await client.get(
            f"/api/v1/products/{product_id}/check-inventory",
            params={"quantity": 50},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["available"] is True
        assert data["current_quantity"] == 100
        assert data["requested_quantity"] == 50

    async def test_check_inventory_insufficient(self, client):
        """在庫不足の場合 available=false を返す"""
        create_res = await client.post("/api/v1/products", json={
            "name_ja": "在庫不足商品",
            "quantity": 5,
        })
        product_id = create_res.json()["id"]

        res = await client.get(
            f"/api/v1/products/{product_id}/check-inventory",
            params={"quantity": 10},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["available"] is False
        assert data["current_quantity"] == 5
        assert data["requested_quantity"] == 10

    async def test_check_inventory_exact_match(self, client):
        """在庫数 = 要求数のときは available=true"""
        create_res = await client.post("/api/v1/products", json={
            "name_ja": "在庫ぴったり商品",
            "quantity": 3,
        })
        product_id = create_res.json()["id"]

        res = await client.get(
            f"/api/v1/products/{product_id}/check-inventory",
            params={"quantity": 3},
        )
        assert res.status_code == 200
        assert res.json()["available"] is True

    async def test_check_inventory_product_not_found(self, client):
        """存在しない商品IDは 404"""
        res = await client.get(
            "/api/v1/products/99999/check-inventory",
            params={"quantity": 1},
        )
        assert res.status_code == 404

    async def test_check_inventory_invalid_quantity(self, client):
        """quantity=0 は 422（ge=1 バリデーション）"""
        create_res = await client.post("/api/v1/products", json={"name_ja": "バリデ商品"})
        product_id = create_res.json()["id"]

        res = await client.get(
            f"/api/v1/products/{product_id}/check-inventory",
            params={"quantity": 0},
        )
        assert res.status_code == 422


# ---------------------------------------------------------------------------
# FK 参照時の削除 409
# ---------------------------------------------------------------------------

class TestProductsDeleteWithFK:
    """下流テーブルから参照されている商品は物理削除できない（409）"""

    async def test_delete_with_quote_item_returns_409(self, client):
        """quote_items から参照されている場合 409"""
        # 商品作成
        p_res = await client.post("/api/v1/products", json={
            "name_ja": "見積参照商品",
            "unit_price": "1000.00",
        })
        product_id = p_res.json()["id"]

        # 会社・担当者・見積もりを作成し、商品IDを明細に使用
        co = await client.post("/api/v1/companies", json={"name": "FK参照テスト会社"})
        company_id = co.json()["id"]
        ct = await client.post("/api/v1/contacts", json={
            "company_id": company_id,
            "display_name": "FK担当者",
        })
        contact_id = ct.json()["id"]

        await client.post("/api/v1/quotes", json={
            "company_id": company_id,
            "contact_id": contact_id,
            "items": [
                {
                    "product_id": product_id,
                    "product_name": "見積参照商品",
                    "quantity": 1,
                    "unit_price": "1000.00",
                },
            ],
        })

        # 削除試み → 409
        res = await client.delete(f"/api/v1/products/{product_id}")
        assert res.status_code == 409
        detail = res.json()["detail"]
        assert "quote_items" in str(detail)

    async def test_delete_with_invoice_item_returns_409(self, client):
        """invoice_items から参照されている場合 409"""
        p_res = await client.post("/api/v1/products", json={
            "name_ja": "請求参照商品",
            "unit_price": "2000.00",
        })
        product_id = p_res.json()["id"]

        co = await client.post("/api/v1/companies", json={"name": "請求FK会社"})
        company_id = co.json()["id"]
        ct = await client.post("/api/v1/contacts", json={
            "company_id": company_id, "display_name": "請求FK担当",
        })
        contact_id = ct.json()["id"]

        await client.post("/api/v1/invoices", json={
            "company_id": company_id,
            "contact_id": contact_id,
            "items": [
                {
                    "product_id": product_id,
                    "product_name": "請求参照商品",
                    "quantity": 1,
                    "unit_price": "2000.00",
                },
            ],
        })

        res = await client.delete(f"/api/v1/products/{product_id}")
        assert res.status_code == 409
        detail = res.json()["detail"]
        assert "invoice_items" in str(detail)

    async def test_delete_without_references_succeeds(self, client):
        """FK 参照なしなら物理削除できる"""
        p_res = await client.post("/api/v1/products", json={"name_ja": "参照なし商品"})
        product_id = p_res.json()["id"]

        res = await client.delete(f"/api/v1/products/{product_id}")
        assert res.status_code == 204


# ---------------------------------------------------------------------------
# バリデーション
# ---------------------------------------------------------------------------

class TestProductsValidation:
    """入力バリデーション"""

    async def test_missing_name_ja(self, client):
        """name_ja なしは 422"""
        res = await client.post("/api/v1/products", json={"name_en": "No Japanese Name"})
        assert res.status_code == 422

    async def test_negative_unit_price(self, client):
        """負の unit_price は 422"""
        res = await client.post("/api/v1/products", json={
            "name_ja": "負の値段商品",
            "unit_price": "-100.00",
        })
        assert res.status_code == 422

    async def test_negative_quantity(self, client):
        """負の quantity は 422"""
        res = await client.post("/api/v1/products", json={
            "name_ja": "負の在庫商品",
            "quantity": -1,
        })
        assert res.status_code == 422

    async def test_invalid_image_url_scheme(self, client):
        """javascript:// スキームの image_url は 422"""
        res = await client.post("/api/v1/products", json={
            "name_ja": "XSSテスト商品",
            "image_url": "javascript://evil.example.com",
        })
        assert res.status_code == 422

    async def test_invalid_image_url_data_scheme(self, client):
        """data: スキームの image_url は 422"""
        res = await client.post("/api/v1/products", json={
            "name_ja": "データスキーム商品",
            "image_url": "data:text/html,<h1>XSS</h1>",
        })
        assert res.status_code == 422

    async def test_valid_image_url_http(self, client):
        """http:// の image_url は許可される"""
        res = await client.post("/api/v1/products", json={
            "name_ja": "HTTP画像商品",
            "image_url": "http://example.com/image.jpg",
        })
        assert res.status_code == 201
        assert res.json()["image_url"] == "http://example.com/image.jpg"

    async def test_valid_image_url_https(self, client):
        """https:// の image_url は許可される"""
        res = await client.post("/api/v1/products", json={
            "name_ja": "HTTPS画像商品",
            "image_url": "https://cdn.example.com/product.png",
        })
        assert res.status_code == 201
        assert res.json()["image_url"] == "https://cdn.example.com/product.png"

    async def test_invalid_status(self, client):
        """不正な status 値は 422"""
        res = await client.post("/api/v1/products", json={
            "name_ja": "不正ステータス商品",
            "status": "invalid_status",
        })
        assert res.status_code == 422

    async def test_phase1c_fields_stored_correctly(self, client):
        """Phase 1-C M-MVP の追加フィールドが保存・取得できる"""
        res = await client.post("/api/v1/products", json={
            "name_ja": "ポケモンカード テスト",
            "category": "Pokemon TCG",
            "jan_code": "4902370549058",
            "card_number": "001/100",
            "expansion_code": "SV01",
            "rarity": "RR",
            "language": "JP",
            "unit_price_usd": "15.99",
            "unit_price_eur": "14.50",
        })
        assert res.status_code == 201
        data = res.json()
        assert data["jan_code"] == "4902370549058"
        assert data["card_number"] == "001/100"
        assert data["expansion_code"] == "SV01"
        assert data["rarity"] == "RR"
        assert data["language"] == "JP"
        assert float(data["unit_price_usd"]) == 15.99
        assert float(data["unit_price_eur"]) == 14.5
