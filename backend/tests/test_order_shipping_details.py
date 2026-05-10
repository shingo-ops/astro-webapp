"""ADR-021 Phase 3 / Sprint 3 — 受注発送情報 API のテスト。

検証対象:
  - POST   /orders/{id}/shipping
  - GET    /orders/{id}/shipping
  - PATCH  /orders/{id}/shipping
  - DELETE /orders/{id}/shipping
  - GET    /orders/{id}/shipping/elogi-csv
  - GET    /shipping/elogi-csv?order_ids=...

eLogi CSV 19 列フォーマット（Config.gs col 56-76 と同じ）の正しさと、
カンマ・改行・ダブルクォート含む値のエスケープも合わせて検証する。
"""

from __future__ import annotations

import csv
from io import StringIO


async def _create_company_contact(client, company_name="発送テスト顧客"):
    co = await client.post("/api/v1/companies", json={"name": company_name})
    company_id = co.json()["id"]
    ct = await client.post("/api/v1/contacts", json={
        "company_id": company_id,
        "display_name": f"{company_name}の担当",
    })
    return company_id, ct.json()["id"]


async def _create_order(client, order_number="ORD-SHIP-1"):
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


class TestCreateShipping:
    async def test_create_shipping_for_order(self, client):
        """発送情報を新規作成できる + 各カラムが保存される"""
        order_id = await _create_order(client, "ORD-SHIP-CREATE-1")
        res = await client.post(
            f"/api/v1/orders/{order_id}/shipping",
            json={
                "recipient_name": "John Smith",
                "phone": "+1-555-1234",
                "email": "john@example.com",
                "address1": "1 Main St",
                "city": "Brooklyn",
                "state_code": "NY",
                "zip_code": "11201",
                "country_code": "US",
                "length_cm": 30.5,
                "width_cm": 20,
                "height_cm": 10.25,
                "weight_kg": 1.234,
                "carrier": "elogi",
                "tracking_number": "EL12345JP",
            },
        )
        assert res.status_code == 201, res.text
        body = res.json()
        assert body["order_id"] == order_id
        assert body["recipient_name"] == "John Smith"
        assert body["country_code"] == "US"
        assert body["carrier"] == "elogi"
        assert body["tracking_number"] == "EL12345JP"
        # NUMERIC は Decimal が JSON 化されると str になる
        assert float(body["weight_kg"]) == 1.234

    async def test_create_shipping_minimal_body(self, client):
        """body 空でも作成できる（全カラム optional のため）"""
        order_id = await _create_order(client, "ORD-SHIP-CREATE-EMPTY")
        res = await client.post(f"/api/v1/orders/{order_id}/shipping", json={})
        assert res.status_code == 201, res.text
        body = res.json()
        assert body["order_id"] == order_id
        assert body["recipient_name"] is None
        assert body["carrier"] is None

    async def test_create_shipping_duplicate_returns_409(self, client):
        """同一 order_id で 2 回 POST すると 409"""
        order_id = await _create_order(client, "ORD-SHIP-DUP")
        first = await client.post(f"/api/v1/orders/{order_id}/shipping", json={"recipient_name": "A"})
        assert first.status_code == 201
        second = await client.post(f"/api/v1/orders/{order_id}/shipping", json={"recipient_name": "B"})
        assert second.status_code == 409

    async def test_create_shipping_unknown_order_returns_404(self, client):
        """存在しない order_id だと 404"""
        res = await client.post("/api/v1/orders/999999/shipping", json={"recipient_name": "X"})
        assert res.status_code == 404

    async def test_create_shipping_invalid_carrier_returns_422(self, client):
        """carrier が enum 外なら 422（Pydantic Literal で弾かれる）"""
        order_id = await _create_order(client, "ORD-SHIP-BADCARRIER")
        res = await client.post(
            f"/api/v1/orders/{order_id}/shipping",
            json={"carrier": "ups"},
        )
        assert res.status_code == 422

    async def test_create_shipping_negative_weight_returns_422(self, client):
        """負の重量は 422"""
        order_id = await _create_order(client, "ORD-SHIP-NEG")
        res = await client.post(
            f"/api/v1/orders/{order_id}/shipping",
            json={"weight_kg": -1.0},
        )
        assert res.status_code == 422


