"""
請求書管理API（invoices）のテスト

対象:
  - GET /invoices (一覧・フィルタ)
  - POST /invoices (直接作成)
  - POST /invoices/from-quote/{id} (見積もり変換)
  - GET /invoices/{id} (詳細)
  - PATCH /invoices/{id} (更新)
  - POST /invoices/{id}/issue (draft → issued)
  - POST /invoices/{id}/pay  (issued → paid)
  - POST /invoices/{id}/void (無効化)
  - _calc_currency_amounts の単体テスト（JPY/USD/EUR）
"""

from decimal import Decimal


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------

async def _create_company_contact(client, company_name="請求テスト会社"):
    co = await client.post("/api/v1/companies", json={"name": company_name})
    assert co.status_code == 201, co.text
    company_id = co.json()["id"]

    ct = await client.post("/api/v1/contacts", json={
        "company_id": company_id,
        "display_name": f"{company_name}の担当",
    })
    assert ct.status_code == 201, ct.text
    return company_id, ct.json()["id"]


async def _create_invoice(client, company_id, contact_id, **kwargs):
    payload = {
        "company_id": company_id,
        "contact_id": contact_id,
        "items": [
            {"product_name": "テスト商品", "quantity": 2, "unit_price": "5000.00"},
        ],
    }
    payload.update(kwargs)
    res = await client.post("/api/v1/invoices", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


async def _create_approved_quote(client, company_id, contact_id):
    """見積もりを作成して承認済みにする"""
    q_res = await client.post("/api/v1/quotes", json={
        "company_id": company_id,
        "contact_id": contact_id,
        "items": [
            {"product_name": "見積商品", "quantity": 1, "unit_price": "3000.00"},
        ],
    })
    assert q_res.status_code == 201, q_res.text
    quote_id = q_res.json()["id"]

    await client.post(f"/api/v1/quotes/{quote_id}/send")
    await client.post(f"/api/v1/quotes/{quote_id}/approve")
    return quote_id


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

class TestInvoicesCRUD:
    """請求書の基本 CRUD"""

    async def test_create_invoice_direct(self, client):
        """請求書を直接作成できる"""
        company_id, contact_id = await _create_company_contact(client)
        data = await _create_invoice(client, company_id, contact_id)

        assert data["company_id"] == company_id
        assert data["contact_id"] == contact_id
        assert data["status"] == "draft"
        assert data["invoice_number"].startswith("IN-")
        assert len(data["items"]) == 1

    async def test_list_invoices(self, client):
        """請求書一覧を取得できる"""
        company_id, contact_id = await _create_company_contact(client)
        await _create_invoice(client, company_id, contact_id)
        await _create_invoice(client, company_id, contact_id)

        res = await client.get("/api/v1/invoices")
        assert res.status_code == 200
        assert len(res.json()) >= 2

    async def test_list_invoices_filter_by_status(self, client):
        """status でフィルタリングできる"""
        company_id, contact_id = await _create_company_contact(client, "ステータスフィルタ会社")
        await _create_invoice(client, company_id, contact_id)

        res = await client.get("/api/v1/invoices", params={"status": "draft"})
        assert res.status_code == 200
        assert all(r["status"] == "draft" for r in res.json())

    async def test_list_invoices_filter_by_company(self, client):
        """company_id でフィルタリングできる"""
        co_a, ct_a = await _create_company_contact(client, "会社A請求")
        co_b, ct_b = await _create_company_contact(client, "会社B請求")
        await _create_invoice(client, co_a, ct_a)
        await _create_invoice(client, co_b, ct_b)

        res = await client.get("/api/v1/invoices", params={"company_id": co_a})
        assert res.status_code == 200
        assert all(r["company_id"] == co_a for r in res.json())

    async def test_get_invoice(self, client):
        """請求書詳細を取得できる（明細含む）"""
        company_id, contact_id = await _create_company_contact(client)
        created = await _create_invoice(client, company_id, contact_id)
        invoice_id = created["id"]

        res = await client.get(f"/api/v1/invoices/{invoice_id}")
        assert res.status_code == 200
        data = res.json()
        assert data["id"] == invoice_id
        assert len(data["items"]) == 1
        assert data["items"][0]["product_name"] == "テスト商品"

    async def test_get_invoice_not_found(self, client):
        """存在しない請求書IDは 404"""
        res = await client.get("/api/v1/invoices/99999")
        assert res.status_code == 404

    async def test_update_invoice_draft(self, client):
        """draft 状態の請求書を更新できる"""
        company_id, contact_id = await _create_company_contact(client)
        created = await _create_invoice(client, company_id, contact_id)
        invoice_id = created["id"]

        res = await client.patch(f"/api/v1/invoices/{invoice_id}", json={
            "payment_method": "銀行振込",
            "notes": "支払い期限注意",
        })
        assert res.status_code == 200
        assert res.json()["payment_method"] == "銀行振込"
        assert res.json()["notes"] == "支払い期限注意"

    async def test_update_invoice_non_draft_returns_400(self, client):
        """issued 状態の請求書は更新不可（400）"""
        company_id, contact_id = await _create_company_contact(client, "更新禁止会社")
        created = await _create_invoice(client, company_id, contact_id)
        invoice_id = created["id"]

        await client.post(f"/api/v1/invoices/{invoice_id}/issue")

        res = await client.patch(f"/api/v1/invoices/{invoice_id}", json={
            "notes": "変更試み",
        })
        assert res.status_code == 400

    async def test_update_invoice_no_fields_returns_400(self, client):
        """更新フィールドなしは 400"""
        company_id, contact_id = await _create_company_contact(client)
        created = await _create_invoice(client, company_id, contact_id)

        res = await client.patch(f"/api/v1/invoices/{created['id']}", json={})
        assert res.status_code == 400


# ---------------------------------------------------------------------------
# 見積もりから変換
# ---------------------------------------------------------------------------

class TestInvoicesFromQuote:
    """見積もりからの請求書変換"""

    async def test_create_from_approved_quote(self, client):
        """承認済み見積もりから請求書を作成できる"""
        company_id, contact_id = await _create_company_contact(client, "変換テスト会社")
        quote_id = await _create_approved_quote(client, company_id, contact_id)

        res = await client.post(f"/api/v1/invoices/from-quote/{quote_id}")
        assert res.status_code == 201
        data = res.json()
        assert data["quote_id"] == quote_id
        assert data["status"] == "draft"
        assert data["invoice_number"].startswith("IN-")
        # 明細が見積もりからコピーされている
        assert len(data["items"]) == 1
        assert data["items"][0]["product_name"] == "見積商品"

    async def test_create_from_draft_quote_returns_400(self, client):
        """draft 状態の見積もりからは変換不可（400）"""
        company_id, contact_id = await _create_company_contact(client, "draft変換失敗会社")
        q_res = await client.post("/api/v1/quotes", json={
            "company_id": company_id,
            "contact_id": contact_id,
            "items": [{"product_name": "商品", "quantity": 1, "unit_price": "100.00"}],
        })
        quote_id = q_res.json()["id"]

        res = await client.post(f"/api/v1/invoices/from-quote/{quote_id}")
        assert res.status_code == 400

    async def test_create_from_sent_quote_returns_400(self, client):
        """sent 状態の見積もりからも変換不可（400）"""
        company_id, contact_id = await _create_company_contact(client, "sent変換失敗会社")
        q_res = await client.post("/api/v1/quotes", json={
            "company_id": company_id,
            "contact_id": contact_id,
            "items": [{"product_name": "商品", "quantity": 1, "unit_price": "100.00"}],
        })
        quote_id = q_res.json()["id"]
        await client.post(f"/api/v1/quotes/{quote_id}/send")

        res = await client.post(f"/api/v1/invoices/from-quote/{quote_id}")
        assert res.status_code == 400

    async def test_create_from_nonexistent_quote_returns_404(self, client):
        """存在しない見積もりIDは 404"""
        res = await client.post("/api/v1/invoices/from-quote/99999")
        assert res.status_code == 404

    async def test_converted_invoice_inherits_amounts(self, client):
        """変換後の請求書が見積もりの金額を引き継ぐ"""
        company_id, contact_id = await _create_company_contact(client, "金額継承テスト会社")
        # shipping_fee=500 の見積もりを作成して承認
        q_res = await client.post("/api/v1/quotes", json={
            "company_id": company_id,
            "contact_id": contact_id,
            "shipping_fee": "500.00",
            "tax_amount": "100.00",
            "items": [{"product_name": "商品X", "quantity": 2, "unit_price": "1000.00"}],
        })
        quote_id = q_res.json()["id"]
        await client.post(f"/api/v1/quotes/{quote_id}/send")
        await client.post(f"/api/v1/quotes/{quote_id}/approve")

        res = await client.post(f"/api/v1/invoices/from-quote/{quote_id}")
        assert res.status_code == 201
        data = res.json()
        # subtotal=2000, shipping=500, tax=100 → total=2600
        assert float(data["subtotal"]) == 2000.0
        assert float(data["total_amount"]) == 2600.0


# ---------------------------------------------------------------------------
# 金額計算（単体テスト）
# ---------------------------------------------------------------------------

class TestInvoicesCalculation:
    """_calc_currency_amounts の単体テスト"""

    def test_calc_jpy_currency(self):
        """JPY通貨: amount_jpy=total, amount_usd=total/rate_usd"""
        from app.routers.invoices import _calc_currency_amounts
        total = Decimal("10000")
        rate_jpy = None
        rate_usd = Decimal("150.0000")

        amount_jpy, amount_usd = _calc_currency_amounts(total, "JPY", rate_jpy, rate_usd)
        assert amount_jpy == total
        # 10000 / 150 ≈ 66.67
        assert amount_usd == round(total / rate_usd, 2)

    def test_calc_jpy_without_usd_rate(self):
        """JPY通貨で rate_usd なし: amount_usd=None"""
        from app.routers.invoices import _calc_currency_amounts
        total = Decimal("5000")
        amount_jpy, amount_usd = _calc_currency_amounts(total, "JPY", None, None)
        assert amount_jpy == total
        assert amount_usd is None

    def test_calc_usd_currency(self):
        """USD通貨: amount_usd=total, amount_jpy=total*rate_jpy"""
        from app.routers.invoices import _calc_currency_amounts
        total = Decimal("100")
        rate_jpy = Decimal("150.0000")

        amount_jpy, amount_usd = _calc_currency_amounts(total, "USD", rate_jpy, None)
        assert amount_usd == total
        assert amount_jpy == round(total * rate_jpy, 2)

    def test_calc_usd_without_jpy_rate(self):
        """USD通貨で rate_jpy なし: amount_jpy=None"""
        from app.routers.invoices import _calc_currency_amounts
        total = Decimal("200")
        amount_jpy, amount_usd = _calc_currency_amounts(total, "USD", None, None)
        assert amount_usd == total
        assert amount_jpy is None

    def test_calc_eur_currency(self):
        """EUR通貨: rate_jpy と rate_usd の両方で換算"""
        from app.routers.invoices import _calc_currency_amounts
        total = Decimal("100")
        rate_jpy = Decimal("160.0000")
        rate_usd = Decimal("1.1000")

        amount_jpy, amount_usd = _calc_currency_amounts(total, "EUR", rate_jpy, rate_usd)
        assert amount_jpy == round(total * rate_jpy, 2)
        assert amount_usd == round(total * rate_usd, 2)

    async def test_create_invoice_calculates_subtotal(self, client):
        """明細の合計が subtotal/total に反映される"""
        company_id, contact_id = await _create_company_contact(client, "計算確認会社")
        res = await client.post("/api/v1/invoices", json={
            "company_id": company_id,
            "contact_id": contact_id,
            "tax_amount": "1000.00",
            "items": [
                {"product_name": "商品A", "quantity": 3, "unit_price": "2000.00"},
                {"product_name": "商品B", "quantity": 1, "unit_price": "500.00"},
            ],
        })
        assert res.status_code == 201
        data = res.json()
        # subtotal = 3*2000 + 1*500 = 6500
        assert float(data["subtotal"]) == 6500.0
        # total = 6500 + 1000 = 7500
        assert float(data["total_amount"]) == 7500.0


# ---------------------------------------------------------------------------
# ステータス遷移
# ---------------------------------------------------------------------------

class TestInvoicesStatusTransitions:
    """請求書のステータス遷移"""

    async def test_draft_to_issued(self, client):
        """draft → issued へ発行できる"""
        company_id, contact_id = await _create_company_contact(client, "発行テスト会社")
        created = await _create_invoice(client, company_id, contact_id)
        invoice_id = created["id"]

        res = await client.post(f"/api/v1/invoices/{invoice_id}/issue")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "issued"
        assert data["issued_at"] is not None

    async def test_issue_non_draft_returns_400(self, client):
        """issued 状態からさらに issue は 400"""
        company_id, contact_id = await _create_company_contact(client, "二重発行会社")
        created = await _create_invoice(client, company_id, contact_id)
        invoice_id = created["id"]

        await client.post(f"/api/v1/invoices/{invoice_id}/issue")
        res = await client.post(f"/api/v1/invoices/{invoice_id}/issue")
        assert res.status_code == 400

    async def test_issued_to_paid(self, client):
        """issued → paid へ入金登録できる"""
        company_id, contact_id = await _create_company_contact(client, "入金テスト会社")
        created = await _create_invoice(client, company_id, contact_id)
        invoice_id = created["id"]

        await client.post(f"/api/v1/invoices/{invoice_id}/issue")
        res = await client.post(f"/api/v1/invoices/{invoice_id}/pay")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "paid"
        assert data["paid_at"] is not None

    async def test_pay_draft_returns_400(self, client):
        """draft 状態からの入金登録は 400"""
        company_id, contact_id = await _create_company_contact(client, "入金失敗会社")
        created = await _create_invoice(client, company_id, contact_id)
        invoice_id = created["id"]

        res = await client.post(f"/api/v1/invoices/{invoice_id}/pay")
        assert res.status_code == 400

    async def test_void_draft_invoice(self, client):
        """draft 状態の請求書を void できる"""
        company_id, contact_id = await _create_company_contact(client, "void-draft会社")
        created = await _create_invoice(client, company_id, contact_id)
        invoice_id = created["id"]

        res = await client.post(f"/api/v1/invoices/{invoice_id}/void",
                                json={"reason": "ミス入力のため"})
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "voided"
        assert data["void_reason"] == "ミス入力のため"
        assert "[VOID]" in data["invoice_number"]

    async def test_void_issued_invoice(self, client):
        """issued 状態の請求書も void できる"""
        company_id, contact_id = await _create_company_contact(client, "void-issued会社")
        created = await _create_invoice(client, company_id, contact_id)
        invoice_id = created["id"]

        await client.post(f"/api/v1/invoices/{invoice_id}/issue")
        res = await client.post(f"/api/v1/invoices/{invoice_id}/void",
                                json={"reason": "キャンセル"})
        assert res.status_code == 200
        assert res.json()["status"] == "voided"

    async def test_cannot_void_paid_invoice(self, client):
        """paid 状態は void 不可（400）"""
        company_id, contact_id = await _create_company_contact(client, "paid-void禁止会社")
        created = await _create_invoice(client, company_id, contact_id)
        invoice_id = created["id"]

        await client.post(f"/api/v1/invoices/{invoice_id}/issue")
        await client.post(f"/api/v1/invoices/{invoice_id}/pay")
        res = await client.post(f"/api/v1/invoices/{invoice_id}/void",
                                json={"reason": "試み"})
        assert res.status_code == 400

    async def test_cannot_void_twice(self, client):
        """既に void 済みは再度 void できない（400）"""
        company_id, contact_id = await _create_company_contact(client, "二重void禁止会社")
        created = await _create_invoice(client, company_id, contact_id)
        invoice_id = created["id"]

        await client.post(f"/api/v1/invoices/{invoice_id}/void", json={"reason": "一度目"})
        res = await client.post(f"/api/v1/invoices/{invoice_id}/void", json={"reason": "二度目"})
        assert res.status_code == 400

    async def test_void_nonexistent_invoice_returns_404(self, client):
        """存在しない請求書の void は 404"""
        res = await client.post("/api/v1/invoices/99999/void", json={"reason": "x"})
        assert res.status_code == 404


# ---------------------------------------------------------------------------
# バリデーション
# ---------------------------------------------------------------------------

class TestInvoicesValidation:
    """バリデーションエラーのテスト"""

    async def test_missing_company_id(self, client):
        """company_id なしは 422"""
        res = await client.post("/api/v1/invoices", json={
            "contact_id": 1,
            "items": [{"product_name": "x", "quantity": 1, "unit_price": "100.00"}],
        })
        assert res.status_code == 422

    async def test_missing_items(self, client):
        """items なしは 422"""
        res = await client.post("/api/v1/invoices", json={
            "company_id": 1,
            "contact_id": 1,
        })
        assert res.status_code == 422

    async def test_empty_items(self, client):
        """items が空配列は 422"""
        res = await client.post("/api/v1/invoices", json={
            "company_id": 1,
            "contact_id": 1,
            "items": [],
        })
        assert res.status_code == 422

    async def test_contact_not_found(self, client):
        """存在しない contact_id は 404"""
        company_id, _ = await _create_company_contact(client, "連絡先なし会社")
        res = await client.post("/api/v1/invoices", json={
            "company_id": company_id,
            "contact_id": 99999,
            "items": [{"product_name": "x", "quantity": 1, "unit_price": "100.00"}],
        })
        assert res.status_code == 404

    async def test_contact_mismatch_company(self, client):
        """別会社の contact_id は 400"""
        co_a, ct_a = await _create_company_contact(client, "会社A")
        co_b, _ = await _create_company_contact(client, "会社B")

        res = await client.post("/api/v1/invoices", json={
            "company_id": co_b,
            "contact_id": ct_a,
            "items": [{"product_name": "x", "quantity": 1, "unit_price": "100.00"}],
        })
        assert res.status_code == 400

    async def test_void_without_reason(self, client):
        """void に reason なしは 422"""
        company_id, contact_id = await _create_company_contact(client)
        created = await _create_invoice(client, company_id, contact_id)

        res = await client.post(f"/api/v1/invoices/{created['id']}/void", json={})
        assert res.status_code == 422
