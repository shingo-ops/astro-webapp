"""
仕入先管理API スモークテスト（ADR-072 Phase 2 カバレッジ補完）。

対象: GET /suppliers, GET /suppliers/{id}, POST /suppliers,
      PATCH /suppliers/{id}, DELETE /suppliers/{id}
目的: suppliers.py の未テスト endpoint body をカバーし、全体カバレッジを 60% 以上に回復する。
"""
from __future__ import annotations

import pytest


_SUPPLIER_BASE = {
    "name": "テスト仕入先株式会社",
    "contact_name": "田中太郎",
    "email": "test@supplier.example.com",
    "phone": "03-0000-0000",
    "address": "東京都渋谷区",
    "notes": "テスト用",
}


class TestSuppliersCRUD:
    async def test_list_suppliers_empty(self, client):
        """仕入先が0件の時に空リストを返す"""
        res = await client.get("/api/v1/suppliers")
        assert res.status_code == 200
        assert res.json() == []

    async def test_create_supplier(self, client):
        """仕入先を作成できる"""
        res = await client.post("/api/v1/suppliers", json=_SUPPLIER_BASE)
        assert res.status_code == 201, res.text
        data = res.json()
        assert data["name"] == "テスト仕入先株式会社"
        assert data["contact_name"] == "田中太郎"
        assert data["supplier_code"].startswith("SP-")
        assert data["is_active"] is True

    async def test_get_supplier(self, client):
        """仕入先をIDで取得できる"""
        create_res = await client.post("/api/v1/suppliers", json=_SUPPLIER_BASE)
        supplier_id = create_res.json()["id"]

        res = await client.get(f"/api/v1/suppliers/{supplier_id}")
        assert res.status_code == 200
        assert res.json()["id"] == supplier_id

    async def test_get_supplier_not_found(self, client):
        """存在しない仕入先は 404"""
        res = await client.get("/api/v1/suppliers/99999")
        assert res.status_code == 404

    async def test_list_suppliers_with_search(self, client):
        """search フィルタで絞り込める"""
        await client.post("/api/v1/suppliers", json=_SUPPLIER_BASE)
        res = await client.get("/api/v1/suppliers", params={"search": "テスト仕入先", "active_only": False})
        assert res.status_code == 200
        data = res.json()
        assert any("テスト仕入先" in s["name"] for s in data)

    async def test_update_supplier(self, client):
        """仕入先情報を更新できる"""
        create_res = await client.post("/api/v1/suppliers", json=_SUPPLIER_BASE)
        supplier_id = create_res.json()["id"]

        res = await client.patch(
            f"/api/v1/suppliers/{supplier_id}",
            json={"name": "更新後仕入先株式会社"},
        )
        assert res.status_code == 200
        assert res.json()["name"] == "更新後仕入先株式会社"

    async def test_update_supplier_not_found(self, client):
        """存在しない仕入先の更新は 404"""
        res = await client.patch("/api/v1/suppliers/99999", json={"name": "X"})
        assert res.status_code == 404

    async def test_update_supplier_no_fields(self, client):
        """更新フィールドが空の場合は 400"""
        create_res = await client.post("/api/v1/suppliers", json=_SUPPLIER_BASE)
        supplier_id = create_res.json()["id"]

        res = await client.patch(f"/api/v1/suppliers/{supplier_id}", json={})
        assert res.status_code == 400

    async def test_delete_supplier(self, client):
        """仕入先をソフトデリートできる（is_active = False）"""
        create_res = await client.post("/api/v1/suppliers", json=_SUPPLIER_BASE)
        supplier_id = create_res.json()["id"]

        del_res = await client.delete(f"/api/v1/suppliers/{supplier_id}")
        assert del_res.status_code == 204

    async def test_delete_supplier_not_found(self, client):
        """存在しない仕入先の削除は 404"""
        res = await client.delete("/api/v1/suppliers/99999")
        assert res.status_code == 404