class TestGetShipping:
    async def test_get_shipping(self, client):
        order_id = await _create_order(client, "ORD-SHIP-GET-1")
        await client.post(
            f"/api/v1/orders/{order_id}/shipping",
            json={"recipient_name": "Alice", "carrier": "elogi"},
        )
        res = await client.get(f"/api/v1/orders/{order_id}/shipping")
        assert res.status_code == 200
        body = res.json()
        assert body["recipient_name"] == "Alice"
        assert body["carrier"] == "elogi"

    async def test_get_shipping_not_found(self, client):
        order_id = await _create_order(client, "ORD-SHIP-GET-404")
        res = await client.get(f"/api/v1/orders/{order_id}/shipping")
        assert res.status_code == 404


class TestPatchShipping:
    async def test_patch_shipping_partial(self, client):
        order_id = await _create_order(client, "ORD-SHIP-PATCH-1")
        await client.post(
            f"/api/v1/orders/{order_id}/shipping",
            json={"recipient_name": "Old", "tracking_number": ""},
        )
        res = await client.patch(
            f"/api/v1/orders/{order_id}/shipping",
            json={"tracking_number": "EL999"},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["recipient_name"] == "Old"  # 据え置き
        assert body["tracking_number"] == "EL999"  # 更新

    async def test_patch_shipping_clear_with_null(self, client):
        """明示的に null を渡すとフィールドがクリアされる"""
        order_id = await _create_order(client, "ORD-SHIP-PATCH-NULL")
        await client.post(
            f"/api/v1/orders/{order_id}/shipping",
            json={"tracking_number": "EL111"},
        )
        res = await client.patch(
            f"/api/v1/orders/{order_id}/shipping",
            json={"tracking_number": None},
        )
        assert res.status_code == 200
        assert res.json()["tracking_number"] is None

    async def test_patch_shipping_not_found(self, client):
        order_id = await _create_order(client, "ORD-SHIP-PATCH-404")
        res = await client.patch(
            f"/api/v1/orders/{order_id}/shipping",
            json={"recipient_name": "X"},
        )
        assert res.status_code == 404

    async def test_patch_shipping_empty_body_400(self, client):
        order_id = await _create_order(client, "ORD-SHIP-PATCH-EMPTY")
        await client.post(f"/api/v1/orders/{order_id}/shipping", json={"recipient_name": "X"})
        res = await client.patch(f"/api/v1/orders/{order_id}/shipping", json={})
        assert res.status_code == 400


class TestDeleteShipping:
    async def test_delete_shipping(self, client):
        order_id = await _create_order(client, "ORD-SHIP-DEL")
        await client.post(f"/api/v1/orders/{order_id}/shipping", json={"recipient_name": "X"})
        res = await client.delete(f"/api/v1/orders/{order_id}/shipping")
        assert res.status_code == 204
        res2 = await client.get(f"/api/v1/orders/{order_id}/shipping")
        assert res2.status_code == 404

    async def test_delete_shipping_not_found(self, client):
        order_id = await _create_order(client, "ORD-SHIP-DEL-404")
        res = await client.delete(f"/api/v1/orders/{order_id}/shipping")
        assert res.status_code == 404

    async def test_cascade_on_order_delete(self, client):
        """受注本体を消すと発送情報も CASCADE で消える"""
        order_id = await _create_order(client, "ORD-SHIP-CASC")
        await client.post(f"/api/v1/orders/{order_id}/shipping", json={"recipient_name": "X"})
        del_order = await client.delete(f"/api/v1/orders/{order_id}")
        assert del_order.status_code == 204
        res = await client.get(f"/api/v1/orders/{order_id}/shipping")
        assert res.status_code == 404


# ---------------------------------------------------------------------------
# eLogi CSV
# ---------------------------------------------------------------------------


class TestElogiCsvSingle:
    async def test_single_csv_returns_19_columns(self, client):
        """単一 CSV は ヘッダ 1 行 + データ 1 行で 19 列"""
        order_id = await _create_order(client, "ORD-SHIP-CSV-1")
        await client.post(
            f"/api/v1/orders/{order_id}/shipping",
            json={
                "recipient_name": "Recipient A",
                "phone": "+81-3-1111-2222",
                "email": "a@example.com",
                "country_code": "JP",
                "state_code": "13",
                "city": "Tokyo",
                "zip_code": "100-0001",
                "address1": "1-1 Marunouchi",
            },
        )
        res = await client.get(f"/api/v1/orders/{order_id}/shipping/elogi-csv")
        assert res.status_code == 200
        assert res.headers["content-type"].startswith("text/csv")
        body = res.text
        rows = list(csv.reader(StringIO(body)))
        assert len(rows) == 2  # ヘッダ + データ
        header, data = rows
        assert len(header) == 19
        assert header[0] == "TIMESTAMP"
        assert header[3] == "ORDER_NO"
        assert header[18] == "ADDRESS2_1"
        # ORDER_NO がデータ行に出ている
        assert data[3] == "ORD-SHIP-CSV-1"
        # 受取人 / 国 / 州 / 市 / ZIP / 住所
        assert data[11] == "Recipient A"
        assert data[14] == "JP"
        assert data[15] == "13"
        assert data[16] == "Tokyo"
        assert data[17] == "100-0001"
        assert data[18] == "1-1 Marunouchi"

    async def test_single_csv_without_shipping_row(self, client):
        """発送情報未登録でも受注があれば CSV を返す（多くの列が空）"""
        order_id = await _create_order(client, "ORD-SHIP-CSV-NOSHIP")
        res = await client.get(f"/api/v1/orders/{order_id}/shipping/elogi-csv")
        assert res.status_code == 200
        rows = list(csv.reader(StringIO(res.text)))
        assert len(rows) == 2
        assert rows[1][3] == "ORD-SHIP-CSV-NOSHIP"
        # 発送情報が無いので受取人は空
        assert rows[1][11] == ""

    async def test_single_csv_unknown_order_returns_404(self, client):
        res = await client.get("/api/v1/orders/999999/shipping/elogi-csv")
        assert res.status_code == 404


class TestElogiCsvBulk:
    async def test_bulk_csv_returns_n_rows(self, client):
        """複数受注を bulk export できる（ヘッダ + N 行）"""
        ids: list[int] = []
        for i in range(3):
            oid = await _create_order(client, f"ORD-SHIP-BULK-{i}")
            await client.post(
                f"/api/v1/orders/{oid}/shipping",
                json={"recipient_name": f"R{i}", "country_code": "US"},
            )
            ids.append(oid)
        param = ",".join(str(i) for i in ids)
        res = await client.get(f"/api/v1/shipping/elogi-csv?order_ids={param}")
        assert res.status_code == 200
        rows = list(csv.reader(StringIO(res.text)))
        assert len(rows) == 4  # ヘッダ + 3 行
        # ORDER_NO 列の順序確認
        order_nos = [r[3] for r in rows[1:]]
        assert order_nos == [f"ORD-SHIP-BULK-{i}" for i in range(3)]

    async def test_bulk_csv_skips_missing_ids(self, client):
        """存在しない id は黙ってスキップ（残りは出力）"""
        oid = await _create_order(client, "ORD-SHIP-BULK-A")
        await client.post(
            f"/api/v1/orders/{oid}/shipping",
            json={"recipient_name": "Alpha"},
        )
        res = await client.get(f"/api/v1/shipping/elogi-csv?order_ids={oid},9999999")
        assert res.status_code == 200
        rows = list(csv.reader(StringIO(res.text)))
        assert len(rows) == 2  # ヘッダ + 1 行（実在するもの）
        assert rows[1][3] == "ORD-SHIP-BULK-A"

    async def test_bulk_csv_all_missing_returns_404(self, client):
        res = await client.get("/api/v1/shipping/elogi-csv?order_ids=999991,999992")
        assert res.status_code == 404

    async def test_bulk_csv_invalid_id_returns_400(self, client):
        res = await client.get("/api/v1/shipping/elogi-csv?order_ids=1,abc")
        assert res.status_code == 400

    async def test_bulk_csv_empty_returns_400(self, client):
        res = await client.get("/api/v1/shipping/elogi-csv?order_ids=,,,")
        assert res.status_code == 400


class TestCsvEscape:
    async def test_csv_escapes_comma_quote_and_newline(self, client):
        """カンマ / ダブルクォート / 改行を含む値が破綻せず csv モジュールで再パースできる"""
        order_id = await _create_order(client, "ORD-SHIP-CSV-ESC")
        nasty_addr = 'Line1, "Quoted"\nLine2'
        nasty_recipient = 'Smith, "Jr."'
        await client.post(
            f"/api/v1/orders/{order_id}/shipping",
            json={
                "recipient_name": nasty_recipient,
                "address1": nasty_addr,
                "city": "Plain",
            },
        )
        res = await client.get(f"/api/v1/orders/{order_id}/shipping/elogi-csv")
        assert res.status_code == 200
        # csv モジュールで parse できれば OK（quote / 改行が崩れていないことを保証）
        rows = list(csv.reader(StringIO(res.text)))
        assert len(rows) == 2
        data = rows[1]
        assert data[11] == nasty_recipient
        assert data[18] == nasty_addr
        assert data[16] == "Plain"


# ---------------------------------------------------------------------------
# 権限・テナント分離
# ---------------------------------------------------------------------------


class TestPermissions:
    """ADR-021 Sprint 3 / AC-3.6: 権限・テナント分離

    SQLite テスト基盤では物理的なテナント分離は再現できないが、
    require_permission(orders.view / orders.update) が依存に残ることを
    確認する（権限なしユーザーは 403）。
    """

    async def test_get_shipping_requires_orders_view(self, client):
        from unittest.mock import patch

        async def _no_perms(db, tenant_id, user_id):
            return set()

        order_id = await _create_order(client, "ORD-SHIP-PERM-GET")
        with patch("app.auth.dependencies.load_user_permissions", _no_perms):
            res = await client.get(f"/api/v1/orders/{order_id}/shipping")
        assert res.status_code == 403

    async def test_create_shipping_requires_orders_update(self, client):
        from unittest.mock import patch

        async def _no_perms(db, tenant_id, user_id):
            return set()

        order_id = await _create_order(client, "ORD-SHIP-PERM-POST")
        with patch("app.auth.dependencies.load_user_permissions", _no_perms):
            res = await client.post(
                f"/api/v1/orders/{order_id}/shipping",
                json={"recipient_name": "X"},
            )
        assert res.status_code == 403

    async def test_csv_export_requires_orders_view(self, client):
        from unittest.mock import patch

        async def _no_perms(db, tenant_id, user_id):
            return set()

        order_id = await _create_order(client, "ORD-SHIP-PERM-CSV")
        with patch("app.auth.dependencies.load_user_permissions", _no_perms):
            res = await client.get(f"/api/v1/orders/{order_id}/shipping/elogi-csv")
        assert res.status_code == 403

    async def test_bulk_csv_requires_orders_view(self, client):
        from unittest.mock import patch

        async def _no_perms(db, tenant_id, user_id):
            return set()

        oid = await _create_order(client, "ORD-SHIP-PERM-BULK")
        with patch("app.auth.dependencies.load_user_permissions", _no_perms):
            res = await client.get(f"/api/v1/shipping/elogi-csv?order_ids={oid}")
        assert res.status_code == 403


# ---------------------------------------------------------------------------
# adapter ユニット相当
# ---------------------------------------------------------------------------


class TestAdapterUnit:
    """eLogi adapter の境界条件（DB を経由しないユニット相当）"""

    def test_elogi_adapter_header_is_19_cols(self):
        from app.services.shipping_carriers import get_adapter
        adapter = get_adapter("elogi")
        cols = adapter.header_columns()
        assert len(cols) == 19
        assert cols[0] == "TIMESTAMP"
        assert cols[18] == "ADDRESS2_1"

    def test_elogi_adapter_handles_empty_orders(self):
        """0 件の入力でもヘッダ 1 行は返る"""
        from app.services.shipping_carriers import get_adapter
        adapter = get_adapter("elogi")
        text = adapter.to_csv_text([])
        rows = list(csv.reader(StringIO(text)))
        assert len(rows) == 1
        assert rows[0][0] == "TIMESTAMP"

    def test_unknown_adapter_raises(self):
        from app.services.shipping_carriers import get_adapter
        try:
            get_adapter("ups")
        except KeyError:
            return
        raise AssertionError("KeyError not raised for unknown adapter")

    def test_registry_rejects_duplicate(self):
        """同じカリアコードを 2 回 register すると ValueError"""
        from app.services.shipping_carriers import register_adapter
        from app.services.shipping_carriers.elogi import ElogiCsvAdapter
        try:
            register_adapter(ElogiCsvAdapter())
        except ValueError:
            return
        raise AssertionError("ValueError not raised for duplicate carrier code")
