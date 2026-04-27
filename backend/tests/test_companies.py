"""
Phase 1-B-2 Step 5b-1 で新設した companies 系 API のスモークテスト。
既存 customers API は温存されており、本テストは新 API のみ対象。
"""


class TestCompaniesCRUD:
    async def test_create_minimal(self, client):
        """会社名だけで会社を作成できる（副テーブル全て空）"""
        res = await client.post("/api/v1/companies", json={"name": "株式会社テスト"})
        assert res.status_code == 201
        data = res.json()
        assert data["name"] == "株式会社テスト"
        assert data["company_code"].startswith("CO-")
        assert data["addresses"] == []
        assert data["sales_channels"] == []
        assert data["status"] == "active"

    async def test_create_with_nested_address(self, client):
        """会社を住所付きで作成できる（branch_name + is_default 対応）"""
        res = await client.post("/api/v1/companies", json={
            "name": "Card Galaxy LTD",
            "addresses": [
                {
                    "address_type": "billing",
                    "branch_name": "Essex",
                    "name": "Card Galaxy LTD Essex",
                    "country_code": "GB",
                    "is_default": True,
                },
                {
                    "address_type": "billing",
                    "branch_name": "Preston",
                    "name": "Card Galaxy LTD Preston",
                    "country_code": "GB",
                    "is_default": False,
                },
            ],
            "sales_channels": ["EC", "実店舗"],
        })
        assert res.status_code == 201
        data = res.json()
        assert len(data["addresses"]) == 2
        branches = sorted(a["branch_name"] for a in data["addresses"])
        assert branches == ["Essex", "Preston"]
        # is_default=TRUE は1つに絞られている
        defaults = [a for a in data["addresses"] if a["is_default"]]
        assert len(defaults) == 1
        assert defaults[0]["branch_name"] == "Essex"
        assert set(data["sales_channels"]) == {"EC", "実店舗"}

    async def test_create_explicit_code(self, client):
        """明示的な company_code を指定できる"""
        res = await client.post("/api/v1/companies", json={
            "name": "明示コード会社",
            "company_code": "CO-99999",
        })
        assert res.status_code == 201
        assert res.json()["company_code"] == "CO-99999"

    async def test_list_and_search(self, client):
        """一覧 + 検索"""
        await client.post("/api/v1/companies", json={"name": "α Company"})
        await client.post("/api/v1/companies", json={"name": "β Inc"})

        res = await client.get("/api/v1/companies")
        assert res.status_code == 200
        assert len(res.json()) >= 2

        res = await client.get("/api/v1/companies", params={"search": "β"})
        assert res.status_code == 200
        names = [c["name"] for c in res.json()]
        assert "β Inc" in names

    async def test_get_single(self, client):
        create = await client.post("/api/v1/companies", json={"name": "取得テスト"})
        company_id = create.json()["id"]
        res = await client.get(f"/api/v1/companies/{company_id}")
        assert res.status_code == 200
        assert res.json()["name"] == "取得テスト"

    async def test_get_not_found(self, client):
        res = await client.get("/api/v1/companies/99999999")
        assert res.status_code == 404

    async def test_patch_partial(self, client):
        create = await client.post("/api/v1/companies", json={"name": "更新前"})
        company_id = create.json()["id"]
        res = await client.patch(
            f"/api/v1/companies/{company_id}",
            json={"name": "更新後", "industry": "IT"},
        )
        assert res.status_code == 200
        assert res.json()["name"] == "更新後"
        assert res.json()["industry"] == "IT"

    async def test_patch_empty_returns_400(self, client):
        create = await client.post("/api/v1/companies", json={"name": "空更新"})
        company_id = create.json()["id"]
        res = await client.patch(f"/api/v1/companies/{company_id}", json={})
        assert res.status_code == 400

    async def test_patch_replaces_addresses(self, client):
        create = await client.post("/api/v1/companies", json={
            "name": "住所置換",
            "addresses": [{"address_type": "billing", "name": "旧住所"}],
        })
        company_id = create.json()["id"]
        res = await client.patch(f"/api/v1/companies/{company_id}", json={
            "addresses": [
                {"address_type": "billing", "name": "新請求", "is_default": True},
                {"address_type": "delivery", "name": "新配送", "is_default": True},
            ],
        })
        assert res.status_code == 200
        data = res.json()
        assert len(data["addresses"]) == 2
        names = sorted(a["name"] for a in data["addresses"])
        assert names == ["新請求", "新配送"]

    async def test_delete(self, client):
        create = await client.post("/api/v1/companies", json={"name": "削除対象"})
        company_id = create.json()["id"]
        res = await client.delete(f"/api/v1/companies/{company_id}")
        assert res.status_code == 204

        # 404 確認
        assert (await client.get(f"/api/v1/companies/{company_id}")).status_code == 404

    async def test_company_code_required_unique(self, client):
        """同一 company_code を2回登録すると 409"""
        await client.post("/api/v1/companies", json={
            "name": "会社A",
            "company_code": "CO-DUP-01",
        })
        res2 = await client.post("/api/v1/companies", json={
            "name": "会社B",
            "company_code": "CO-DUP-01",
        })
        assert res2.status_code == 409


class TestPendingDedupReviewResolution:
    """PR #145 Q2: pending_dedup_review の手動解消フロー smoke。

    backend は既に `update_company` で status を任意の有効値に書き換えできるが、
    UI 側で「別会社として確定」ボタンが叩く PATCH 経路を回帰テストで保護する。
    """

    async def test_create_with_pending_dedup_review_status(self, client):
        """status='pending_dedup_review' で会社を新規登録できる（CHECK 制約 OK 確認）"""
        res = await client.post("/api/v1/companies", json={
            "name": "重複候補会社",
            "status": "pending_dedup_review",
        })
        assert res.status_code == 201, res.text
        assert res.json()["status"] == "pending_dedup_review"

    async def test_resolve_to_active(self, client):
        """pending_dedup_review → active に PATCH で更新できる（解消フロー）"""
        create = await client.post("/api/v1/companies", json={
            "name": "解消対象",
            "status": "pending_dedup_review",
        })
        company_id = create.json()["id"]
        res = await client.patch(f"/api/v1/companies/{company_id}", json={
            "status": "active",
        })
        assert res.status_code == 200, res.text
        assert res.json()["status"] == "active"

    async def test_other_fields_intact_after_resolve(self, client):
        """status だけの PATCH は副テーブル（住所・販売チャネル）を巻き込まない"""
        create = await client.post("/api/v1/companies", json={
            "name": "副テーブル保護",
            "status": "pending_dedup_review",
            "addresses": [{"address_type": "billing", "name": "請求", "is_default": True}],
            "sales_channels": ["EC"],
        })
        company_id = create.json()["id"]
        await client.patch(f"/api/v1/companies/{company_id}", json={"status": "active"})
        got = await client.get(f"/api/v1/companies/{company_id}")
        data = got.json()
        assert data["status"] == "active"
        assert len(data["addresses"]) == 1
        assert data["addresses"][0]["name"] == "請求"
        assert data["sales_channels"] == ["EC"]

    async def test_invalid_status_rejected(self, client):
        """未知の status 値は 422 で拒否される（enum バリデーション）"""
        create = await client.post("/api/v1/companies", json={"name": "不正値"})
        company_id = create.json()["id"]
        res = await client.patch(f"/api/v1/companies/{company_id}", json={
            "status": "totally_invalid",
        })
        assert res.status_code == 422
