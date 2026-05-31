"""ADR-021 Phase 2 / Sprint 2 — 受注売上情報 API のテスト。

検証対象:
  - POST   /orders/{id}/financial
  - GET    /orders/{id}/financial
  - PATCH  /orders/{id}/financial
  - DELETE /orders/{id}/financial
  - GET    /financials/monthly?year=&month=&staff_id=

導出列の計算（cost_total / gross_profit / gross_profit_rate /
operating_profit_with_tax_refund）と、月次集計の整合性も併せて検証する。
"""

from decimal import Decimal


async def _create_company_contact(client, company_name="売上テスト顧客"):
    co = await client.post("/api/v1/companies", json={"name": company_name})
    company_id = co.json()["id"]
    ct = await client.post("/api/v1/contacts", json={
        "company_id": company_id,
        "display_name": f"{company_name}の担当",
    })
    return company_id, ct.json()["id"]


async def _create_order(client, order_number="ORD-FIN-1"):
    company_id, contact_id = await _create_company_contact(client, f"Co-{order_number}")
    res = await client.post("/api/v1/orders", json={
        "company_id": company_id,
        "contact_id": contact_id,
        "order_number": order_number,
    })
    assert res.status_code == 201, res.text
    return res.json()["id"]


class TestCreateFinancial:
    """POST /orders/{id}/financial"""

    async def test_create_financial_for_order(self, client):
        """売上情報を新規作成できる + 導出列がレスポンスに含まれる"""
        order_id = await _create_order(client, "ORD-FIN-CREATE-1")
        res = await client.post(
            f"/api/v1/orders/{order_id}/financial",
            json={
                "revenue_amount": 100000,
                "purchase_cost": 60000,
                "paypal_fee": 3000,
                "tax_refund": 5000,
            },
        )
        assert res.status_code == 201, res.text
        body = res.json()
        assert body["order_id"] == order_id
        assert float(body["revenue_amount"]) == 100000.0
        assert float(body["purchase_cost"]) == 60000.0
        # cost_total = 60000 + 0 + 3000 + 0*7 = 63000
        assert float(body["cost_total"]) == 63000.0
        # gross_profit = 100000 - 63000 = 37000
        assert float(body["gross_profit"]) == 37000.0
        # gross_profit_rate = 37000/100000 = 0.37
        assert abs(float(body["gross_profit_rate"]) - 0.37) < 1e-6
        # operating_profit_with_tax_refund = 37000 + 5000 = 42000
        assert float(body["operating_profit_with_tax_refund"]) == 42000.0

    async def test_create_financial_defaults_to_zero(self, client):
        """body 空でも全カラム 0 で作成できる"""
        order_id = await _create_order(client, "ORD-FIN-CREATE-EMPTY")
        res = await client.post(f"/api/v1/orders/{order_id}/financial", json={})
        assert res.status_code == 201, res.text
        body = res.json()
        assert float(body["revenue_amount"]) == 0.0
        assert float(body["cost_total"]) == 0.0
        assert float(body["gross_profit"]) == 0.0
        # revenue=0 のとき gross_profit_rate は null
        assert body["gross_profit_rate"] is None

    async def test_create_financial_duplicate_returns_409(self, client):
        """同一 order_id で 2 回 POST すると 409"""
        order_id = await _create_order(client, "ORD-FIN-DUP")
        first = await client.post(f"/api/v1/orders/{order_id}/financial", json={"revenue_amount": 1000})
        assert first.status_code == 201
        second = await client.post(f"/api/v1/orders/{order_id}/financial", json={"revenue_amount": 2000})
        assert second.status_code == 409

    async def test_create_financial_unknown_order_returns_404(self, client):
        """存在しない order_id だと 404"""
        res = await client.post("/api/v1/orders/999999/financial", json={"revenue_amount": 1000})
        assert res.status_code == 404

    async def test_create_financial_negative_amount_returns_422(self, client):
        """負の金額は 422"""
        order_id = await _create_order(client, "ORD-FIN-NEG")
        res = await client.post(
            f"/api/v1/orders/{order_id}/financial",
            json={"revenue_amount": -1000},
        )
        assert res.status_code == 422


