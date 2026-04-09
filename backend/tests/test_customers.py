"""顧客管理API（customers）のテスト"""

import pytest


class TestCustomersCRUD:
    """顧客の作成・取得・更新・削除"""

    async def test_create_customer(self, client):
        """顧客を新規作成できる"""
        res = await client.post("/api/v1/customers", json={
            "name": "山田太郎",
            "email": "yamada@example.com",
            "phone": "090-1234-5678",
            "company": "山田商事",
            "notes": "テスト顧客",
        })
        assert res.status_code == 201
        data = res.json()
        assert data["name"] == "山田太郎"
        assert data["email"] == "yamada@example.com"
        assert data["company"] == "山田商事"
        assert "id" in data
        assert "created_at" in data

    async def test_create_customer_minimal(self, client):
        """名前のみで顧客を作成できる（他はオプション）"""
        res = await client.post("/api/v1/customers", json={"name": "佐藤花子"})
        assert res.status_code == 201
        data = res.json()
        assert data["name"] == "佐藤花子"
        assert data["email"] is None
        assert data["phone"] is None

    async def test_list_customers(self, client):
        """顧客一覧を取得できる"""
        await client.post("/api/v1/customers", json={"name": "顧客A"})
        await client.post("/api/v1/customers", json={"name": "顧客B"})

        res = await client.get("/api/v1/customers")
        assert res.status_code == 200
        data = res.json()
        assert len(data) >= 2

    @pytest.mark.skip(reason="ILIKE is PostgreSQL-specific, tested in integration tests")
    async def test_list_customers_search(self, client):
        """名前・メール・会社名で検索できる（PostgreSQL環境で検証）"""
        pass

    async def test_list_customers_pagination(self, client):
        """ページネーションが動作する"""
        for i in range(5):
            await client.post("/api/v1/customers", json={"name": f"ページ顧客{i}"})

        res = await client.get("/api/v1/customers", params={"page": 1, "per_page": 2})
        assert res.status_code == 200
        assert len(res.json()) == 2

    async def test_get_customer(self, client):
        """顧客詳細を取得できる"""
        create_res = await client.post("/api/v1/customers", json={"name": "詳細テスト"})
        customer_id = create_res.json()["id"]

        res = await client.get(f"/api/v1/customers/{customer_id}")
        assert res.status_code == 200
        assert res.json()["name"] == "詳細テスト"

    async def test_get_customer_not_found(self, client):
        """存在しない顧客は404"""
        res = await client.get("/api/v1/customers/99999")
        assert res.status_code == 404

    async def test_update_customer(self, client):
        """顧客情報を部分更新できる"""
        create_res = await client.post("/api/v1/customers", json={
            "name": "更新前", "company": "旧会社",
        })
        customer_id = create_res.json()["id"]

        res = await client.patch(f"/api/v1/customers/{customer_id}", json={
            "name": "更新後",
        })
        assert res.status_code == 200
        data = res.json()
        assert data["name"] == "更新後"
        assert data["company"] == "旧会社"  # 変更していないフィールドは保持

    async def test_update_customer_empty_body(self, client):
        """空のリクエストボディは400"""
        create_res = await client.post("/api/v1/customers", json={"name": "空更新テスト"})
        customer_id = create_res.json()["id"]

        res = await client.patch(f"/api/v1/customers/{customer_id}", json={})
        assert res.status_code == 400

    async def test_delete_customer(self, client):
        """顧客を削除できる"""
        create_res = await client.post("/api/v1/customers", json={"name": "削除テスト"})
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

    async def test_create_without_name(self, client):
        """名前なしは422"""
        res = await client.post("/api/v1/customers", json={"email": "no-name@test.com"})
        assert res.status_code == 422

    async def test_create_empty_name(self, client):
        """空文字の名前は422"""
        res = await client.post("/api/v1/customers", json={"name": ""})
        assert res.status_code == 422

    async def test_invalid_email_format(self, client):
        """不正なメール形式は422"""
        res = await client.post("/api/v1/customers", json={
            "name": "メールテスト", "email": "invalid-email",
        })
        assert res.status_code == 422

    async def test_invalid_phone_format(self, client):
        """不正な電話番号形式は422"""
        res = await client.post("/api/v1/customers", json={
            "name": "電話テスト", "phone": "abc",
        })
        assert res.status_code == 422
