"""ADR-093 Phase 4: 在庫表ユーザー別フィルタ API のテスト。

SQLite には public.user_inventory_filters が無いため is_postgresql 分岐で
GET=デフォルト / PATCH=受領値エコー となる（API 契約・バリデーションの検証）。
永続化の実検証（upsert / 再取得）は実 PostgreSQL E2E 側。
"""


class TestMeInventoryFilters:
    """GET/PATCH /api/v1/me/inventory-filters の契約。"""

    async def test_get_default(self, client):
        """未設定ユーザーはデフォルト（enabled=false, 空配列）を返す。"""
        res = await client.get("/api/v1/me/inventory-filters")
        assert res.status_code == 200
        d = res.json()
        assert d["enabled"] is False
        assert d["hidden_supplier_ids"] == []
        assert d["hidden_columns"] == []

    async def test_patch_echoes_payload(self, client):
        """PATCH は受領した設定をそのまま返す（SQLite では永続化 skip）。"""
        res = await client.patch(
            "/api/v1/me/inventory-filters",
            json={
                "enabled": True,
                "hidden_supplier_ids": [1, 2, 3],
                "hidden_columns": ["unit", "unitPrice"],
            },
        )
        assert res.status_code == 200
        d = res.json()
        assert d["enabled"] is True
        assert d["hidden_supplier_ids"] == [1, 2, 3]
        assert d["hidden_columns"] == ["unit", "unitPrice"]

    async def test_patch_invalid_supplier_id_type_422(self, client):
        """hidden_supplier_ids に非整数 → 422。"""
        res = await client.patch(
            "/api/v1/me/inventory-filters",
            json={"hidden_supplier_ids": ["not-a-number"]},
        )
        assert res.status_code == 422
