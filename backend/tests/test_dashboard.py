"""ダッシュボードAPI（dashboard）のテスト

Phase 1-B-2 Step 5d 以降は会社 + 担当者 (company_id + contact_id) を必須とする。
"""

import pytest


async def _seed_data(client):
    """テスト用データを投入するヘルパー"""
    # 会社 + 担当者ペア 3 組
    pairs = []
    for name in ["顧客A", "顧客B", "顧客C"]:
        co = await client.post("/api/v1/companies", json={"name": name})
        company_id = co.json()["id"]
        ct = await client.post("/api/v1/contacts", json={
            "company_id": company_id,
            "display_name": f"{name}の担当",
        })
        pairs.append((company_id, ct.json()["id"]))

    # 案件: open 2件, won 1件
    await client.post("/api/v1/deals", json={
        "company_id": pairs[0][0], "contact_id": pairs[0][1],
        "title": "案件1", "amount": 100000, "status": "open",
    })
    await client.post("/api/v1/deals", json={
        "company_id": pairs[1][0], "contact_id": pairs[1][1],
        "title": "案件2", "amount": 200000, "status": "open",
    })
    await client.post("/api/v1/deals", json={
        "company_id": pairs[2][0], "contact_id": pairs[2][1],
        "title": "案件3", "amount": 500000, "status": "won",
    })

    # 注文: pending 2件, confirmed 1件
    await client.post("/api/v1/orders", json={
        "company_id": pairs[0][0], "contact_id": pairs[0][1],
        "order_number": "DASH-001",
        "total_amount": 50000, "status": "pending",
    })
    await client.post("/api/v1/orders", json={
        "company_id": pairs[1][0], "contact_id": pairs[1][1],
        "order_number": "DASH-002",
        "total_amount": 80000, "status": "pending",
    })
    await client.post("/api/v1/orders", json={
        "company_id": pairs[2][0], "contact_id": pairs[2][1],
        "order_number": "DASH-003",
        "total_amount": 120000, "status": "confirmed",
    })

    return pairs


class TestDashboard:
    """ダッシュボードKPI"""

    @pytest.mark.skip(reason="FILTER (WHERE ...) is PostgreSQL-specific, tested in integration tests")
    async def test_dashboard_with_data(self, client):
        """データがある場合のKPI集計が正しい（PostgreSQL環境で検証）"""
        pass

    async def test_dashboard_empty(self, client):
        """データが空の場合もエラーにならない"""
        res = await client.get("/api/v1/dashboard")
        assert res.status_code == 200
        data = res.json()
        assert data["customer_count"] == 0
        assert data["deal_count"] == 0
        assert data["order_count"] == 0
        assert data["deal_total_amount"] == 0.0
        assert data["order_total_amount"] == 0.0
