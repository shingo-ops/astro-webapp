"""注文管理API（orders）のテスト

Phase 1-B-2 Step 5d 以降は会社 + 担当者 (company_id + contact_id) を必須とする。
"""

import pytest


async def _create_company_contact(client, company_name="注文テスト顧客"):
    co = await client.post("/api/v1/companies", json={"name": company_name})
    company_id = co.json()["id"]
    ct = await client.post("/api/v1/contacts", json={
        "company_id": company_id,
        "display_name": f"{company_name}の担当",
    })
    return company_id, ct.json()["id"]


async def _create_deal(client, company_id, contact_id, title="注文テスト案件"):
    res = await client.post("/api/v1/deals", json={
        "company_id": company_id, "contact_id": contact_id, "title": title,
    })
    return res.json()["id"]


class TestOrdersCRUD:
    """注文の作成・取得・更新・削除"""

    async def test_create_order(self, client):
        """注文を新規作成できる"""
        company_id, contact_id = await _create_company_contact(client)
        deal_id = await _create_deal(client, company_id, contact_id)

        res = await client.post("/api/v1/orders", json={
            "company_id": company_id,
            "contact_id": contact_id,
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
        assert data["company_id"] == company_id
        assert data["contact_id"] == contact_id
        assert data["deal_id"] == deal_id

    async def test_create_order_without_deal(self, client):
        """案件なしでも注文を作成できる"""
        company_id, contact_id = await _create_company_contact(client)
        res = await client.post("/api/v1/orders", json={
            "company_id": company_id,
            "contact_id": contact_id,
            "order_number": "ORD-NODEAL",
            "total_amount": 10000,
        })
        assert res.status_code == 201
        assert res.json()["deal_id"] is None

    async def test_create_order_duplicate_number(self, client):
        """注文番号の重複は409"""
        company_id, contact_id = await _create_company_contact(client)
        await client.post("/api/v1/orders", json={
            "company_id": company_id,
            "contact_id": contact_id,
            "order_number": "ORD-DUP",
        })
        res = await client.post("/api/v1/orders", json={
            "company_id": company_id,
            "contact_id": contact_id,
            "order_number": "ORD-DUP",
        })
        assert res.status_code == 409

    async def test_create_order_invalid_contact(self, client):
        """存在しない担当者IDは400"""
        company_id, _ = await _create_company_contact(client)
        res = await client.post("/api/v1/orders", json={
            "company_id": company_id,
            "contact_id": 99999,
            "order_number": "ORD-INVALID",
        })
        assert res.status_code == 400

    async def test_create_order_invalid_deal(self, client):
        """存在しない案件IDは400"""
        company_id, contact_id = await _create_company_contact(client)
        res = await client.post("/api/v1/orders", json={
            "company_id": company_id,
            "contact_id": contact_id,
            "deal_id": 99999,
            "order_number": "ORD-BADDEAL",
        })
        assert res.status_code == 400

    async def test_list_orders(self, client):
        """注文一覧を取得できる"""
        company_id, contact_id = await _create_company_contact(client)
        await client.post("/api/v1/orders", json={
            "company_id": company_id, "contact_id": contact_id,
            "order_number": "ORD-LIST-1",
        })
        await client.post("/api/v1/orders", json={
            "company_id": company_id, "contact_id": contact_id,
            "order_number": "ORD-LIST-2",
        })

        res = await client.get("/api/v1/orders")
        assert res.status_code == 200
        assert len(res.json()) >= 2

    async def test_list_orders_filter_by_status(self, client):
        """ステータスでフィルタリングできる"""
        company_id, contact_id = await _create_company_contact(client)
        await client.post("/api/v1/orders", json={
            "company_id": company_id, "contact_id": contact_id,
            "order_number": "ORD-PEND",
            "status": "pending",
        })
        await client.post("/api/v1/orders", json={
            "company_id": company_id, "contact_id": contact_id,
            "order_number": "ORD-CONF",
            "status": "confirmed",
        })

        res = await client.get("/api/v1/orders", params={"status": "pending"})
        assert res.status_code == 200
        assert all(o["status"] == "pending" for o in res.json())

    async def test_get_order(self, client):
        """注文詳細を取得できる"""
        company_id, contact_id = await _create_company_contact(client)
        create_res = await client.post("/api/v1/orders", json={
            "company_id": company_id, "contact_id": contact_id,
            "order_number": "ORD-DETAIL",
        })
        order_id = create_res.json()["id"]

        res = await client.get(f"/api/v1/orders/{order_id}")
        assert res.status_code == 200
        assert res.json()["order_number"] == "ORD-DETAIL"

    async def test_update_order_status(self, client):
        """注文ステータスを更新できる"""
        company_id, contact_id = await _create_company_contact(client)
        create_res = await client.post("/api/v1/orders", json={
            "company_id": company_id, "contact_id": contact_id,
            "order_number": "ORD-UPD",
        })
        order_id = create_res.json()["id"]

        res = await client.patch(f"/api/v1/orders/{order_id}", json={
            "status": "shipped",
        })
        assert res.status_code == 200
        assert res.json()["status"] == "shipped"

    async def test_update_order_with_amount_and_status(self, client):
        """Decimal(total_amount)とEnum(status)を同時更新できる（asyncpg encoder対策の回帰テスト）"""
        company_id, contact_id = await _create_company_contact(client)
        create_res = await client.post("/api/v1/orders", json={
            "company_id": company_id, "contact_id": contact_id,
            "order_number": "ORD-UPD-FULL",
        })
        order_id = create_res.json()["id"]

        res = await client.patch(f"/api/v1/orders/{order_id}", json={
            "status": "confirmed",
            "total_amount": 50000,
            "notes": "備考更新",
        })
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "confirmed"
        assert float(body["total_amount"]) == 50000.0
        assert body["notes"] == "備考更新"

    async def test_delete_order(self, client):
        """注文を削除できる"""
        company_id, contact_id = await _create_company_contact(client)
        create_res = await client.post("/api/v1/orders", json={
            "company_id": company_id, "contact_id": contact_id,
            "order_number": "ORD-DEL",
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
        company_id, contact_id = await _create_company_contact(client)
        res = await client.post("/api/v1/orders", json={
            "company_id": company_id, "contact_id": contact_id,
        })
        assert res.status_code == 422

    async def test_create_without_company_or_contact(self, client):
        """会社/担当者IDなしは422"""
        res = await client.post("/api/v1/orders", json={
            "order_number": "ORD-NOCUST",
        })
        assert res.status_code == 422

    async def test_negative_amount(self, client):
        """負の金額は422"""
        company_id, contact_id = await _create_company_contact(client)
        res = await client.post("/api/v1/orders", json={
            "company_id": company_id,
            "contact_id": contact_id,
            "order_number": "ORD-NEG",
            "total_amount": -500,
        })
        assert res.status_code == 422
