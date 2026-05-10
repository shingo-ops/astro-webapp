"""ADR-021 Phase 4 / Sprint 4 — 受注仕入情報 API のテスト。

検証対象:
  - POST   /orders/{id}/purchase
  - GET    /orders/{id}/purchase
  - PATCH  /orders/{id}/purchase
  - DELETE /orders/{id}/purchase
  - PATCH  /orders/{id}/purchase/status
  - GET    /purchase/by-supplier?supplier_name=...&page=&per_page=&sort_by=&sort_order=

導出フィールド (`total_with_shipping`) と、確定ショートカット / 仕入元別履歴の
partial match 検索 / ホワイトリスト sort も併せて検証する。
"""

from __future__ import annotations


async def _create_company_contact(client, company_name="仕入テスト顧客"):
    co = await client.post("/api/v1/companies", json={"name": company_name})
    company_id = co.json()["id"]
    ct = await client.post("/api/v1/contacts", json={
        "company_id": company_id,
        "display_name": f"{company_name}の担当",
    })
    return company_id, ct.json()["id"]


async def _create_order(client, order_number="ORD-PUR-1"):
    company_id, contact_id = await _create_company_contact(client, f"Co-{order_number}")
    res = await client.post("/api/v1/orders", json={
        "company_id": company_id,
        "contact_id": contact_id,
        "order_number": order_number,
    })
    assert res.status_code == 201, res.text
    return res.json()["id"]


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


class TestCreatePurchase:
    async def test_create_purchase_for_order(self, client):
        """仕入情報を新規作成できる + 各カラムが保存される + 導出列を含む"""
        order_id = await _create_order(client, "ORD-PUR-CREATE-1")
        res = await client.post(
            f"/api/v1/orders/{order_id}/purchase",
            json={
                "purchase_staff": "山田 太郎",
                "purchase_date": "2026-05-01",
                "transaction_no": "TX-001",
                "supplier_name": "アルファ仕入元",
                "supplier_url": "https://alpha-supplier.example.com",
                "purchase_amount": 1500,
                "purchase_quantity": 10,
                "purchase_total": 15000,
                "purchase_shipping": 2000,
                "carrier_name": "ヤマト",
                "waybill_no": "W-998877",
                "purchase_note": "サンプル仕入",
            },
        )
        assert res.status_code == 201, res.text
        body = res.json()
        assert body["order_id"] == order_id
        assert body["purchase_staff"] == "山田 太郎"
        assert body["supplier_name"] == "アルファ仕入元"
        assert body["transaction_no"] == "TX-001"
        assert float(body["purchase_amount"]) == 1500.0
        assert body["purchase_quantity"] == 10
        assert float(body["purchase_total"]) == 15000.0
        assert float(body["purchase_shipping"]) == 2000.0
        # 導出: total_with_shipping = purchase_total + purchase_shipping
        assert float(body["total_with_shipping"]) == 17000.0
        # ステータスのデフォルトは "" (確認中)
        assert body["purchase_status"] == ""

    async def test_create_purchase_minimal_body(self, client):
        """body 空でも作成できる（全カラム optional のため）"""
        order_id = await _create_order(client, "ORD-PUR-CREATE-EMPTY")
        res = await client.post(f"/api/v1/orders/{order_id}/purchase", json={})
        assert res.status_code == 201, res.text
        body = res.json()
        assert body["order_id"] == order_id
        assert body["supplier_name"] is None
        assert body["purchase_status"] == ""
        # 数値は DB DEFAULT 0
        assert float(body["total_with_shipping"]) == 0.0

    async def test_create_purchase_duplicate_returns_409(self, client):
        """同一 order_id で 2 回 POST すると 409"""
        order_id = await _create_order(client, "ORD-PUR-DUP")
        first = await client.post(
            f"/api/v1/orders/{order_id}/purchase",
            json={"supplier_name": "A"},
        )
        assert first.status_code == 201
        second = await client.post(
            f"/api/v1/orders/{order_id}/purchase",
            json={"supplier_name": "B"},
        )
        assert second.status_code == 409

    async def test_create_purchase_unknown_order_returns_404(self, client):
        """存在しない order_id だと 404"""
        res = await client.post(
            "/api/v1/orders/999999/purchase",
            json={"supplier_name": "X"},
        )
        assert res.status_code == 404

    async def test_create_purchase_invalid_status_returns_422(self, client):
        """purchase_status が enum 外なら 422（Pydantic Literal で弾かれる）"""
        order_id = await _create_order(client, "ORD-PUR-BADSTAT")
        res = await client.post(
            f"/api/v1/orders/{order_id}/purchase",
            json={"purchase_status": "approved"},
        )
        assert res.status_code == 422

    async def test_create_purchase_negative_amount_returns_422(self, client):
        """負の金額は 422"""
        order_id = await _create_order(client, "ORD-PUR-NEG")
        res = await client.post(
            f"/api/v1/orders/{order_id}/purchase",
            json={"purchase_total": -1.0},
        )
        assert res.status_code == 422

    async def test_create_purchase_negative_quantity_returns_422(self, client):
        """負の数量は 422"""
        order_id = await _create_order(client, "ORD-PUR-NEGQ")
        res = await client.post(
            f"/api/v1/orders/{order_id}/purchase",
            json={"purchase_quantity": -1},
        )
        assert res.status_code == 422