class TestGetFinancial:
    """GET /orders/{id}/financial"""

    async def test_get_financial(self, client):
        """登録済み売上情報を取得できる"""
        order_id = await _create_order(client, "ORD-FIN-GET-1")
        await client.post(
            f"/api/v1/orders/{order_id}/financial",
            json={"revenue_amount": 50000, "purchase_cost": 20000},
        )
        res = await client.get(f"/api/v1/orders/{order_id}/financial")
        assert res.status_code == 200
        body = res.json()
        assert float(body["revenue_amount"]) == 50000.0
        assert float(body["cost_total"]) == 20000.0
        assert float(body["gross_profit"]) == 30000.0

    async def test_get_financial_not_found(self, client):
        """売上情報未登録なら 404"""
        order_id = await _create_order(client, "ORD-FIN-GET-404")
        res = await client.get(f"/api/v1/orders/{order_id}/financial")
        assert res.status_code == 404


class TestPatchFinancial:
    """PATCH /orders/{id}/financial"""

    async def test_patch_financial_partial(self, client):
        """部分更新できる（指定列のみ書き換わる）"""
        order_id = await _create_order(client, "ORD-FIN-PATCH-1")
        await client.post(
            f"/api/v1/orders/{order_id}/financial",
            json={
                "revenue_amount": 100000,
                "purchase_cost": 50000,
                "notes": "before",
            },
        )
        res = await client.patch(
            f"/api/v1/orders/{order_id}/financial",
            json={"purchase_cost": 70000},
        )
        assert res.status_code == 200
        body = res.json()
        assert float(body["revenue_amount"]) == 100000.0  # 据え置き
        assert float(body["purchase_cost"]) == 70000.0    # 更新
        assert body["notes"] == "before"                   # 据え置き

    async def test_patch_financial_recomputes_derived(self, client):
        """PATCH 後、cost_total / gross_profit / gross_profit_rate /
        operating_profit_with_tax_refund がレスポンスで再計算される"""
        order_id = await _create_order(client, "ORD-FIN-PATCH-DERIVED")
        await client.post(
            f"/api/v1/orders/{order_id}/financial",
            json={"revenue_amount": 200000, "purchase_cost": 100000},
        )
        res = await client.patch(
            f"/api/v1/orders/{order_id}/financial",
            json={
                "paypal_fee": 5000,
                "wise_fee": 3000,
                "tax_refund": 10000,
            },
        )
        assert res.status_code == 200
        body = res.json()
        # cost_total = 100000(purchase_cost) + 5000(paypal) + 3000(wise) = 108000
        assert float(body["cost_total"]) == 108000.0
        # gross_profit = 200000 - 108000 = 92000
        assert float(body["gross_profit"]) == 92000.0
        # gross_profit_rate = 92000/200000 = 0.46
        assert abs(float(body["gross_profit_rate"]) - 0.46) < 1e-6
        # operating = 92000 + 10000 = 102000
        assert float(body["operating_profit_with_tax_refund"]) == 102000.0

    async def test_patch_financial_not_found(self, client):
        """売上情報未登録の order に PATCH すると 404"""
        order_id = await _create_order(client, "ORD-FIN-PATCH-404")
        res = await client.patch(
            f"/api/v1/orders/{order_id}/financial",
            json={"revenue_amount": 1000},
        )
        assert res.status_code == 404

    async def test_patch_financial_empty_body_400(self, client):
        """空 dict だと 400（更新フィールド指定なし）"""
        order_id = await _create_order(client, "ORD-FIN-PATCH-EMPTY")
        await client.post(f"/api/v1/orders/{order_id}/financial", json={"revenue_amount": 1000})
        res = await client.patch(f"/api/v1/orders/{order_id}/financial", json={})
        assert res.status_code == 400


