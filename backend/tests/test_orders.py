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
            "status": "awaiting_payment",
        })
        assert res.status_code == 201
        data = res.json()
        assert data["order_number"] == "ORD-001"
        assert float(data["total_amount"]) == 500000.0
        assert data["status"] == "awaiting_payment"
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
            "status": "awaiting_payment",
        })
        await client.post("/api/v1/orders", json={
            "company_id": company_id, "contact_id": contact_id,
            "order_number": "ORD-SHIP",
            "status": "awaiting_shipping",
        })

        res = await client.get("/api/v1/orders", params={"status": "awaiting_payment"})
        assert res.status_code == 200
        assert all(o["status"] == "awaiting_payment" for o in res.json())

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
            "status": "awaiting_shipping",
        })
        assert res.status_code == 200
        assert res.json()["status"] == "awaiting_shipping"

    async def test_update_order_with_amount_and_status(self, client):
        """Decimal(total_amount)とEnum(status)を同時更新できる（asyncpg encoder対策の回帰テスト）"""
        company_id, contact_id = await _create_company_contact(client)
        create_res = await client.post("/api/v1/orders", json={
            "company_id": company_id, "contact_id": contact_id,
            "order_number": "ORD-UPD-FULL",
        })
        order_id = create_res.json()["id"]

        res = await client.patch(f"/api/v1/orders/{order_id}", json={
            "status": "sourcing",
            "total_amount": 50000,
            "notes": "備考更新",
        })
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "sourcing"
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


