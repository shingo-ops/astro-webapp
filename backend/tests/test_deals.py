"""案件管理API（deals）のテスト"""

import pytest


async def _create_customer(client, name="テスト顧客"):
    """テスト用の顧客を作成するヘルパー（Phase 1 再設計: company_name + 副テーブル）"""
    res = await client.post("/api/v1/customers", json={"company_name": name})
    assert res.status_code == 201
    return res.json()["id"]


class TestDealsCRUD:
    """案件の作成・取得・更新・削除"""

    async def test_create_deal(self, client):
        """案件を新規作成できる"""
        customer_id = await _create_customer(client)
        res = await client.post("/api/v1/deals", json={
            "customer_id": customer_id,
            "title": "大型案件",
            "amount": 1000000,
            "status": "open",
            "notes": "重要案件",
        })
        assert res.status_code == 201
        data = res.json()
        assert data["title"] == "大型案件"
        assert float(data["amount"]) == 1000000.0
        assert data["status"] == "open"
        assert data["customer_id"] == customer_id

    async def test_create_deal_invalid_customer(self, client):
        """存在しない顧客IDで案件作成は404"""
        res = await client.post("/api/v1/deals", json={
            "customer_id": 99999,
            "title": "無効な案件",
        })
        assert res.status_code == 404

    async def test_list_deals(self, client):
        """案件一覧を取得できる"""
        customer_id = await _create_customer(client)
        await client.post("/api/v1/deals", json={"customer_id": customer_id, "title": "案件A"})
        await client.post("/api/v1/deals", json={"customer_id": customer_id, "title": "案件B"})

        res = await client.get("/api/v1/deals")
        assert res.status_code == 200
        assert len(res.json()) >= 2

    async def test_list_deals_filter_by_status(self, client):
        """ステータスでフィルタリングできる"""
        customer_id = await _create_customer(client)
        await client.post("/api/v1/deals", json={
            "customer_id": customer_id, "title": "成約案件", "status": "won",
        })
        await client.post("/api/v1/deals", json={
            "customer_id": customer_id, "title": "進行中案件", "status": "open",
        })

        res = await client.get("/api/v1/deals", params={"status": "won"})
        assert res.status_code == 200
        data = res.json()
        assert all(d["status"] == "won" for d in data)

    async def test_list_deals_filter_by_customer(self, client):
        """顧客IDでフィルタリングできる"""
        cust_a = await _create_customer(client, "顧客A")
        cust_b = await _create_customer(client, "顧客B")
        await client.post("/api/v1/deals", json={"customer_id": cust_a, "title": "Aの案件"})
        await client.post("/api/v1/deals", json={"customer_id": cust_b, "title": "Bの案件"})

        res = await client.get("/api/v1/deals", params={"customer_id": cust_a})
        assert res.status_code == 200
        data = res.json()
        assert all(d["customer_id"] == cust_a for d in data)

    async def test_get_deal(self, client):
        """案件詳細を取得できる"""
        customer_id = await _create_customer(client)
        create_res = await client.post("/api/v1/deals", json={
            "customer_id": customer_id, "title": "詳細テスト案件",
        })
        deal_id = create_res.json()["id"]

        res = await client.get(f"/api/v1/deals/{deal_id}")
        assert res.status_code == 200
        assert res.json()["title"] == "詳細テスト案件"

    async def test_update_deal_status(self, client):
        """案件のステータスを更新できる"""
        customer_id = await _create_customer(client)
        create_res = await client.post("/api/v1/deals", json={
            "customer_id": customer_id, "title": "進行中",
        })
        deal_id = create_res.json()["id"]

        res = await client.patch(f"/api/v1/deals/{deal_id}", json={"status": "won"})
        assert res.status_code == 200
        assert res.json()["status"] == "won"

    async def test_update_deal_with_date_and_amount(self, client):
        """date(expected_close_date)とDecimal(amount)を同時更新できる（asyncpg encoder対策の回帰テスト）"""
        customer_id = await _create_customer(client)
        create_res = await client.post("/api/v1/deals", json={
            "customer_id": customer_id, "title": "日付更新テスト",
        })
        deal_id = create_res.json()["id"]

        res = await client.patch(f"/api/v1/deals/{deal_id}", json={
            "status": "negotiating",
            "amount": 10000,
            "expected_close_date": "2026-04-30",
            "notes": "備考更新",
        })
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "negotiating"
        assert float(body["amount"]) == 10000.0
        assert body["expected_close_date"] == "2026-04-30"
        assert body["notes"] == "備考更新"

    async def test_delete_deal(self, client):
        """案件を削除できる"""
        customer_id = await _create_customer(client)
        create_res = await client.post("/api/v1/deals", json={
            "customer_id": customer_id, "title": "削除案件",
        })
        deal_id = create_res.json()["id"]

        res = await client.delete(f"/api/v1/deals/{deal_id}")
        assert res.status_code == 204

        res = await client.get(f"/api/v1/deals/{deal_id}")
        assert res.status_code == 404

    async def test_delete_deal_with_order_returns_409(self, client):
        """関連注文がある商談は削除できず、409とわかりやすいメッセージを返す"""
        customer_id = await _create_customer(client)
        deal_res = await client.post("/api/v1/deals", json={
            "customer_id": customer_id, "title": "注文紐付け商談",
        })
        deal_id = deal_res.json()["id"]
        await client.post("/api/v1/orders", json={
            "customer_id": customer_id, "deal_id": deal_id, "order_number": "ORD-FK-TEST",
        })

        res = await client.delete(f"/api/v1/deals/{deal_id}")
        assert res.status_code == 409
        assert "注文" in res.json()["detail"]


class TestDealsValidation:
    """案件バリデーション"""

    async def test_create_without_title(self, client):
        """タイトルなしは422"""
        customer_id = await _create_customer(client)
        res = await client.post("/api/v1/deals", json={"customer_id": customer_id})
        assert res.status_code == 422

    async def test_create_without_customer_id(self, client):
        """顧客IDなしは422"""
        res = await client.post("/api/v1/deals", json={"title": "顧客なし案件"})
        assert res.status_code == 422

    async def test_invalid_status(self, client):
        """無効なステータスは422"""
        customer_id = await _create_customer(client)
        res = await client.post("/api/v1/deals", json={
            "customer_id": customer_id, "title": "無効ステータス", "status": "invalid",
        })
        assert res.status_code == 422

    async def test_negative_amount(self, client):
        """負の金額は422"""
        customer_id = await _create_customer(client)
        res = await client.post("/api/v1/deals", json={
            "customer_id": customer_id, "title": "負の金額", "amount": -100,
        })
        assert res.status_code == 422
