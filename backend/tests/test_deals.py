"""案件管理API（deals）のテスト

Phase 1-B-2 Step 5d 以降は会社 + 担当者 (company_id + contact_id) を必須とする。
"""

import pytest


async def _create_company_contact(client, company_name="テスト顧客"):
    """テスト用に会社 + 担当者ペアを作成する共通ヘルパー。

    backend が deals/orders/quotes/invoices/leads.convert で要求する
    (company_id, contact_id) を返す。
    """
    co = await client.post("/api/v1/companies", json={"name": company_name})
    assert co.status_code == 201
    company_id = co.json()["id"]
    ct = await client.post("/api/v1/contacts", json={
        "company_id": company_id,
        "display_name": f"{company_name}の担当",
    })
    assert ct.status_code == 201
    return company_id, ct.json()["id"]


class TestDealsCRUD:
    """案件の作成・取得・更新・削除"""

    async def test_create_deal(self, client):
        """案件を新規作成できる"""
        company_id, contact_id = await _create_company_contact(client)
        res = await client.post("/api/v1/deals", json={
            "company_id": company_id,
            "contact_id": contact_id,
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
        assert data["company_id"] == company_id
        assert data["contact_id"] == contact_id

    async def test_create_deal_invalid_contact(self, client):
        """存在しない担当者IDで案件作成は404"""
        company_id, _ = await _create_company_contact(client)
        res = await client.post("/api/v1/deals", json={
            "company_id": company_id,
            "contact_id": 99999,
            "title": "無効な案件",
        })
        assert res.status_code == 404

    async def test_create_deal_contact_company_mismatch(self, client):
        """contact が指定 company に所属していない場合は400"""
        company_a, contact_a = await _create_company_contact(client, "会社A")
        company_b, _ = await _create_company_contact(client, "会社B")
        res = await client.post("/api/v1/deals", json={
            "company_id": company_b,
            "contact_id": contact_a,
            "title": "ミスマッチ案件",
        })
        assert res.status_code == 400

    async def test_list_deals(self, client):
        """案件一覧を取得できる"""
        company_id, contact_id = await _create_company_contact(client)
        await client.post("/api/v1/deals", json={
            "company_id": company_id, "contact_id": contact_id, "title": "案件A",
        })
        await client.post("/api/v1/deals", json={
            "company_id": company_id, "contact_id": contact_id, "title": "案件B",
        })

        res = await client.get("/api/v1/deals")
        assert res.status_code == 200
        assert len(res.json()) >= 2

    async def test_list_deals_filter_by_status(self, client):
        """ステータスでフィルタリングできる"""
        company_id, contact_id = await _create_company_contact(client)
        await client.post("/api/v1/deals", json={
            "company_id": company_id, "contact_id": contact_id,
            "title": "成約案件", "status": "won",
        })
        await client.post("/api/v1/deals", json={
            "company_id": company_id, "contact_id": contact_id,
            "title": "進行中案件", "status": "open",
        })

        res = await client.get("/api/v1/deals", params={"status": "won"})
        assert res.status_code == 200
        data = res.json()
        assert all(d["status"] == "won" for d in data)

    async def test_list_deals_filter_by_company(self, client):
        """会社IDでフィルタリングできる"""
        company_a, contact_a = await _create_company_contact(client, "顧客A")
        company_b, contact_b = await _create_company_contact(client, "顧客B")
        await client.post("/api/v1/deals", json={
            "company_id": company_a, "contact_id": contact_a, "title": "Aの案件",
        })
        await client.post("/api/v1/deals", json={
            "company_id": company_b, "contact_id": contact_b, "title": "Bの案件",
        })

        res = await client.get("/api/v1/deals", params={"company_id": company_a})
        assert res.status_code == 200
        data = res.json()
        assert all(d["company_id"] == company_a for d in data)

    async def test_get_deal(self, client):
        """案件詳細を取得できる"""
        company_id, contact_id = await _create_company_contact(client)
        create_res = await client.post("/api/v1/deals", json={
            "company_id": company_id, "contact_id": contact_id, "title": "詳細テスト案件",
        })
        deal_id = create_res.json()["id"]

        res = await client.get(f"/api/v1/deals/{deal_id}")
        assert res.status_code == 200
        assert res.json()["title"] == "詳細テスト案件"

    async def test_update_deal_status(self, client):
        """案件のステータスを更新できる"""
        company_id, contact_id = await _create_company_contact(client)
        create_res = await client.post("/api/v1/deals", json={
            "company_id": company_id, "contact_id": contact_id, "title": "進行中",
        })
        deal_id = create_res.json()["id"]

        res = await client.patch(f"/api/v1/deals/{deal_id}", json={"status": "won"})
        assert res.status_code == 200
        assert res.json()["status"] == "won"

    async def test_update_deal_with_date_and_amount(self, client):
        """date(expected_close_date)とDecimal(amount)を同時更新できる（asyncpg encoder対策の回帰テスト）"""
        company_id, contact_id = await _create_company_contact(client)
        create_res = await client.post("/api/v1/deals", json={
            "company_id": company_id, "contact_id": contact_id, "title": "日付更新テスト",
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
        company_id, contact_id = await _create_company_contact(client)
        create_res = await client.post("/api/v1/deals", json={
            "company_id": company_id, "contact_id": contact_id, "title": "削除案件",
        })
        deal_id = create_res.json()["id"]

        res = await client.delete(f"/api/v1/deals/{deal_id}")
        assert res.status_code == 204

        res = await client.get(f"/api/v1/deals/{deal_id}")
        assert res.status_code == 404

    async def test_delete_deal_with_order_returns_409(self, client):
        """関連注文がある商談は削除できず、409とわかりやすいメッセージを返す"""
        company_id, contact_id = await _create_company_contact(client)
        deal_res = await client.post("/api/v1/deals", json={
            "company_id": company_id, "contact_id": contact_id, "title": "注文紐付け商談",
        })
        deal_id = deal_res.json()["id"]
        await client.post("/api/v1/orders", json={
            "company_id": company_id, "contact_id": contact_id,
            "deal_id": deal_id, "order_number": "ORD-FK-TEST",
        })

        res = await client.delete(f"/api/v1/deals/{deal_id}")
        assert res.status_code == 409
        assert "注文" in res.json()["detail"]


class TestDealsValidation:
    """案件バリデーション"""

    async def test_create_without_title(self, client):
        """タイトルなしは422"""
        company_id, contact_id = await _create_company_contact(client)
        res = await client.post("/api/v1/deals", json={
            "company_id": company_id, "contact_id": contact_id,
        })
        assert res.status_code == 422

    async def test_create_without_company_or_contact(self, client):
        """会社/担当者IDなしは422"""
        res = await client.post("/api/v1/deals", json={"title": "顧客なし案件"})
        assert res.status_code == 422

    async def test_invalid_status(self, client):
        """無効なステータスは422"""
        company_id, contact_id = await _create_company_contact(client)
        res = await client.post("/api/v1/deals", json={
            "company_id": company_id, "contact_id": contact_id,
            "title": "無効ステータス", "status": "invalid",
        })
        assert res.status_code == 422

    async def test_negative_amount(self, client):
        """負の金額は422"""
        company_id, contact_id = await _create_company_contact(client)
        res = await client.post("/api/v1/deals", json={
            "company_id": company_id, "contact_id": contact_id,
            "title": "負の金額", "amount": -100,
        })
        assert res.status_code == 422