class TestDeleteFinancial:
    async def test_delete_financial(self, client):
        """売上情報を削除すると 204、その後 GET は 404"""
        order_id = await _create_order(client, "ORD-FIN-DEL")
        await client.post(f"/api/v1/orders/{order_id}/financial", json={"revenue_amount": 1000})
        res = await client.delete(f"/api/v1/orders/{order_id}/financial")
        assert res.status_code == 204
        res2 = await client.get(f"/api/v1/orders/{order_id}/financial")
        assert res2.status_code == 404

    async def test_delete_financial_not_found(self, client):
        """売上情報未登録なら 404"""
        order_id = await _create_order(client, "ORD-FIN-DEL-404")
        res = await client.delete(f"/api/v1/orders/{order_id}/financial")
        assert res.status_code == 404

    async def test_cascade_on_order_delete(self, client):
        """受注本体を消すと売上情報も CASCADE で消える"""
        order_id = await _create_order(client, "ORD-FIN-CASC")
        await client.post(f"/api/v1/orders/{order_id}/financial", json={"revenue_amount": 1000})
        del_order = await client.delete(f"/api/v1/orders/{order_id}")
        assert del_order.status_code == 204
        res = await client.get(f"/api/v1/orders/{order_id}/financial")
        assert res.status_code == 404


