"""
顧客管理API（customers）のテスト。Phase 1 再設計版。

本体 + 3副テーブル（customer_addresses / customer_sales_channels / customer_discord）
のネスト構造に対応するテストケース。
"""

import pytest


class TestCustomerDeleteConstraint:
    """顧客削除時のFK保護"""

    async def test_delete_customer_with_deal_returns_409(self, client):
        """関連商談がある顧客は削除できず、409とわかりやすいメッセージを返す"""
        cust = await client.post(
            "/api/v1/customers",
            json={"company_name": "関連データ付き顧客"},
        )
        customer_id = cust.json()["id"]
        await client.post("/api/v1/deals", json={"customer_id": customer_id, "title": "関連商談"})

        res = await client.delete(f"/api/v1/customers/{customer_id}")
        assert res.status_code == 409
        assert "関連" in res.json()["detail"]


class TestCustomersCRUD:
    """顧客の作成・取得・更新・削除"""

    async def test_create_customer_with_nested_address(self, client):
        """顧客をネスト構造（addresses配列）で新規作成できる"""
        res = await client.post("/api/v1/customers", json={
            "company_name": "山田商事",
            "billing_display_name": "山田太郎",
            "primary_contact_channel": "whatsapp",
            "addresses": [
                {
                    "address_type": "billing",
                    "name": "山田太郎",
                    "email": "yamada@example.com",
                    "telephone": "+819012345678",
                    "country_code": "JP",
                },
                {
                    "address_type": "delivery",
                    "name": "山田太郎（配送先）",
                    "country_code": "JP",
                },
            ],
            "sales_channels": ["EC", "実店舗"],
        })
        assert res.status_code == 201
        data = res.json()
        assert data["company_name"] == "山田商事"
        assert data["billing_display_name"] == "山田太郎"
        assert data["customer_code"].startswith("CT-")  # 自動採番
        assert len(data["addresses"]) == 2
        billing = next(a for a in data["addresses"] if a["address_type"] == "billing")
        assert billing["email"] == "yamada@example.com"
        assert billing["country_code"] == "JP"
        assert set(data["sales_channels"]) == {"EC", "実店舗"}
        assert data["discord"] is None

    async def test_create_customer_minimal(self, client):
        """会社名だけで顧客を作成できる（副テーブル全て空）"""
        res = await client.post("/api/v1/customers", json={"company_name": "佐藤花子事務所"})
        assert res.status_code == 201
        data = res.json()
        assert data["company_name"] == "佐藤花子事務所"
        assert data["addresses"] == []
        assert data["sales_channels"] == []
        assert data["discord"] is None
        # customer_code は自動採番
        assert data["customer_code"] and data["customer_code"].startswith("CT-")

    async def test_create_customer_with_discord(self, client):
        """Discord 連携情報を含めて作成できる"""
        res = await client.post("/api/v1/customers", json={
            "company_name": "Discord顧客",
            "discord": {
                "is_joined": True,
                "channel_id": "1234567890",
                "user_id": "0987654321",
                "invoice_webhook": "https://discord.com/api/webhooks/xxx/yyy",
            },
        })
        assert res.status_code == 201
        data = res.json()
        assert data["discord"] is not None
        assert data["discord"]["is_joined"] is True
        assert data["discord"]["channel_id"] == "1234567890"

    async def test_create_customer_explicit_code(self, client):
        """明示的な customer_code を指定して作成できる"""
        res = await client.post("/api/v1/customers", json={
            "customer_code": "CT-99999",
            "company_name": "コード指定顧客",
        })
        assert res.status_code == 201
        assert res.json()["customer_code"] == "CT-99999"

    async def test_list_customers(self, client):
        """顧客一覧を取得できる"""
        await client.post("/api/v1/customers", json={"company_name": "顧客A"})
        await client.post("/api/v1/customers", json={"company_name": "顧客B"})

        res = await client.get("/api/v1/customers")
        assert res.status_code == 200
        data = res.json()
        assert len(data) >= 2
        # ネスト構造が返ってくる
        for c in data:
            assert "addresses" in c
            assert "sales_channels" in c
            assert "discord" in c

    async def test_list_customers_pagination(self, client):
        """ページネーションが動作する"""
        for i in range(5):
            await client.post("/api/v1/customers", json={"company_name": f"ページ顧客{i}"})

        res = await client.get("/api/v1/customers", params={"page": 1, "per_page": 2})
        assert res.status_code == 200
        assert len(res.json()) == 2

    async def test_get_customer(self, client):
        """顧客詳細を副テーブル込みで取得できる"""
        create_res = await client.post("/api/v1/customers", json={
            "company_name": "詳細テスト",
            "addresses": [
                {"address_type": "billing", "name": "請求先太郎", "country_code": "JP"},
            ],
            "sales_channels": ["EC"],
        })
        customer_id = create_res.json()["id"]

        res = await client.get(f"/api/v1/customers/{customer_id}")
        assert res.status_code == 200
        data = res.json()
        assert data["company_name"] == "詳細テスト"
        assert len(data["addresses"]) == 1
        assert data["addresses"][0]["name"] == "請求先太郎"
        assert data["sales_channels"] == ["EC"]

    async def test_get_customer_not_found(self, client):
        """存在しない顧客は404"""
        res = await client.get("/api/v1/customers/99999")
        assert res.status_code == 404

    async def test_update_customer_body(self, client):
        """顧客本体情報を部分更新できる"""
        create_res = await client.post("/api/v1/customers", json={
            "company_name": "旧会社",
            "billing_display_name": "旧名義",
        })
        customer_id = create_res.json()["id"]

        res = await client.patch(f"/api/v1/customers/{customer_id}", json={
            "company_name": "新会社",
        })
        assert res.status_code == 200
        data = res.json()
        assert data["company_name"] == "新会社"
        assert data["billing_display_name"] == "旧名義"  # 変更していないフィールドは保持

    async def test_update_customer_addresses_replace(self, client):
        """addresses 配列を新しい内容で置換できる"""
        create_res = await client.post("/api/v1/customers", json={
            "company_name": "住所更新テスト",
            "addresses": [
                {"address_type": "billing", "name": "旧請求先"},
            ],
        })
        customer_id = create_res.json()["id"]

        res = await client.patch(f"/api/v1/customers/{customer_id}", json={
            "addresses": [
                {"address_type": "billing", "name": "新請求先", "country_code": "US"},
                {"address_type": "delivery", "name": "新配送先", "country_code": "US"},
            ],
        })
        assert res.status_code == 200
        addrs = {a["address_type"]: a for a in res.json()["addresses"]}
        assert addrs["billing"]["name"] == "新請求先"
        assert addrs["delivery"]["country_code"] == "US"

    async def test_update_customer_addresses_untouched(self, client):
        """addresses を指定しない PATCH は既存の addresses を保持"""
        create_res = await client.post("/api/v1/customers", json={
            "company_name": "住所据え置きテスト",
            "addresses": [{"address_type": "billing", "name": "保持される"}],
        })
        customer_id = create_res.json()["id"]

        res = await client.patch(f"/api/v1/customers/{customer_id}", json={
            "company_name": "別社名",
        })
        assert res.status_code == 200
        assert len(res.json()["addresses"]) == 1
        assert res.json()["addresses"][0]["name"] == "保持される"

    async def test_update_customer_empty_body(self, client):
        """空のリクエストボディは400"""
        create_res = await client.post("/api/v1/customers", json={"company_name": "空更新テスト"})
        customer_id = create_res.json()["id"]

        res = await client.patch(f"/api/v1/customers/{customer_id}", json={})
        assert res.status_code == 400

    async def test_delete_customer(self, client):
        """顧客を削除できる（副テーブルは CASCADE）"""
        create_res = await client.post("/api/v1/customers", json={
            "company_name": "削除テスト",
            "addresses": [{"address_type": "billing"}],
        })
        customer_id = create_res.json()["id"]

        res = await client.delete(f"/api/v1/customers/{customer_id}")
        assert res.status_code == 204

        # 削除後は404
        res = await client.get(f"/api/v1/customers/{customer_id}")
        assert res.status_code == 404

    async def test_delete_customer_not_found(self, client):
        """存在しない顧客の削除は404"""
        res = await client.delete("/api/v1/customers/99999")
        assert res.status_code == 404