class TestOrdersListSearchSort:
    """ADR-021 Sprint 1: GET /orders の search / sort / JOIN 拡張"""

    async def test_list_orders_search_by_order_number(self, client):
        """search で order_number 部分一致できる"""
        company_id, contact_id = await _create_company_contact(client)
        await client.post("/api/v1/orders", json={
            "company_id": company_id, "contact_id": contact_id,
            "order_number": "ORD-ALPHA-001",
        })
        await client.post("/api/v1/orders", json={
            "company_id": company_id, "contact_id": contact_id,
            "order_number": "ORD-BRAVO-002",
        })

        res = await client.get("/api/v1/orders", params={"search": "ALPHA"})
        assert res.status_code == 200
        body = res.json()
        numbers = {o["order_number"] for o in body}
        assert "ORD-ALPHA-001" in numbers
        assert "ORD-BRAVO-002" not in numbers

    async def test_list_orders_search_by_company_name(self, client):
        """search で company.name 部分一致できる"""
        co_a, ct_a = await _create_company_contact(client, "アルファ商事")
        co_b, ct_b = await _create_company_contact(client, "ベータ工業")
        await client.post("/api/v1/orders", json={
            "company_id": co_a, "contact_id": ct_a,
            "order_number": "ORD-CO-SEARCH-A",
        })
        await client.post("/api/v1/orders", json={
            "company_id": co_b, "contact_id": ct_b,
            "order_number": "ORD-CO-SEARCH-B",
        })

        res = await client.get("/api/v1/orders", params={"search": "アルファ"})
        assert res.status_code == 200
        body = res.json()
        numbers = {o["order_number"] for o in body}
        assert "ORD-CO-SEARCH-A" in numbers
        assert "ORD-CO-SEARCH-B" not in numbers

    async def test_list_orders_search_by_contact_display_name(self, client):
        """search で contact.display_name 部分一致できる"""
        co_a, ct_a = await _create_company_contact(client, "DisplayCoA")
        co_b, ct_b = await _create_company_contact(client, "DisplayCoB")
        await client.post("/api/v1/orders", json={
            "company_id": co_a, "contact_id": ct_a,
            "order_number": "ORD-CT-A",
        })
        await client.post("/api/v1/orders", json={
            "company_id": co_b, "contact_id": ct_b,
            "order_number": "ORD-CT-B",
        })
        # _create_company_contact のヘルパーは display_name = "{company_name}の担当"
        # を生成するので、"DisplayCoA" を search すれば ct_a 行のみがヒットする
        res = await client.get("/api/v1/orders", params={"search": "DisplayCoAの担当"})
        assert res.status_code == 200
        body = res.json()
        numbers = {o["order_number"] for o in body}
        assert "ORD-CT-A" in numbers
        assert "ORD-CT-B" not in numbers

    async def test_list_orders_search_blank_returns_all(self, client):
        """search が空白のみは無視され全件返る"""
        company_id, contact_id = await _create_company_contact(client)
        await client.post("/api/v1/orders", json={
            "company_id": company_id, "contact_id": contact_id,
            "order_number": "ORD-BLANK-1",
        })

        res = await client.get("/api/v1/orders", params={"search": "   "})
        assert res.status_code == 200
        assert any(o["order_number"] == "ORD-BLANK-1" for o in res.json())

    async def test_list_orders_search_special_chars_escaped(self, client):
        """LIKE メタ文字 (%, _) はエスケープされ、リテラル一致になる"""
        company_id, contact_id = await _create_company_contact(client, "EscapeCo")
        await client.post("/api/v1/orders", json={
            "company_id": company_id, "contact_id": contact_id,
            "order_number": "ORD-NORMAL-1",
        })
        # "%" を search に含めても他レコードに勝手にマッチしないこと
        res = await client.get("/api/v1/orders", params={"search": "%"})
        assert res.status_code == 200
        # "%" を含む order_number は存在しないので空のはず
        numbers = {o["order_number"] for o in res.json()}
        assert "ORD-NORMAL-1" not in numbers

    async def test_list_orders_sort_by_total_amount_desc(self, client):
        """total_amount で降順ソートできる"""
        company_id, contact_id = await _create_company_contact(client)
        await client.post("/api/v1/orders", json={
            "company_id": company_id, "contact_id": contact_id,
            "order_number": "ORD-SORT-LOW", "total_amount": 1000,
        })
        await client.post("/api/v1/orders", json={
            "company_id": company_id, "contact_id": contact_id,
            "order_number": "ORD-SORT-HIGH", "total_amount": 999999,
        })
        await client.post("/api/v1/orders", json={
            "company_id": company_id, "contact_id": contact_id,
            "order_number": "ORD-SORT-MID", "total_amount": 50000,
        })

        res = await client.get(
            "/api/v1/orders",
            params={"sort_by": "total_amount", "sort_order": "desc"},
        )
        assert res.status_code == 200
        body = res.json()
        # 該当 3 件のみ抽出
        ours = [o for o in body if o["order_number"].startswith("ORD-SORT-")]
        assert [o["order_number"] for o in ours[:3]] == [
            "ORD-SORT-HIGH", "ORD-SORT-MID", "ORD-SORT-LOW",
        ]

    async def test_list_orders_sort_by_total_amount_asc(self, client):
        """total_amount で昇順ソートできる"""
        company_id, contact_id = await _create_company_contact(client)
        await client.post("/api/v1/orders", json={
            "company_id": company_id, "contact_id": contact_id,
            "order_number": "ORD-ASC-A", "total_amount": 5000,
        })
        await client.post("/api/v1/orders", json={
            "company_id": company_id, "contact_id": contact_id,
            "order_number": "ORD-ASC-B", "total_amount": 100,
        })
        res = await client.get(
            "/api/v1/orders",
            params={"sort_by": "total_amount", "sort_order": "asc"},
        )
        assert res.status_code == 200
        ours = [o for o in res.json() if o["order_number"].startswith("ORD-ASC-")]
        assert [o["order_number"] for o in ours[:2]] == ["ORD-ASC-B", "ORD-ASC-A"]

    async def test_list_orders_sort_by_status(self, client):
        """status でソートできる（文字列辞書順）"""
        company_id, contact_id = await _create_company_contact(client)
        await client.post("/api/v1/orders", json={
            "company_id": company_id, "contact_id": contact_id,
            "order_number": "ORD-ST-PEND", "status": "awaiting_payment",
        })
        await client.post("/api/v1/orders", json={
            "company_id": company_id, "contact_id": contact_id,
            "order_number": "ORD-ST-DEL", "status": "completed",
        })

        res = await client.get(
            "/api/v1/orders",
            params={"sort_by": "status", "sort_order": "asc"},
        )
        assert res.status_code == 200
        ours = [o for o in res.json() if o["order_number"].startswith("ORD-ST-")]
        statuses = [o["status"] for o in ours]
        # ascending order: delivered < pending（辞書順）
        assert statuses == sorted(statuses)

    async def test_list_orders_invalid_sort_by_returns_400(self, client):
        """ホワイトリスト外の sort_by は 400"""
        res = await client.get(
            "/api/v1/orders",
            params={"sort_by": "evil_column; DROP TABLE orders;"},
        )
        assert res.status_code == 400

    async def test_list_orders_invalid_sort_order_returns_400(self, client):
        """ホワイトリスト外の sort_order は 400"""
        res = await client.get(
            "/api/v1/orders",
            params={"sort_order": "shuffle"},
        )
        assert res.status_code == 400

    async def test_list_orders_response_includes_company_contact_names(self, client):
        """レスポンスに company_name / contact_display_name が含まれる"""
        company_id, contact_id = await _create_company_contact(client, "JoinTestCo")
        await client.post("/api/v1/orders", json={
            "company_id": company_id, "contact_id": contact_id,
            "order_number": "ORD-JOIN-1",
        })

        res = await client.get("/api/v1/orders", params={"search": "ORD-JOIN-1"})
        assert res.status_code == 200
        body = res.json()
        assert len(body) == 1
        order = body[0]
        assert order["company_name"] == "JoinTestCo"
        assert order["contact_display_name"] == "JoinTestCoの担当"