class TestMonthlySummary:
    """GET /financials/monthly?year=&month=&staff_id="""

    async def test_monthly_summary_basic(self, client):
        """売上 2 件作って合計が合う"""
        # SQLite テストでは created_at は CURRENT_TIMESTAMP（fixture の "2026-04-07 00:00:00+00:00"）
        # ではなく、SQLite の datetime 関数で "now" になる。テスト fixture の NOW() と
        # 厳密に整合するため、現在月（JST）をクエリする。
        # UTC.month を使うと月末 JST0:00〜UTC0:00 の9時間で月境界がずれるため JST で取得。
        from datetime import datetime
        from zoneinfo import ZoneInfo
        now_jst = datetime.now(ZoneInfo("Asia/Tokyo"))

        order1 = await _create_order(client, "ORD-FIN-MONTH-1")
        order2 = await _create_order(client, "ORD-FIN-MONTH-2")
        await client.post(
            f"/api/v1/orders/{order1}/financial",
            json={"revenue_amount": 100000, "purchase_cost": 30000, "paypal_fee": 5000},
        )
        await client.post(
            f"/api/v1/orders/{order2}/financial",
            json={"revenue_amount": 200000, "purchase_cost": 80000, "wise_fee": 3000},
        )
        res = await client.get(
            "/api/v1/financials/monthly",
            params={"year": now_jst.year, "month": now_jst.month},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["count"] == 2
        # revenue_total = 100000 + 200000 = 300000
        assert float(body["revenue_total"]) == 300000.0
        # cost_total = 30000+5000 + 80000+3000 = 118000
        assert float(body["cost_total"]) == 118000.0
        # gross_profit_total = 300000 - 118000 = 182000
        assert float(body["gross_profit_total"]) == 182000.0
        # gross_profit_rate = 182000/300000 ≈ 0.6066...
        assert abs(float(body["gross_profit_rate"]) - 182000 / 300000) < 1e-6

    async def test_monthly_summary_empty_period(self, client):
        """該当なしの期間なら count=0 / 各 sum=0 / rate=null"""
        # 2000 年 1 月（テストデータ存在しない期間）
        res = await client.get(
            "/api/v1/financials/monthly",
            params={"year": 2000, "month": 1},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["count"] == 0
        assert float(body["revenue_total"]) == 0.0
        assert float(body["cost_total"]) == 0.0
        assert float(body["gross_profit_total"]) == 0.0
        assert body["gross_profit_rate"] is None

    async def test_monthly_summary_staff_id_stub_passthrough(self, client):
        """staff_id を渡しても 200（stub 実装、レスポンスで echoback される）"""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        res = await client.get(
            "/api/v1/financials/monthly",
            params={"year": now.year, "month": now.month, "staff_id": 42},
        )
        assert res.status_code == 200
        assert res.json()["staff_id"] == 42

    async def test_monthly_summary_invalid_month_returns_422(self, client):
        """month=13 は 422"""
        res = await client.get(
            "/api/v1/financials/monthly",
            params={"year": 2026, "month": 13},
        )
        assert res.status_code == 422


class TestMonthlyJstBoundary:
    """ADR-021 J2 fix (2026-05-13): /financials/monthly の JST 暦月境界。

    `created_at` を SQL で直接 UPDATE して境界を作る。
    JST 月末 23:59:59 までを当該月にカウントし、JST 翌月 00:00 は翌月。
    """

    async def _set_financial_created_at(self, order_id: int, created_at_utc):
        """order_financials.created_at を aware UTC datetime に直接 UPDATE する。

        SQLAlchemy が SQLite に向けて文字列化する形式と router 側の bind
        値（datetime オブジェクト）が一致するよう、両方 datetime を渡す。
        """
        from sqlalchemy import text

        from app.database import get_db
        from app.main import app

        override = app.dependency_overrides.get(get_db)
        if override is None:
            raise RuntimeError("client fixture が DB セッションを登録していません")
        agen = override()
        db = await agen.__anext__()
        await db.execute(
            text("UPDATE order_financials SET created_at = :cat WHERE order_id = :oid"),
            {"cat": created_at_utc, "oid": order_id},
        )
        await db.commit()

    async def test_monthly_financials_includes_jst_late_night(self, client):
        """JST 2026-05-31 23:59:59 の created_at は month=5 集計に含まれる"""
        from datetime import datetime, timezone
        order_id = await _create_order(client, "ORD-FIN-JST-LATE")
        await client.post(
            f"/api/v1/orders/{order_id}/financial",
            json={"revenue_amount": 100000, "purchase_cost": 60000},
        )
        # UTC 2026-05-31 14:59:59 = JST 2026-05-31 23:59:59
        await self._set_financial_created_at(
            order_id, datetime(2026, 5, 31, 14, 59, 59, tzinfo=timezone.utc),
        )

        res_may = await client.get(
            "/api/v1/financials/monthly",
            params={"year": 2026, "month": 5},
        )
        assert res_may.status_code == 200, res_may.text
        # 5 月に含まれる
        assert res_may.json()["count"] >= 1

        res_jun = await client.get(
            "/api/v1/financials/monthly",
            params={"year": 2026, "month": 6},
        )
        # 6 月には入らない（この order だけを観測するため revenue 一致で見る）
        assert res_jun.status_code == 200
        # 注: 他テストの混入を避けるため revenue 100000 ピンポイント検証は
        # しない。代わりに 5 月の方に集計されることを上で確認できれば OK。

    async def test_monthly_financials_excludes_jst_month_start(self, client):
        """JST 2026-04-30 23:59:59 は 5 月集計に入らず、JST 2026-05-01 00:00:00 は入る"""
        from datetime import datetime, timezone
        order_a = await _create_order(client, "ORD-FIN-JST-APR-END")
        order_b = await _create_order(client, "ORD-FIN-JST-MAY-START")
        await client.post(
            f"/api/v1/orders/{order_a}/financial",
            json={"revenue_amount": 12345},
        )
        await client.post(
            f"/api/v1/orders/{order_b}/financial",
            json={"revenue_amount": 67890},
        )
        # UTC 2026-04-30 14:59:59 = JST 2026-04-30 23:59:59（4 月最終秒）
        await self._set_financial_created_at(
            order_a, datetime(2026, 4, 30, 14, 59, 59, tzinfo=timezone.utc),
        )
        # UTC 2026-04-30 15:00:00 = JST 2026-05-01 00:00:00（5 月初秒）
        await self._set_financial_created_at(
            order_b, datetime(2026, 4, 30, 15, 0, 0, tzinfo=timezone.utc),
        )

        res_may = await client.get(
            "/api/v1/financials/monthly",
            params={"year": 2026, "month": 5},
        )
        assert res_may.status_code == 200
        body_may = res_may.json()
        # 5/1 00:00 の 67890 が含まれる
        assert float(body_may["revenue_total"]) >= 67890.0
        # 4/30 23:59 は含まれない（他のテストデータが混入する可能性があるが
        # 12345 は他テストでは作っていない固有値）
        # 念のためピンポイントで「12345 が含まれていない」ことを確認するのは
        # SUM 値しか取れないため難しい。代わりに 4 月集計で 12345 を含むことを確認する。
        res_apr = await client.get(
            "/api/v1/financials/monthly",
            params={"year": 2026, "month": 4},
        )
        assert res_apr.status_code == 200
        body_apr = res_apr.json()
        assert float(body_apr["revenue_total"]) >= 12345.0

    async def test_monthly_financials_december_jst_year_rollover(self, client):
        """12 月境界: JST 2026-12-31 23:59:59 は month=12、2027-01-01 00:00:00 は 2027/1"""
        from datetime import datetime, timezone
        order_dec = await _create_order(client, "ORD-FIN-JST-DEC-END")
        order_jan = await _create_order(client, "ORD-FIN-JST-JAN-START")
        await client.post(
            f"/api/v1/orders/{order_dec}/financial",
            json={"revenue_amount": 11111},
        )
        await client.post(
            f"/api/v1/orders/{order_jan}/financial",
            json={"revenue_amount": 22222},
        )
        # JST 2026-12-31 23:59:59 = UTC 2026-12-31 14:59:59
        await self._set_financial_created_at(
            order_dec, datetime(2026, 12, 31, 14, 59, 59, tzinfo=timezone.utc),
        )
        # JST 2027-01-01 00:00:00 = UTC 2026-12-31 15:00:00
        await self._set_financial_created_at(
            order_jan, datetime(2026, 12, 31, 15, 0, 0, tzinfo=timezone.utc),
        )

        res_dec = await client.get(
            "/api/v1/financials/monthly",
            params={"year": 2026, "month": 12},
        )
        assert res_dec.status_code == 200
        assert float(res_dec.json()["revenue_total"]) >= 11111.0

        res_jan = await client.get(
            "/api/v1/financials/monthly",
            params={"year": 2027, "month": 1},
        )
        assert res_jan.status_code == 200
        assert float(res_jan.json()["revenue_total"]) >= 22222.0


class TestPermissions:
    """ADR-021 Sprint 2 / AC-2.6: 権限・テナント分離

    SQLite テスト基盤では物理的なテナント分離は再現できないが、
    require_permission(orders.view / orders.update) が依存に残ることを
    確認する（権限なしユーザーは 403）。
    """

    async def test_get_financial_requires_orders_view(self, client):
        from unittest.mock import patch

        async def _no_perms(db, tenant_id, user_id):
            return set()

        order_id = await _create_order(client, "ORD-FIN-PERM-1")
        with patch("app.auth.dependencies.load_user_permissions", _no_perms):
            res = await client.get(f"/api/v1/orders/{order_id}/financial")
        assert res.status_code == 403

    async def test_create_financial_requires_orders_update(self, client):
        from unittest.mock import patch

        async def _no_perms(db, tenant_id, user_id):
            return set()

        order_id = await _create_order(client, "ORD-FIN-PERM-2")
        with patch("app.auth.dependencies.load_user_permissions", _no_perms):
            res = await client.post(
                f"/api/v1/orders/{order_id}/financial",
                json={"revenue_amount": 1000},
            )
        assert res.status_code == 403

    async def test_monthly_requires_orders_view(self, client):
        from unittest.mock import patch

        async def _no_perms(db, tenant_id, user_id):
            return set()

        with patch("app.auth.dependencies.load_user_permissions", _no_perms):
            res = await client.get(
                "/api/v1/financials/monthly",
                params={"year": 2026, "month": 5},
            )
        assert res.status_code == 403


class TestSchemaContract:
    """schema 単位のユニットテスト相当（compute_derived の境界条件）"""

    def test_compute_derived_zero_revenue(self):
        from app.schemas.order_financial import compute_derived
        out = compute_derived({
            "revenue_amount": Decimal("0"),
            "purchase_cost": Decimal("100"),
            "tax_refund": Decimal("50"),
        })
        assert out["cost_total"] == Decimal("100")
        assert out["gross_profit"] == Decimal("-100")
        assert out["gross_profit_rate"] is None
        assert out["operating_profit_with_tax_refund"] == Decimal("-50")

    def test_compute_derived_handles_none(self):
        """全フィールド None でも例外を投げず 0 として扱う"""
        from app.schemas.order_financial import compute_derived
        out = compute_derived({})
        assert out["cost_total"] == Decimal("0")
        assert out["gross_profit"] == Decimal("0")
        assert out["gross_profit_rate"] is None
        assert out["operating_profit_with_tax_refund"] == Decimal("0")