class TestCustomersValidation:
    """顧客バリデーション"""

    async def test_invalid_email_format_in_address(self, client):
        """addresses[].email が不正形式なら422"""
        res = await client.post("/api/v1/customers", json={
            "company_name": "メールテスト",
            "addresses": [
                {"address_type": "billing", "email": "invalid-email"},
            ],
        })
        assert res.status_code == 422

    async def test_invalid_phone_format_in_address(self, client):
        """addresses[].telephone が不正形式なら422"""
        res = await client.post("/api/v1/customers", json={
            "company_name": "電話テスト",
            "addresses": [
                {"address_type": "billing", "telephone": "abc"},
            ],
        })
        assert res.status_code == 422

    async def test_invalid_address_type(self, client):
        """address_type に billing/delivery 以外は422"""
        res = await client.post("/api/v1/customers", json={
            "company_name": "不正タイプ",
            "addresses": [
                {"address_type": "other", "name": "ダメ"},
            ],
        })
        assert res.status_code == 422

    async def test_invalid_trust_level(self, client):
        """trust_level が 1-5 範囲外なら422"""
        res = await client.post("/api/v1/customers", json={
            "company_name": "信頼度テスト",
            "trust_level": 10,
        })
        assert res.status_code == 422

    async def test_invalid_country_code_length(self, client):
        """country_code が alpha-2 以外の長さなら422"""
        res = await client.post("/api/v1/customers", json={
            "company_name": "国コードテスト",
            "addresses": [
                {"address_type": "billing", "country_code": "JPN"},  # 3文字はNG
            ],
        })
        assert res.status_code == 422
