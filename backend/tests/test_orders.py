"""注文管理API（orders）のテスト"""

import pytest


async def _create_customer(client, name="注文テスト顧客"):
    res = await client.post("/api/v1/customers", json={"name": name})
    return res.json()["id"]


async def _create_deal(client, customer_id, title="注文テスト案件"):
    res = await client.post("/api/v1/deals", json={
        "customer_id": customer_id, "title": title,
    })
    return res.json()["id"]


class TestOrdersCRUD:
    """注文の作成・取得・更新・削除"""

    async def test_create_order(self, client):
        """注文を新規作成できる"""
        customer_id = await _create_customer(client)
        deal_id = await _create_deal(client, customer_id)

        res = await client.post("/api/v1/orders", json={
            "customer_id": customer_id,
            "deal_id": deal_id,
            "order_number": "ORD-001",
            "total_amount": 500000,
            "status": "pending",
        })
        assert res.status_code == 201
        data = res.json()
        assert data["order_number"] == "ORD-001"
        assert float(data["total_amount"]) == 500000.0
        assert data["status"] == "pending"
        assert data["customer_id"] == customer_id
        assert data["deal_id"] == deal_id

    async def test_create_order_without_deal(self, client):
        """案件なしでも注文を作成できる"""
        customer_id = await _create_customer(client)
        res = await client.post("/api/v1/orders", json={
            "customer_id": customer_id,
            "order_number": "ORD-NODEAL",
            "total_amount": 10000,
        })
        assert res.status_code == 201
        assert res.json()["deal_id"] is None

    async def test_create_order_duplicate_number(self, client):
        """注文番号の重複は409"""
        customer_id = await _create_customer(client)
        await client.post("/api/v1/orders", json={
            "customer_id": customer_id,
            "order_number": "ORD-DUP",
        })
        res = await client.post("/api/v1/orders", json={
            "customer_id": customer_id,
            "order_number": "ORD-DUP",
        })
        assert res.status_code == 409

    async def test_create_order_invalid_customer(self, client):
        """存在しない顧客IDは400"""
        res = await client.post("/api/v1/orders", json={
            "customer_id": 99999,
            "order_number": "ORD-INVALID",
        })
        assert res.status_code == 400

    async def test_create_order_invalid_deal(self, client):
        """存在しない案件IDは400"""
        customer_id = await _create_customer(client)
        res = await client.post("/api/v1/orders", json={
            "customer_id": customer_id,
            "deal_id": 99999,
            "order_number": "ORD-BADDEAL",
        })
        assert res.status_code == 400

    async def test_list_orders(self, client):
        """注文一覧を取得できる"""
        customer_id = await _create_customer(client)
        await client.post("/api/v1/orders", json={
            "customer_id": customer_id, "order_number": "ORD-LIST-1",
        })
        await client.post("/api/v1/orders", json={
            "customer_id": customer_id, "order_number": "ORD-LIST-2",
        })

        res = await client.get("/api/v1/orders")
        assert res.status_code == 200
        assert len(res.json()) >= 2

    async def test_list_orders_filter_by_status(self, client):
        """ステータスでフィルタリングできる"""
        customer_id = await _create_customer(client)
        await client.post("/api/v1/orders", json={
            "customer_id": customer_id, "order_number": "ORD-PEND",
            "status": "pending",
        })
        await client.post("/api/v1/orders", json={
            "customer_id": customer_id, "order_number": "ORD-CONF",
            "status": "confirmed",
        })

        res = await client.get("/api/v1/orders", params={"status": "pending"})
        assert res.status_code == 200
        assert all(o["status"] == "pending" for o in res.json())

    async def test_get_order(self, client):
        """注文詳細を取得できる"""
        customer_id = await _create_customer(client)
        create_res = await client.post("/api/v1/orders", json={
            "customer_id": customer_id, "order_number": "ORD-DETAIL",
        })
        order_id = create_res.json()["id"]

        res = await client.get(f"/api/v1/orders/{order_id}")
        assert res.status_code == 200
        assert res.json()["order_number"] == "ORD-DETAIL"

    async def test_update_order_status(self, client):
        """注文ステータスを更新できる"""
        customer_id = await _create_customer(client)
        create_res = await client.post("/api/v1/orders", json={
            "customer_id": customer_id, "order_number": "ORD-UPD",
        })
        order_id = create_res.json()["id"]

        res = await client.patch(f"/api/v1/orders/{order_id}", json={
            "status": "shipped",
        })
        assert res.status_code == 200
        assert res.json()["status"] == "shipped"

    async def test_delete_order(self, client):
        """注文を削除できる"""
        customer_id = await _create_customer(client)
        create_res = await client.post("/api/v1/orders", json={
            "customer_id": customer_id, "order_number": "ORD-DEL",
        })
        order_id = create_res.json()["id"]

        res = await client.delete(f"/api/v1/orders/{order_id}")
        assert res.status_code == 204

        res = await client.get(f"/api/v1/orders/{order_id}")
        assert res.status_code == 404


class TestOrdersValidation:
    """注文バリデーション"""

    async def test_create_without_order_number(self, client):
        """注文番号なしは422"""
        customer_id = await _create_customer(client)
        res = await client.post("/api/v1/orders", json={
            "customer_id": customer_id,
        })
        assert res.status_code == 422

    async def test_create_without_customer_id(self, client):
        """顧客IDなしは422"""
        res = await client.post("/api/v1/orders", json={
            "order_number": "ORD-NOCUST",
        })
        assert res.status_code == 422

    async def test_negative_amount(self, client):
        """負の金額は422"""
        customer_id = await _create_customer(client)
        res = await client.post("/api/v1/orders", json={
            "customer_id": customer_id,
            "order_number": "ORD-NEG",
            "total_amount": -500,
        })
        assert res.status_code == 422
