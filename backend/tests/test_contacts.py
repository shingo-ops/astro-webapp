"""
Phase 1-B-2 Step 5b-1 で新設した contacts 系 API のスモークテスト。
"""


class TestContactsCRUD:
    async def _create_company(self, client, name: str = "会社A") -> int:
        res = await client.post("/api/v1/companies", json={"name": name})
        assert res.status_code == 201
        return res.json()["id"]

    async def test_create_minimal(self, client):
        company_id = await self._create_company(client, "担当者持ち会社")
        res = await client.post("/api/v1/contacts", json={
            "company_id": company_id,
            "display_name": "山田太郎",
        })
        assert res.status_code == 201
        data = res.json()
        assert data["company_id"] == company_id
        assert data["display_name"] == "山田太郎"
        assert data["contact_code"].startswith("CT-")
        assert data["is_primary_contact"] is False
        assert data["emails"] == []
        assert data["discord"] is None
        assert data["contact_channels"] == []

    async def test_create_unknown_company_returns_404(self, client):
        res = await client.post("/api/v1/contacts", json={
            "company_id": 99999999,
            "display_name": "孤児担当者",
        })
        assert res.status_code == 404

    async def test_create_with_nested_fields(self, client):
        company_id = await self._create_company(client, "フル担当者")
        res = await client.post("/api/v1/contacts", json={
            "company_id": company_id,
            "display_name": "佐藤花子",
            "primary_email": "sato@example.com",
            "primary_phone": "+819012345678",
            "is_primary_contact": True,
            "emails": [
                {"email": "sato.work@example.com", "purpose": "仕事用"},
                {"email": "sato.invoice@example.com", "purpose": "請求書用"},
            ],
            "discord": {"is_joined": True, "channel_id": "1234567890"},
            "contact_channels": [
                {"channel": "whatsapp", "purpose": "商談用", "is_primary": True},
            ],
        })
        assert res.status_code == 201
        data = res.json()
        assert data["is_primary_contact"] is True
        assert len(data["emails"]) == 2
        assert data["discord"]["is_joined"] is True
        # Discord is_joined=TRUE で contact_channels に 'discord' 行が自動追加される
        channels = [c["channel"] for c in data["contact_channels"]]
        assert "whatsapp" in channels
        assert "discord" in channels
        # is_primary=TRUE の重複を避けるため whatsapp が primary
        primaries = [c for c in data["contact_channels"] if c["is_primary"]]
        assert len(primaries) == 1
        assert primaries[0]["channel"] == "whatsapp"

    async def test_only_one_primary_contact_per_company(self, client):
        """1会社1 primary_contact の制約: 2人目を primary にすると1人目は解除される"""
        company_id = await self._create_company(client, "主担当者テスト")
        c1 = await client.post("/api/v1/contacts", json={
            "company_id": company_id, "display_name": "初代", "is_primary_contact": True,
        })
        assert c1.status_code == 201
        c1_id = c1.json()["id"]
        c2 = await client.post("/api/v1/contacts", json={
            "company_id": company_id, "display_name": "二代目", "is_primary_contact": True,
        })
        assert c2.status_code == 201
        # 初代の primary は外れているはず
        c1_after = await client.get(f"/api/v1/contacts/{c1_id}")
        assert c1_after.status_code == 200
        assert c1_after.json()["is_primary_contact"] is False

    async def test_list_and_filter(self, client):
        company_id = await self._create_company(client, "一覧テスト")
        await client.post("/api/v1/contacts", json={"company_id": company_id, "display_name": "A"})
        await client.post("/api/v1/contacts", json={"company_id": company_id, "display_name": "B"})
        res = await client.get("/api/v1/contacts", params={"company_id": company_id})
        assert res.status_code == 200
        names = sorted(c["display_name"] for c in res.json())
        assert names == ["A", "B"]

    async def test_list_company_filter_primary_first(self, client):
        """PR #147 review F5: /contacts?company_id=N で is_primary_contact=TRUE が先頭"""
        company_id = await self._create_company(client, "主担当先頭テスト")
        # 先に普通の contact を作成（updated_at が古くなる）
        await client.post("/api/v1/contacts", json={
            "company_id": company_id, "display_name": "サブ担当",
        })
        # その後で is_primary_contact=TRUE の contact を作成
        await client.post("/api/v1/contacts", json={
            "company_id": company_id, "display_name": "主担当", "is_primary_contact": True,
        })
        # さらに別の通常 contact（更新が一番新しい）
        await client.post("/api/v1/contacts", json={
            "company_id": company_id, "display_name": "新サブ",
        })
        res = await client.get("/api/v1/contacts", params={"company_id": company_id})
        assert res.status_code == 200
        data = res.json()
        # primary が必ず先頭に来る（updated_at よりも is_primary_contact DESC が優先）
        assert data[0]["is_primary_contact"] is True
        assert data[0]["display_name"] == "主担当"

    async def test_company_contacts_endpoint(self, client):
        company_id = await self._create_company(client, "配下担当者")
        await client.post("/api/v1/contacts", json={
            "company_id": company_id, "display_name": "プライマリ", "is_primary_contact": True,
        })
        await client.post("/api/v1/contacts", json={
            "company_id": company_id, "display_name": "サブ",
        })
        res = await client.get(f"/api/v1/companies/{company_id}/contacts")
        assert res.status_code == 200
        data = res.json()
        assert len(data) == 2
        # is_primary_contact=TRUE が先頭
        assert data[0]["display_name"] == "プライマリ"

    async def test_company_contacts_404(self, client):
        res = await client.get("/api/v1/companies/99999999/contacts")
        assert res.status_code == 404

    async def test_patch_partial(self, client):
        company_id = await self._create_company(client, "更新会社")
        create = await client.post("/api/v1/contacts", json={
            "company_id": company_id, "display_name": "元",
        })
        contact_id = create.json()["id"]
        res = await client.patch(f"/api/v1/contacts/{contact_id}", json={"display_name": "新"})
        assert res.status_code == 200
        assert res.json()["display_name"] == "新"

    async def test_delete(self, client):
        company_id = await self._create_company(client, "削除会社")
        create = await client.post("/api/v1/contacts", json={
            "company_id": company_id, "display_name": "削除担当",
        })
        contact_id = create.json()["id"]
        res = await client.delete(f"/api/v1/contacts/{contact_id}")
        assert res.status_code == 204
        assert (await client.get(f"/api/v1/contacts/{contact_id}")).status_code == 404