class TestGetPurchase:
    async def test_get_purchase(self, client):
        order_id = await _create_order(client, "ORD-PUR-GET-1")
        await client.post(
            f"/api/v1/orders/{order_id}/purchase",
            json={"supplier_name": "Alice Supplier"},
        )
        res = await client.get(f"/api/v1/orders/{order_id}/purchase")
        assert res.status_code == 200
        body = res.json()
        assert body["supplier_name"] == "Alice Supplier"

    async def test_get_purchase_not_found(self, client):
        order_id = await _create_order(client, "ORD-PUR-GET-404")
        res = await client.get(f"/api/v1/orders/{order_id}/purchase")
        assert res.status_code == 404


class TestPatchPurchase:
    async def test_patch_purchase_partial(self, client):
        order_id = await _create_order(client, "ORD-PUR-PATCH-1")
        await client.post(
            f"/api/v1/orders/{order_id}/purchase",
            json={"supplier_name": "Old Supplier", "purchase_total": 1000},
        )
        res = await client.patch(
            f"/api/v1/orders/{order_id}/purchase",
            json={"purchase_total": 2500},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["supplier_name"] == "Old Supplier"  # 据え置き
        assert float(body["purchase_total"]) == 2500.0
        # 導出列が再計算される
        assert float(body["total_with_shipping"]) == 2500.0

    async def test_patch_purchase_clear_with_null(self, client):
        """明示的に null を渡すとフィールドがクリアされる"""
        order_id = await _create_order(client, "ORD-PUR-PATCH-NULL")
        await client.post(
            f"/api/v1/orders/{order_id}/purchase",
            json={"transaction_no": "TX-OLD"},
        )
        res = await client.patch(
            f"/api/v1/orders/{order_id}/purchase",
            json={"transaction_no": None},
        )
        assert res.status_code == 200
        assert res.json()["transaction_no"] is None

    async def test_patch_purchase_not_found(self, client):
        order_id = await _create_order(client, "ORD-PUR-PATCH-404")
        res = await client.patch(
            f"/api/v1/orders/{order_id}/purchase",
            json={"supplier_name": "X"},
        )
        assert res.status_code == 404

    async def test_patch_purchase_empty_body_400(self, client):
        order_id = await _create_order(client, "ORD-PUR-PATCH-EMPTY")
        await client.post(
            f"/api/v1/orders/{order_id}/purchase",
            json={"supplier_name": "X"},
        )
        res = await client.patch(f"/api/v1/orders/{order_id}/purchase", json={})
        assert res.status_code == 400


class TestDeletePurchase:
    async def test_delete_purchase(self, client):
        order_id = await _create_order(client, "ORD-PUR-DEL")
        await client.post(
            f"/api/v1/orders/{order_id}/purchase",
            json={"supplier_name": "X"},
        )
        res = await client.delete(f"/api/v1/orders/{order_id}/purchase")
        assert res.status_code == 204
        res2 = await client.get(f"/api/v1/orders/{order_id}/purchase")
        assert res2.status_code == 404

    async def test_delete_purchase_not_found(self, client):
        order_id = await _create_order(client, "ORD-PUR-DEL-404")
        res = await client.delete(f"/api/v1/orders/{order_id}/purchase")
        assert res.status_code == 404

    async def test_cascade_on_order_delete(self, client):
        """受注本体を消すと仕入情報も CASCADE で消える"""
        order_id = await _create_order(client, "ORD-PUR-CASC")
        await client.post(
            f"/api/v1/orders/{order_id}/purchase",
            json={"supplier_name": "X"},
        )
        del_order = await client.delete(f"/api/v1/orders/{order_id}")
        assert del_order.status_code == 204
        res = await client.get(f"/api/v1/orders/{order_id}/purchase")
        assert res.status_code == 404


# ---------------------------------------------------------------------------
# 確定ショートカット
# ---------------------------------------------------------------------------


class TestStatusShortcut:
    async def test_status_shortcut_default_confirmed(self, client):
        """body 省略時は 'confirmed' に切り替わる"""
        order_id = await _create_order(client, "ORD-PUR-STAT-1")
        await client.post(
            f"/api/v1/orders/{order_id}/purchase",
            json={"supplier_name": "X"},
        )
        res = await client.patch(f"/api/v1/orders/{order_id}/purchase/status")
        assert res.status_code == 200
        body = res.json()
        assert body["purchase_status"] == "confirmed"

    async def test_status_shortcut_explicit_revert(self, client):
        """status='' を明示すると確認中に戻る"""
        order_id = await _create_order(client, "ORD-PUR-STAT-REVERT")
        await client.post(
            f"/api/v1/orders/{order_id}/purchase",
            json={"supplier_name": "X", "purchase_status": "confirmed"},
        )
        res = await client.patch(
            f"/api/v1/orders/{order_id}/purchase/status",
            json={"status": ""},
        )
        assert res.status_code == 200
        assert res.json()["purchase_status"] == ""

    async def test_status_shortcut_invalid_returns_422(self, client):
        """status が enum 外なら 422"""
        order_id = await _create_order(client, "ORD-PUR-STAT-BAD")
        await client.post(
            f"/api/v1/orders/{order_id}/purchase",
            json={"supplier_name": "X"},
        )
        res = await client.patch(
            f"/api/v1/orders/{order_id}/purchase/status",
            json={"status": "in_progress"},
        )
        assert res.status_code == 422

    async def test_status_shortcut_not_found(self, client):
        order_id = await _create_order(client, "ORD-PUR-STAT-404")
        res = await client.patch(f"/api/v1/orders/{order_id}/purchase/status")
        assert res.status_code == 404


# ---------------------------------------------------------------------------
# 仕入元別履歴
# ---------------------------------------------------------------------------


class TestBySupplier:
    async def _seed_three(self, client):
        oid1 = await _create_order(client, "ORD-PUR-SUP-1")
        oid2 = await _create_order(client, "ORD-PUR-SUP-2")
        oid3 = await _create_order(client, "ORD-PUR-SUP-3")
        await client.post(
            f"/api/v1/orders/{oid1}/purchase",
            json={"supplier_name": "Alpha Trading", "purchase_total": 5000},
        )
        await client.post(
            f"/api/v1/orders/{oid2}/purchase",
            json={"supplier_name": "Alpha Logistics", "purchase_total": 8000},
        )
        await client.post(
            f"/api/v1/orders/{oid3}/purchase",
            json={"supplier_name": "Beta Co.", "purchase_total": 3000},
        )
        return [oid1, oid2, oid3]

    async def test_by_supplier_partial_match(self, client):
        """supplier_name の部分一致でフィルタ"""
        await self._seed_three(client)
        res = await client.get("/api/v1/purchase/by-supplier?supplier_name=Alpha")
        assert res.status_code == 200
        body = res.json()
        assert body["total"] == 2
        names = sorted(item["supplier_name"] for item in body["items"])
        assert names == ["Alpha Logistics", "Alpha Trading"]

    async def test_by_supplier_no_filter_returns_all(self, client):
        """supplier_name 未指定なら全件返す（テナント単位）"""
        await self._seed_three(client)
        res = await client.get("/api/v1/purchase/by-supplier")
        assert res.status_code == 200
        body = res.json()
        assert body["total"] == 3

    async def test_by_supplier_returns_order_number(self, client):
        """order_number が JOIN で返る"""
        ids = await self._seed_three(client)
        res = await client.get("/api/v1/purchase/by-supplier?supplier_name=Beta")
        assert res.status_code == 200
        items = res.json()["items"]
        assert len(items) == 1
        assert items[0]["order_id"] == ids[2]
        assert items[0]["order_number"] == "ORD-PUR-SUP-3"

    async def test_by_supplier_pagination(self, client):
        """per_page / page でページング"""
        await self._seed_three(client)
        res = await client.get(
            "/api/v1/purchase/by-supplier?per_page=2&page=1"
        )
        assert res.status_code == 200
        body = res.json()
        assert body["total"] == 3
        assert len(body["items"]) == 2
        assert body["per_page"] == 2
        assert body["page"] == 1
        # page=2 で残り 1 件
        res2 = await client.get(
            "/api/v1/purchase/by-supplier?per_page=2&page=2"
        )
        assert res2.status_code == 200
        body2 = res2.json()
        assert len(body2["items"]) == 1

    async def test_by_supplier_sort_whitelist_rejects_unknown(self, client):
        """ホワイトリスト外の sort_by は 400"""
        res = await client.get(
            "/api/v1/purchase/by-supplier?sort_by=hacked_column"
        )
        assert res.status_code == 400

    async def test_by_supplier_sort_invalid_order_returns_400(self, client):
        res = await client.get(
            "/api/v1/purchase/by-supplier?sort_order=sideways"
        )
        assert res.status_code == 400

    async def test_by_supplier_sort_by_total_desc(self, client):
        """sort_by=purchase_total + desc で金額降順"""
        await self._seed_three(client)
        res = await client.get(
            "/api/v1/purchase/by-supplier?sort_by=purchase_total&sort_order=desc"
        )
        assert res.status_code == 200
        items = res.json()["items"]
        totals = [float(item["purchase_total"] or 0) for item in items]
        assert totals == sorted(totals, reverse=True)

    async def test_by_supplier_like_metachars_escaped(self, client):
        """LIKE の % / _ がメタとして扱われずエスケープされる"""
        oid = await _create_order(client, "ORD-PUR-LIKE")
        await client.post(
            f"/api/v1/orders/{oid}/purchase",
            json={"supplier_name": "100%Genuine"},
        )
        # "%"" を直接渡す = エスケープ前なら全件 hit してしまう想定。
        # サニタイズされていれば、"%"" 単体ではマッチしない（リテラル % を探す）。
        res = await client.get("/api/v1/purchase/by-supplier?supplier_name=%25")
        assert res.status_code == 200
        body = res.json()
        # "100%Genuine" にはリテラル % が含まれるので hit する
        assert body["total"] == 1


# ---------------------------------------------------------------------------
# 権限・テナント分離
# ---------------------------------------------------------------------------


class TestPermissions:
    """ADR-021 Sprint 4 / AC-4.5: 権限・テナント分離

    SQLite テスト基盤では物理的なテナント分離は再現できないが、
    require_permission(orders.view / orders.update) が依存に残ることを
    確認する（権限なしユーザーは 403）。
    """

    async def test_get_purchase_requires_orders_view(self, client):
        from unittest.mock import patch

        async def _no_perms(db, tenant_id, user_id):
            return set()

        order_id = await _create_order(client, "ORD-PUR-PERM-GET")
        with patch("app.auth.dependencies.load_user_permissions", _no_perms):
            res = await client.get(f"/api/v1/orders/{order_id}/purchase")
        assert res.status_code == 403

    async def test_create_purchase_requires_orders_update(self, client):
        from unittest.mock import patch

        async def _no_perms(db, tenant_id, user_id):
            return set()

        order_id = await _create_order(client, "ORD-PUR-PERM-POST")
        with patch("app.auth.dependencies.load_user_permissions", _no_perms):
            res = await client.post(
                f"/api/v1/orders/{order_id}/purchase",
                json={"supplier_name": "X"},
            )
        assert res.status_code == 403

    async def test_status_shortcut_requires_orders_update(self, client):
        from unittest.mock import patch

        async def _no_perms(db, tenant_id, user_id):
            return set()

        order_id = await _create_order(client, "ORD-PUR-PERM-STAT")
        with patch("app.auth.dependencies.load_user_permissions", _no_perms):
            res = await client.patch(f"/api/v1/orders/{order_id}/purchase/status")
        assert res.status_code == 403

    async def test_by_supplier_requires_orders_view(self, client):
        from unittest.mock import patch

        async def _no_perms(db, tenant_id, user_id):
            return set()

        with patch("app.auth.dependencies.load_user_permissions", _no_perms):
            res = await client.get("/api/v1/purchase/by-supplier?supplier_name=Alpha")
        assert res.status_code == 403
