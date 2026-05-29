"""
見積もり管理API（quotes）のテスト

対象:
  - GET /quotes  (一覧・フィルタ)
  - POST /quotes (作成・小計計算)
  - GET /quotes/{id} (詳細)
  - PATCH /quotes/{id} (更新・合計再計算)
  - POST /quotes/{id}/send (ステータス遷移)
  - POST /quotes/{id}/approve
  - POST /quotes/{id}/reject
  - DELETE /quotes/{id}
  - _calc_currency_amounts 相当のロジック (金額計算)
"""

import pytest
from decimal import Decimal


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------

async def _create_company_contact(client, company_name="見積テスト会社"):
    co = await client.post("/api/v1/companies", json={"name": company_name})
    assert co.status_code == 201, co.text
    company_id = co.json()["id"]

    ct = await client.post("/api/v1/contacts", json={
        "company_id": company_id,
        "display_name": f"{company_name}の担当",
    })
    assert ct.status_code == 201, ct.text
    return company_id, ct.json()["id"]


async def _create_quote(client, company_id, contact_id, **kwargs):
    payload = {
        "company_id": company_id,
        "contact_id": contact_id,
        "items": [
            {"product_name": "テスト商品A", "quantity": 2, "unit_price": "1000.00"},
        ],
    }
    payload.update(kwargs)
    res = await client.post("/api/v1/quotes", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

class TestQuotesCRUD:
    """見積もりの基本 CRUD"""

    async def test_create_quote(self, client):
        """見積もりを新規作成できる"""
        company_id, contact_id = await _create_company_contact(client)
        data = await _create_quote(client, company_id, contact_id)

        assert data["company_id"] == company_id
        assert data["contact_id"] == contact_id
        assert data["status"] == "draft"
        assert data["quote_code"].startswith("QT-")
        assert len(data["items"]) == 1
        assert data["items"][0]["product_name"] == "テスト商品A"

    async def test_create_quote_with_deal(self, client):
        """案件IDを紐付けて見積もりを作成できる"""
        company_id, contact_id = await _create_company_contact(client)
        deal_res = await client.post("/api/v1/deals", json={
            "company_id": company_id,
            "contact_id": contact_id,
            "title": "見積テスト案件",
        })
        deal_id = deal_res.json()["id"]

        data = await _create_quote(client, company_id, contact_id, deal_id=deal_id)
        assert data["deal_id"] == deal_id

    async def test_list_quotes(self, client):
        """見積もり一覧を取得できる"""
        company_id, contact_id = await _create_company_contact(client)
        await _create_quote(client, company_id, contact_id)
        await _create_quote(client, company_id, contact_id)

        res = await client.get("/api/v1/quotes")
        assert res.status_code == 200
        assert len(res.json()) >= 2

    async def test_list_quotes_filter_by_status(self, client):
        """ステータスでフィルタリングできる"""
        company_id, contact_id = await _create_company_contact(client)
        q = await _create_quote(client, company_id, contact_id)

        # draft フィルタ
        res = await client.get("/api/v1/quotes", params={"status": "draft"})
        assert res.status_code == 200
        assert all(r["status"] == "draft" for r in res.json())

    async def test_list_quotes_filter_by_company(self, client):
        """company_id でフィルタリングできる"""
        co_a, ct_a = await _create_company_contact(client, "フィルタ会社A")
        co_b, ct_b = await _create_company_contact(client, "フィルタ会社B")
        await _create_quote(client, co_a, ct_a)
        await _create_quote(client, co_b, ct_b)

        res = await client.get("/api/v1/quotes", params={"company_id": co_a})
        assert res.status_code == 200
        assert all(r["company_id"] == co_a for r in res.json())

    async def test_get_quote(self, client):
        """見積もり詳細を取得できる"""
        company_id, contact_id = await _create_company_contact(client)
        created = await _create_quote(client, company_id, contact_id)
        quote_id = created["id"]

        res = await client.get(f"/api/v1/quotes/{quote_id}")
        assert res.status_code == 200
        assert res.json()["id"] == quote_id
        assert len(res.json()["items"]) == 1

    async def test_get_quote_not_found(self, client):
        """存在しない見積もりIDは 404"""
        res = await client.get("/api/v1/quotes/99999")
        assert res.status_code == 404

    async def test_update_quote_draft(self, client):
        """draft 状態の見積もりを更新できる"""
        company_id, contact_id = await _create_company_contact(client)
        created = await _create_quote(client, company_id, contact_id)
        quote_id = created["id"]

        res = await client.patch(f"/api/v1/quotes/{quote_id}", json={
            "shipping_country": "US",
            "notes": "更新テスト",
        })
        assert res.status_code == 200
        assert res.json()["shipping_country"] == "US"
        assert res.json()["notes"] == "更新テスト"

    async def test_update_quote_no_fields(self, client):
        """更新フィールドなしは 400"""
        company_id, contact_id = await _create_company_contact(client)
        created = await _create_quote(client, company_id, contact_id)

        res = await client.patch(f"/api/v1/quotes/{created['id']}", json={})
        assert res.status_code == 400

    async def test_update_quote_not_found(self, client):
        """存在しない見積もりの更新は 404"""
        res = await client.patch("/api/v1/quotes/99999", json={"notes": "x"})
        assert res.status_code == 404

    async def test_delete_quote_draft(self, client):
        """draft 状態の見積もりを削除できる"""
        company_id, contact_id = await _create_company_contact(client)
        created = await _create_quote(client, company_id, contact_id)
        quote_id = created["id"]

        res = await client.delete(f"/api/v1/quotes/{quote_id}")
        assert res.status_code == 204

        res = await client.get(f"/api/v1/quotes/{quote_id}")
        assert res.status_code == 404

    async def test_delete_quote_non_draft(self, client):
        """sent 状態の見積もりは削除できない（400）"""
        company_id, contact_id = await _create_company_contact(client)
        created = await _create_quote(client, company_id, contact_id)
        quote_id = created["id"]

        # draft → sent
        await client.post(f"/api/v1/quotes/{quote_id}/send")

        res = await client.delete(f"/api/v1/quotes/{quote_id}")
        assert res.status_code == 400

    async def test_delete_quote_not_found(self, client):
        """存在しない見積もりの削除は 404"""
        res = await client.delete("/api/v1/quotes/99999")
        assert res.status_code == 404


# ---------------------------------------------------------------------------
# 金額計算
# ---------------------------------------------------------------------------

class TestQuotesCalculation:
    """見積もりの金額自動計算"""

    async def test_subtotal_from_items(self, client):
        """明細の数量 × 単価 の合計が subtotal になる"""
        company_id, contact_id = await _create_company_contact(client, "計算テスト会社")
        res = await client.post("/api/v1/quotes", json={
            "company_id": company_id,
            "contact_id": contact_id,
            "items": [
                {"product_name": "商品X", "quantity": 3, "unit_price": "500.00"},
                {"product_name": "商品Y", "quantity": 2, "unit_price": "1500.00"},
            ],
        })
        assert res.status_code == 201
        data = res.json()
        # subtotal = 3*500 + 2*1500 = 1500 + 3000 = 4500
        assert float(data["subtotal"]) == 4500.0
        assert float(data["total_amount"]) == 4500.0

    async def test_total_with_shipping_and_tax(self, client):
        """shipping_fee + tax_amount が total に加算される"""
        company_id, contact_id = await _create_company_contact(client, "送料税計算会社")
        res = await client.post("/api/v1/quotes", json={
            "company_id": company_id,
            "contact_id": contact_id,
            "shipping_fee": "800.00",
            "tax_amount": "500.00",
            "items": [
                {"product_name": "商品Z", "quantity": 1, "unit_price": "2000.00"},
            ],
        })
        assert res.status_code == 201
        data = res.json()
        # subtotal=2000, total=2000+800+500=3300
        assert float(data["subtotal"]) == 2000.0
        assert float(data["total_amount"]) == 3300.0

    async def test_update_recalculates_total(self, client):
        """PATCH で shipping_fee を変更すると total が再計算される"""
        company_id, contact_id = await _create_company_contact(client, "再計算会社")
        created = await _create_quote(client, company_id, contact_id)
        quote_id = created["id"]

        # subtotal=2000 (quantity=2, price=1000), total should be 2000+200=2200
        res = await client.patch(f"/api/v1/quotes/{quote_id}", json={
            "shipping_fee": "200.00",
        })
        assert res.status_code == 200
        assert float(res.json()["total_amount"]) == 2200.0


# ---------------------------------------------------------------------------
# ステータス遷移
# ---------------------------------------------------------------------------

class TestQuotesStatusTransitions:
    """見積もりのステータス遷移（ステートマシン）"""

    async def test_draft_to_sent(self, client):
        """draft → sent へ送付できる"""
        company_id, contact_id = await _create_company_contact(client, "送付テスト会社")
        created = await _create_quote(client, company_id, contact_id)
        quote_id = created["id"]

        res = await client.post(f"/api/v1/quotes/{quote_id}/send")
        assert res.status_code == 200
        assert res.json()["status"] == "sent"

    async def test_send_non_draft_returns_400(self, client):
        """sent 状態からさらに send は 400"""
        company_id, contact_id = await _create_company_contact(client, "二重送付会社")
        created = await _create_quote(client, company_id, contact_id)
        quote_id = created["id"]

        await client.post(f"/api/v1/quotes/{quote_id}/send")
        res = await client.post(f"/api/v1/quotes/{quote_id}/send")
        assert res.status_code == 400

    async def test_sent_to_approved(self, client):
        """sent → approved へ承認できる"""
        company_id, contact_id = await _create_company_contact(client, "承認テスト会社")
        created = await _create_quote(client, company_id, contact_id)
        quote_id = created["id"]

        await client.post(f"/api/v1/quotes/{quote_id}/send")
        res = await client.post(f"/api/v1/quotes/{quote_id}/approve")
        assert res.status_code == 200
        assert res.json()["status"] == "approved"

    async def test_approve_non_sent_returns_400(self, client):
        """draft 状態の承認は 400"""
        company_id, contact_id = await _create_company_contact(client, "承認失敗会社")
        created = await _create_quote(client, company_id, contact_id)
        quote_id = created["id"]

        res = await client.post(f"/api/v1/quotes/{quote_id}/approve")
        assert res.status_code == 400

    async def test_sent_to_rejected(self, client):
        """sent → rejected へ却下できる"""
        company_id, contact_id = await _create_company_contact(client, "却下テスト会社")
        created = await _create_quote(client, company_id, contact_id)
        quote_id = created["id"]

        await client.post(f"/api/v1/quotes/{quote_id}/send")
        res = await client.post(f"/api/v1/quotes/{quote_id}/reject")
        assert res.status_code == 200
        assert res.json()["status"] == "rejected"

    async def test_reject_non_sent_returns_400(self, client):
        """draft 状態の却下は 400"""
        company_id, contact_id = await _create_company_contact(client, "却下失敗会社")
        created = await _create_quote(client, company_id, contact_id)
        quote_id = created["id"]

        res = await client.post(f"/api/v1/quotes/{quote_id}/reject")
        assert res.status_code == 400

    async def test_cannot_update_approved_quote(self, client):
        """approved 状態の見積もりは更新できない（400）"""
        company_id, contact_id = await _create_company_contact(client, "更新禁止会社")
        created = await _create_quote(client, company_id, contact_id)
        quote_id = created["id"]

        await client.post(f"/api/v1/quotes/{quote_id}/send")
        await client.post(f"/api/v1/quotes/{quote_id}/approve")

        res = await client.patch(f"/api/v1/quotes/{quote_id}", json={"notes": "変更試み"})
        assert res.status_code == 400


# ---------------------------------------------------------------------------
# バリデーション
# ---------------------------------------------------------------------------

class TestQuotesValidation:
    """バリデーションエラーのテスト"""

    async def test_missing_company_id(self, client):
        """company_id なしは 422"""
        res = await client.post("/api/v1/quotes", json={
            "contact_id": 1,
            "items": [{"product_name": "x", "quantity": 1, "unit_price": "100.00"}],
        })
        assert res.status_code == 422

    async def test_missing_items(self, client):
        """items なしは 422"""
        res = await client.post("/api/v1/quotes", json={
            "company_id": 1,
            "contact_id": 1,
        })
        assert res.status_code == 422

    async def test_empty_items(self, client):
        """items が空配列は 422"""
        res = await client.post("/api/v1/quotes", json={
            "company_id": 1,
            "contact_id": 1,
            "items": [],
        })
        assert res.status_code == 422

    async def test_contact_not_found(self, client):
        """存在しない contact_id は 404"""
        company_id, _ = await _create_company_contact(client, "連絡先なし会社")
        res = await client.post("/api/v1/quotes", json={
            "company_id": company_id,
            "contact_id": 99999,
            "items": [{"product_name": "x", "quantity": 1, "unit_price": "100.00"}],
        })
        assert res.status_code == 404

    async def test_contact_mismatch_company(self, client):
        """別会社に属する contact_id は 400"""
        co_a, ct_a = await _create_company_contact(client, "会社A")
        co_b, _ = await _create_company_contact(client, "会社B")

        res = await client.post("/api/v1/quotes", json={
            "company_id": co_b,
            "contact_id": ct_a,  # 会社Aの担当者を会社Bで使う
            "items": [{"product_name": "x", "quantity": 1, "unit_price": "100.00"}],
        })
        assert res.status_code == 400

    async def test_deal_not_found(self, client):
        """存在しない deal_id は 404"""
        company_id, contact_id = await _create_company_contact(client, "案件なし会社")
        res = await client.post("/api/v1/quotes", json={
            "company_id": company_id,
            "contact_id": contact_id,
            "deal_id": 99999,
            "items": [{"product_name": "x", "quantity": 1, "unit_price": "100.00"}],
        })
        assert res.status_code == 404

    async def test_negative_unit_price(self, client):
        """負の unit_price は 422"""
        company_id, contact_id = await _create_company_contact(client, "負金額会社")
        res = await client.post("/api/v1/quotes", json={
            "company_id": company_id,
            "contact_id": contact_id,
            "items": [{"product_name": "x", "quantity": 1, "unit_price": "-1.00"}],
        })
        assert res.status_code == 422

    async def test_zero_quantity(self, client):
        """quantity=0 は 422"""
        company_id, contact_id = await _create_company_contact(client, "ゼロ数量会社")
        res = await client.post("/api/v1/quotes", json={
            "company_id": company_id,
            "contact_id": contact_id,
            "items": [{"product_name": "x", "quantity": 0, "unit_price": "100.00"}],
        })
        assert res.status_code == 422