class TestContactPendingDedupReviewResolution:
    """PR #145 Q2: contacts の pending_dedup_review 解消フロー smoke。

    contacts には DB CHECK 制約はないが、ContactStatus enum に
    pending_dedup_review を追加したため backend は受領する。
    UI 側の「別人として確定」ボタンが叩く PATCH 経路を保護する。
    """

    async def _create_company(self, client, name: str = "会社A") -> int:
        res = await client.post("/api/v1/companies", json={"name": name})
        assert res.status_code == 201
        return res.json()["id"]

    async def test_create_contact_with_pending_dedup_review(self, client):
        """status='pending_dedup_review' で担当者を新規登録できる"""
        company_id = await self._create_company(client, "重複候補会社")
        res = await client.post("/api/v1/contacts", json={
            "company_id": company_id,
            "display_name": "重複候補担当",
            "status": "pending_dedup_review",
        })
        assert res.status_code == 201, res.text
        assert res.json()["status"] == "pending_dedup_review"

    async def test_resolve_contact_to_active(self, client):
        """pending_dedup_review → active に PATCH で更新できる"""
        company_id = await self._create_company(client, "解消対象会社")
        create = await client.post("/api/v1/contacts", json={
            "company_id": company_id,
            "display_name": "解消対象",
            "status": "pending_dedup_review",
        })
        contact_id = create.json()["id"]
        res = await client.patch(f"/api/v1/contacts/{contact_id}", json={
            "status": "active",
        })
        assert res.status_code == 200, res.text
        assert res.json()["status"] == "active"

    async def test_resolve_does_not_touch_other_fields(self, client):
        """status だけの PATCH は他フィールドを変更しない"""
        company_id = await self._create_company(client, "保護会社")
        create = await client.post("/api/v1/contacts", json={
            "company_id": company_id,
            "display_name": "保護対象",
            "primary_email": "keep@example.com",
            "status": "pending_dedup_review",
        })
        contact_id = create.json()["id"]
        await client.patch(f"/api/v1/contacts/{contact_id}", json={"status": "active"})
        got = await client.get(f"/api/v1/contacts/{contact_id}")
        data = got.json()
        assert data["status"] == "active"
        assert data["display_name"] == "保護対象"
        assert data["primary_email"] == "keep@example.com"