class TestOrdersGroupCounts:
    """ADR-021 Sprint 1: GET /orders/group-counts"""

    async def test_get_orders_group_counts_basic(self, client):
        """OrderStatus 全値 + total が返る、件数 0 のステータスも 0 で含まれる"""
        company_id, contact_id = await _create_company_contact(client)
        await client.post("/api/v1/orders", json={
            "company_id": company_id, "contact_id": contact_id,
            "order_number": "ORD-GC-1", "status": "awaiting_payment",
        })
        await client.post("/api/v1/orders", json={
            "company_id": company_id, "contact_id": contact_id,
            "order_number": "ORD-GC-2", "status": "awaiting_payment",
        })
        await client.post("/api/v1/orders", json={
            "company_id": company_id, "contact_id": contact_id,
            "order_number": "ORD-GC-3", "status": "awaiting_shipping",
        })

        res = await client.get("/api/v1/orders/group-counts")
        assert res.status_code == 200
        body = res.json()
        assert "counts" in body and "total" in body
        # ADR-021 J1 fix: OrderStatus 6 値が含まれる（件数 0 も）。confirmed は撤去済。
        for s in ["awaiting_payment", "sourcing", "awaiting_shipping",
                  "completed", "trouble", "cancelled"]:
            assert s in body["counts"]
        assert "confirmed" not in body["counts"]
        assert body["counts"]["awaiting_payment"] >= 2
        assert body["counts"]["awaiting_shipping"] >= 1
        # total はカウントの合計と一致
        assert body["total"] == sum(body["counts"].values())

    async def test_get_orders_group_counts_respects_search(self, client):
        """?search= 指定時は集計が連動する"""
        co_a, ct_a = await _create_company_contact(client, "GroupSearchA")
        co_b, ct_b = await _create_company_contact(client, "GroupSearchB")
        await client.post("/api/v1/orders", json={
            "company_id": co_a, "contact_id": ct_a,
            "order_number": "ORD-GS-A1", "status": "awaiting_payment",
        })
        await client.post("/api/v1/orders", json={
            "company_id": co_a, "contact_id": ct_a,
            "order_number": "ORD-GS-A2", "status": "awaiting_payment",
        })
        await client.post("/api/v1/orders", json={
            "company_id": co_b, "contact_id": ct_b,
            "order_number": "ORD-GS-B1", "status": "awaiting_shipping",
        })

        res = await client.get(
            "/api/v1/orders/group-counts",
            params={"search": "GroupSearchA"},
        )
        assert res.status_code == 200
        body = res.json()
        # A 検索なので A 社の 2 件のみ集計対象
        assert body["counts"]["awaiting_payment"] == 2
        assert body["counts"]["awaiting_shipping"] == 0
        assert body["total"] == 2

    async def test_get_orders_group_counts_with_status_filter(self, client):
        """?status= を一緒に指定すると、そのステータスだけ件数が乗る"""
        company_id, contact_id = await _create_company_contact(client)
        await client.post("/api/v1/orders", json={
            "company_id": company_id, "contact_id": contact_id,
            "order_number": "ORD-GCF-1", "status": "awaiting_payment",
        })
        await client.post("/api/v1/orders", json={
            "company_id": company_id, "contact_id": contact_id,
            "order_number": "ORD-GCF-2", "status": "awaiting_shipping",
        })

        res = await client.get(
            "/api/v1/orders/group-counts",
            params={"status": "awaiting_shipping"},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["counts"]["awaiting_payment"] == 0
        assert body["counts"]["awaiting_shipping"] >= 1
        assert body["total"] == body["counts"]["awaiting_shipping"]

    async def test_get_orders_group_counts_empty(self, client):
        """注文が無いテナントでも 200 + 全 0 + total=0 を返す"""
        res = await client.get("/api/v1/orders/group-counts")
        assert res.status_code == 200
        body = res.json()
        assert body["total"] == 0
        # ADR-021 J1 fix: 6 値のみ（confirmed なし）
        for s in ["awaiting_payment", "sourcing", "awaiting_shipping",
                  "completed", "trouble", "cancelled"]:
            assert body["counts"][s] == 0
        assert "confirmed" not in body["counts"]


class TestOrdersListMultiTenant:
    """ADR-021 Sprint 1: マルチテナント分離（AC-1.10）

    本番 PostgreSQL では `get_current_tenant` が search_path をテナント
    スキーマ (tenant_NNN) に切替えるため、orders / companies / contacts は
    自テナントのレコードしか見えない（物理分離）。

    SQLite テスト基盤は単一スキーマなので物理分離のシミュレーションは
    できないが、以下を回帰検証する:
      1. require_permission("orders.view") が JOIN 拡張後も依存に残っている
      2. JOIN 後も orders.view 権限なしユーザーは 403 が返る
    """

    async def test_list_orders_requires_orders_view_permission(self, client):
        """orders.view 権限なしユーザーは 403 を返す（JOIN 拡張後も維持）"""
        from unittest.mock import patch

        async def _no_perms(db, tenant_id, user_id):
            return set()

        with patch("app.auth.dependencies.load_user_permissions", _no_perms):
            res = await client.get("/api/v1/orders")
        assert res.status_code == 403

    async def test_get_orders_group_counts_requires_orders_view_permission(self, client):
        """group-counts も orders.view 権限を要求する"""
        from unittest.mock import patch

        async def _no_perms(db, tenant_id, user_id):
            return set()

        with patch("app.auth.dependencies.load_user_permissions", _no_perms):
            res = await client.get("/api/v1/orders/group-counts")
        assert res.status_code == 403


class TestOrderStatusSixValues:
    """ADR-021 J1 fix (2026-05-13): OrderStatus 6 値化の回帰テスト。

    互換性のため Sprint 1 で一時的に残していた `confirmed` を撤去した。
    旧 confirmed 行は migration 051 で `pending` に統合される。
    """

    async def test_order_status_enum_contains_exactly_six_values(self):
        """OrderStatus enum は 6 値（confirmed を含まない）"""
        from app.schemas.order import OrderStatus
        values = {s.value for s in OrderStatus}
        assert values == {
            "awaiting_payment", "sourcing", "awaiting_shipping",
            "completed", "trouble", "cancelled",
        }
        assert "confirmed" not in values

    async def test_create_order_rejects_confirmed_status(self, client):
        """POST /orders で status='confirmed' は 422（Pydantic enum 違反）"""
        company_id, contact_id = await _create_company_contact(client)
        res = await client.post("/api/v1/orders", json={
            "company_id": company_id, "contact_id": contact_id,
            "order_number": "ORD-J1-REJ",
            "status": "confirmed",
        })
        assert res.status_code == 422

    async def test_update_order_rejects_confirmed_status(self, client):
        """PATCH /orders/{id} で status='confirmed' も 422"""
        company_id, contact_id = await _create_company_contact(client)
        cre = await client.post("/api/v1/orders", json={
            "company_id": company_id, "contact_id": contact_id,
            "order_number": "ORD-J1-PATCH-REJ",
        })
        order_id = cre.json()["id"]
        res = await client.patch(f"/api/v1/orders/{order_id}", json={
            "status": "confirmed",
        })
        assert res.status_code == 422

    async def test_status_filter_rejects_confirmed(self, client):
        """GET /orders?status=confirmed は 400 で許可値 6 個を含むメッセージ"""
        res = await client.get("/api/v1/orders", params={"status": "confirmed"})
        assert res.status_code == 400
        detail = res.json()["detail"]
        # 許可値 6 個が detail に列挙されている
        assert "awaiting_payment" in detail
        assert "sourcing" in detail
        assert "awaiting_shipping" in detail
        assert "completed" in detail
        assert "trouble" in detail
        assert "cancelled" in detail

    async def test_status_filter_accepts_pending(self, client):
        """GET /orders?status=pending は 200 を返す（whitelist 通過）"""
        res = await client.get("/api/v1/orders", params={"status": "awaiting_payment"})
        assert res.status_code == 200

    async def test_group_counts_excludes_confirmed_key(self, client):
        """GET /orders/group-counts の counts キーに confirmed が含まれない"""
        res = await client.get("/api/v1/orders/group-counts")
        assert res.status_code == 200
        counts = res.json()["counts"]
        assert "confirmed" not in counts
        # 正本 6 値はすべて含まれる（件数 0 でも 0 埋め）
        assert set(counts.keys()) >= {
            "awaiting_payment", "sourcing", "awaiting_shipping",
            "completed", "trouble", "cancelled",
        }

    async def test_group_counts_filter_with_confirmed_returns_400(self, client):
        """GET /orders/group-counts?status=confirmed も 400 で reject"""
        res = await client.get(
            "/api/v1/orders/group-counts", params={"status": "confirmed"},
        )
        assert res.status_code == 400


class TestOrderResponseSchema:
    """OrderResponse の堅牢性（後発テナントの NULL contact_id 行）。"""

    def _row(self, **overrides):
        from datetime import datetime

        row = {
            "id": 1,
            "company_id": 10,
            "contact_id": 20,
            "deal_id": None,
            "invoice_id": None,
            "order_number": "O-001",
            "total_amount": None,
            "currency": None,
            "status": "pending",
            "shipping_carrier": None,
            "shipping_fee": None,
            "tracking_number": None,
            "shipped_at": None,
            "delivered_at": None,
            "shipping_country": None,
            "notes": None,
            "created_at": datetime(2026, 1, 1, 0, 0, 0),
            "updated_at": datetime(2026, 1, 1, 0, 0, 0),
        }
        row.update(overrides)
        return row

    def test_contact_id_null_does_not_raise(self):
        """tenant_006 等の NULL contact_id 行で GET /orders が 500 にならないこと。"""
        from app.schemas.order import OrderResponse

        resp = OrderResponse(**self._row(contact_id=None))
        assert resp.contact_id is None
        assert resp.company_id == 10

    def test_contact_id_present_still_valid(self):
        from app.schemas.order import OrderResponse

        assert OrderResponse(**self._row(contact_id=20)).contact_id == 20
