"""
シフト管理API スモークテスト（ADR-072 Phase 2 カバレッジ補完）。

対象: GET /shifts, POST /shifts, DELETE /shifts/{id}
目的: shifts.py の未テスト endpoint body をカバーし、全体カバレッジを 60% 以上に回復する。
"""
from __future__ import annotations

import pytest


_SHIFT_BASE = {
    "user_id": 999,
    "shift_date": "2026-06-01",
    "start_time": "09:00",
    "end_time": "18:00",
    "shift_type": "normal",
    "notes": "テストシフト",
}


class TestShiftsCRUD:
    async def test_list_shifts_empty(self, client):
        """シフトが0件の時に空リストを返す"""
        res = await client.get("/api/v1/shifts")
        assert res.status_code == 200
        assert res.json() == []

    async def test_create_shift(self, client):
        """シフトを作成できる"""
        res = await client.post("/api/v1/shifts", json=_SHIFT_BASE)
        assert res.status_code == 201, res.text
        data = res.json()
        assert data["user_id"] == 999
        assert data["shift_date"] == "2026-06-01"
        assert data["start_time"] == "09:00"
        assert data["end_time"] == "18:00"
        assert data["shift_type"] == "normal"
        assert data["notes"] == "テストシフト"
        assert "id" in data

    async def test_list_shifts_with_results(self, client):
        """作成後にリストで取得できる"""
        await client.post("/api/v1/shifts", json=_SHIFT_BASE)
        res = await client.get("/api/v1/shifts")
        assert res.status_code == 200
        assert len(res.json()) >= 1

    async def test_list_shifts_with_filters(self, client):
        """user_id / date_from / date_to フィルタが動作する"""
        await client.post("/api/v1/shifts", json=_SHIFT_BASE)
        res = await client.get(
            "/api/v1/shifts",
            params={"user_id": 999, "date_from": "2026-06-01", "date_to": "2026-06-30"},
        )
        assert res.status_code == 200
        data = res.json()
        assert all(s["user_id"] == 999 for s in data)

    async def test_delete_shift(self, client):
        """シフトを削除できる"""
        create_res = await client.post("/api/v1/shifts", json=_SHIFT_BASE)
        shift_id = create_res.json()["id"]

        del_res = await client.delete(f"/api/v1/shifts/{shift_id}")
        assert del_res.status_code == 204

    async def test_delete_shift_not_found(self, client):
        """存在しないシフトの削除は 404"""
        res = await client.delete("/api/v1/shifts/99999")
        assert res.status_code == 404
