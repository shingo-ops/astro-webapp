"""
ロール・権限管理API（roles）のテスト

対象:
  - GET /permissions (パーミッションマスタ一覧)
  - GET /me/permissions (自分の権限)
  - GET /roles (ロール一覧)
  - POST /roles (ロール作成・priority制限)
  - PATCH /roles/{id} (更新・システムロール保護・priority制限)
  - DELETE /roles/{id} (削除・システムロール保護・priority制限)
  - GET /roles/{id}/permissions (ロール権限一覧)
  - PUT /roles/{id}/permissions (権限一括更新・空リストで全削除)
  - GET /users/{id}/roles (ユーザーロール一覧)

制約:
  - set_role_permissions / set_user_roles の非空 ANY クエリは PostgreSQL 専用のため
    空リストのケースのみ SQLite テスト対象とする。
  - テストユーザー (id=999) は users.role='admin' → max_priority=1000 として振る舞う
    (conftest._max_priority_for_user の後方互換ロジック)。
"""

import pytest
from sqlalchemy import text


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------

async def _create_role(client, name, priority=10, color="#123456"):
    res = await client.post("/api/v1/roles", json={
        "name": name,
        "priority": priority,
        "color": color,
    })
    assert res.status_code == 201, res.text
    return res.json()


# ---------------------------------------------------------------------------
# パーミッションマスタ
# ---------------------------------------------------------------------------

class TestPermissions:
    """パーミッションマスタ系エンドポイント"""

    async def test_list_permissions_returns_200(self, client):
        """GET /permissions は 200 を返す（空でも OK）"""
        res = await client.get("/api/v1/permissions")
        assert res.status_code == 200
        assert isinstance(res.json(), list)

    async def test_get_my_permissions(self, client):
        """GET /me/permissions は permissions/is_super_admin/tenant_id を返す"""
        res = await client.get("/api/v1/me/permissions")
        assert res.status_code == 200
        data = res.json()
        assert "permissions" in data
        assert "is_super_admin" in data
        assert "tenant_id" in data
        assert isinstance(data["permissions"], list)

    async def test_my_permissions_includes_mocked_all_perms(self, client):
        """テスト環境では ALL_TEST_PERMISSIONS が返る"""
        res = await client.get("/api/v1/me/permissions")
        assert res.status_code == 200
        perms = set(res.json()["permissions"])
        # bypass_permissions で全権限がモックされていることを確認
        assert "roles.view" in perms
        assert "products.view" in perms
        assert "invoices.create" in perms


# ---------------------------------------------------------------------------
# ロール CRUD
# ---------------------------------------------------------------------------

class TestRolesCRUD:
    """ロールの基本 CRUD"""

    async def test_list_roles(self, client):
        """GET /roles は 200 を返す"""
        res = await client.get("/api/v1/roles")
        assert res.status_code == 200
        assert isinstance(res.json(), list)

    async def test_create_role(self, client):
        """ロールを作成できる"""
        data = await _create_role(client, "テストロール1", priority=50)
        assert data["name"] == "テストロール1"
        assert data["priority"] == 50
        assert data["is_system"] is False
        assert data["color"] == "#123456"

    async def test_create_role_with_description(self, client):
        """説明付きロールを作成できる"""
        res = await client.post("/api/v1/roles", json={
            "name": "説明付きロール",
            "priority": 5,
            "description": "このロールはテスト用です",
        })
        assert res.status_code == 201
        assert res.json()["description"] == "このロールはテスト用です"

    async def test_create_role_duplicate_name_returns_409(self, client):
        """同名ロールの重複作成は 409"""
        await _create_role(client, "重複ロール", priority=10)
        res = await client.post("/api/v1/roles", json={
            "name": "重複ロール",
            "priority": 20,
        })
        assert res.status_code == 409

    async def test_list_roles_after_create(self, client):
        """作成したロールが一覧に含まれる"""
        await _create_role(client, "一覧確認ロール", priority=30)

        res = await client.get("/api/v1/roles")
        assert res.status_code == 200
        names = [r["name"] for r in res.json()]
        assert "一覧確認ロール" in names

    async def test_update_role(self, client):
        """ロールを更新できる"""
        created = await _create_role(client, "更新前ロール", priority=15)
        role_id = created["id"]

        res = await client.patch(f"/api/v1/roles/{role_id}", json={
            "name": "更新後ロール",
            "description": "更新済み",
        })
        assert res.status_code == 200
        data = res.json()
        assert data["name"] == "更新後ロール"
        assert data["description"] == "更新済み"

    async def test_update_role_not_found(self, client):
        """存在しないロールの更新は 404"""
        res = await client.patch("/api/v1/roles/99999", json={"name": "xxx"})
        assert res.status_code == 404

    async def test_update_role_no_fields_returns_400(self, client):
        """更新フィールドなしは 400"""
        created = await _create_role(client, "フィールドなし更新ロール", priority=5)
        res = await client.patch(f"/api/v1/roles/{created['id']}", json={})
        assert res.status_code == 400

    async def test_delete_role(self, client):
        """ロールを削除できる"""
        created = await _create_role(client, "削除ロール", priority=10)
        role_id = created["id"]

        res = await client.delete(f"/api/v1/roles/{role_id}")
        assert res.status_code == 204

        # 削除後は一覧に含まれない
        list_res = await client.get("/api/v1/roles")
        names = [r["name"] for r in list_res.json()]
        assert "削除ロール" not in names

    async def test_delete_role_not_found(self, client):
        """存在しないロールの削除は 404"""
        res = await client.delete("/api/v1/roles/99999")
        assert res.status_code == 404

    async def test_update_role_invalid_color(self, client):
        """不正な色コードは 422"""
        created = await _create_role(client, "色バリデロール", priority=5)
        res = await client.patch(f"/api/v1/roles/{created['id']}", json={
            "color": "invalidcolor",
        })
        assert res.status_code == 422

    async def test_create_role_invalid_color(self, client):
        """不正な色コードでの作成は 422"""
        res = await client.post("/api/v1/roles", json={
            "name": "不正色ロール",
            "priority": 10,
            "color": "red",  # #RRGGBB 形式でない
        })
        assert res.status_code == 422


# ---------------------------------------------------------------------------
# Priority ガード
# ---------------------------------------------------------------------------

class TestRolesPriorityGuard:
    """priority 制限（ユーザーの最大 priority より低いロールのみ操作可）

    テストユーザー (id=999) は role='admin' → max_priority=1000 として振る舞う。
    user_roles を DB に直接挿入して max_priority を低下させ、制限を検証する。

    Note: RoleCreate.priority は Pydantic で le=999 に制限されているため、
    admin fallback(max_priority=1000) のまま API 経由で 403 を引き出すことはできない。
    代わりに user_roles を操作して max_priority を任意の値に設定するテストにする。
    """

    async def test_can_create_role_at_schema_max_priority(self, client):
        """priority=999（スキーマ上限）のロールは作成できる"""
        res = await client.post("/api/v1/roles", json={
            "name": "スキーマ上限ロール",
            "priority": 999,
        })
        assert res.status_code == 201

    async def test_cannot_create_role_at_equal_user_max_priority(self, client, db_session):
        """ユーザーのmax_priorityと等しい priority のロールは作成不可（403）"""
        # ユーザー999 に priority=50 のロールを割り当てる → max_priority が 50 に下がる
        await db_session.execute(text(
            "INSERT INTO roles (tenant_id, name, priority, is_system) VALUES (999, 'RefRole50', 50, FALSE)"
        ))
        await db_session.commit()
        ref_role = await db_session.execute(text("SELECT id FROM roles WHERE name='RefRole50'"))
        ref_role_id = ref_role.scalar()
        await db_session.execute(text(
            "INSERT INTO user_roles (user_id, role_id, assigned_by) VALUES (999, :rid, 999)"
        ), {"rid": ref_role_id})
        await db_session.commit()

        # max_priority=50 のユーザーが priority=50 のロールを作成しようとする → 403
        res = await client.post("/api/v1/roles", json={
            "name": "forbidden-equal-priority",
            "priority": 50,
        })
        assert res.status_code == 403

    async def test_can_create_role_below_user_max_priority(self, client, db_session):
        """ユーザーのmax_priorityより低い priority のロールは作成できる"""
        await db_session.execute(text(
            "INSERT INTO roles (tenant_id, name, priority, is_system) VALUES (999, 'RefRole60', 60, FALSE)"
        ))
        await db_session.commit()
        ref_role = await db_session.execute(text("SELECT id FROM roles WHERE name='RefRole60'"))
        ref_role_id = ref_role.scalar()
        await db_session.execute(text(
            "INSERT INTO user_roles (user_id, role_id, assigned_by) VALUES (999, :rid, 999)"
        ), {"rid": ref_role_id})
        await db_session.commit()

        # max_priority=60 のユーザーが priority=59 のロールを作成 → 201
        res = await client.post("/api/v1/roles", json={
            "name": "allowed-below-priority",
            "priority": 59,
        })
        assert res.status_code == 201

    async def test_cannot_edit_high_priority_role(self, client, db_session):
        """max_priority と等しい priority を持つロールは更新不可（403）"""
        # DB に priority=1000 のロールを直接挿入（スキーマ上限外のため API 不可）
        await db_session.execute(text(
            "INSERT INTO roles (tenant_id, name, priority, is_system) VALUES (999, 'Tier1000ロール', 1000, FALSE)"
        ))
        await db_session.commit()

        list_res = await client.get("/api/v1/roles")
        high_role = next(r for r in list_res.json() if r["name"] == "Tier1000ロール")
        role_id = high_role["id"]

        res = await client.patch(f"/api/v1/roles/{role_id}", json={"description": "変更試み"})
        assert res.status_code == 403

    async def test_cannot_delete_high_priority_role(self, client, db_session):
        """max_priority と等しい priority を持つロールは削除不可（403）"""
        await db_session.execute(text(
            "INSERT INTO roles (tenant_id, name, priority, is_system) VALUES (999, 'Tier1000削除ロール', 1000, FALSE)"
        ))
        await db_session.commit()

        list_res = await client.get("/api/v1/roles")
        high_role = next(r for r in list_res.json() if r["name"] == "Tier1000削除ロール")
        role_id = high_role["id"]

        res = await client.delete(f"/api/v1/roles/{role_id}")
        assert res.status_code == 403

    async def test_cannot_update_priority_to_user_max(self, client, db_session):
        """priority を自分の max_priority と等しい値に更新しようとすると 403"""
        # ユーザー999 に priority=70 のロールを割り当てる
        await db_session.execute(text(
            "INSERT INTO roles (tenant_id, name, priority, is_system) VALUES (999, 'RefRole70', 70, FALSE)"
        ))
        await db_session.commit()
        ref_role = await db_session.execute(text("SELECT id FROM roles WHERE name='RefRole70'"))
        ref_role_id = ref_role.scalar()
        await db_session.execute(text(
            "INSERT INTO user_roles (user_id, role_id, assigned_by) VALUES (999, :rid, 999)"
        ), {"rid": ref_role_id})
        await db_session.commit()

        # priority=30 のロールを作成（max_priority=70 未満なので OK）
        target = await _create_role(client, "昇格試みロール", priority=30)
        role_id = target["id"]

        # priority を 70（自分の max）に変更しようとする → 403
        res = await client.patch(f"/api/v1/roles/{role_id}", json={
            "priority": 70,
        })
        assert res.status_code == 403


# ---------------------------------------------------------------------------
# システムロール保護
# ---------------------------------------------------------------------------

class TestRolesSystemProtection:
    """is_system=TRUE のロールは編集・削除不可"""

    async def test_cannot_update_system_role(self, client, db_session):
        """システムロールの更新は 403"""
        await db_session.execute(text(
            "INSERT INTO roles (tenant_id, name, priority, is_system) VALUES (999, 'Ownerロール', 999, TRUE)"
        ))
        await db_session.commit()

        list_res = await client.get("/api/v1/roles")
        sys_role = next(r for r in list_res.json() if r["name"] == "Ownerロール")
        role_id = sys_role["id"]

        res = await client.patch(f"/api/v1/roles/{role_id}", json={"description": "変更試み"})
        assert res.status_code == 403

    async def test_cannot_delete_system_role(self, client, db_session):
        """システムロールの削除は 403"""
        await db_session.execute(text(
            "INSERT INTO roles (tenant_id, name, priority, is_system) VALUES (999, 'Memberロール', 1, TRUE)"
        ))
        await db_session.commit()

        list_res = await client.get("/api/v1/roles")
        sys_role = next(r for r in list_res.json() if r["name"] == "Memberロール")
        role_id = sys_role["id"]

        res = await client.delete(f"/api/v1/roles/{role_id}")
        assert res.status_code == 403


# ---------------------------------------------------------------------------
# ロール権限（role_permissions）
# ---------------------------------------------------------------------------

class TestRolePermissions:
    """ロールへの権限割り当て"""

    async def test_get_role_permissions_empty(self, client):
        """作成直後のロールは権限なし"""
        created = await _create_role(client, "権限なしロール", priority=5)
        role_id = created["id"]

        res = await client.get(f"/api/v1/roles/{role_id}/permissions")
        assert res.status_code == 200
        assert res.json() == []

    async def test_get_role_permissions_not_found(self, client):
        """存在しないロールの権限取得は 404"""
        res = await client.get("/api/v1/roles/99999/permissions")
        assert res.status_code == 404

    async def test_set_role_permissions_empty_clears_all(self, client):
        """権限IDリスト=空で PUT すると全権限削除（ANY 不使用パス）"""
        created = await _create_role(client, "権限クリアロール", priority=5)
        role_id = created["id"]

        # 空リストで PUT → ANY クエリは skip される
        res = await client.put(f"/api/v1/roles/{role_id}/permissions",
                               json={"permission_ids": []})
        assert res.status_code == 200
        data = res.json()
        assert data["role_id"] == role_id
        assert data["permission_count"] == 0

    async def test_set_role_permissions_system_role_forbidden(self, client, db_session):
        """システムロールへの権限設定は 403"""
        await db_session.execute(text(
            "INSERT INTO roles (tenant_id, name, priority, is_system) VALUES (999, 'perm-sys-ロール', 50, TRUE)"
        ))
        await db_session.commit()

        list_res = await client.get("/api/v1/roles")
        sys_role = next(r for r in list_res.json() if r["name"] == "perm-sys-ロール")
        role_id = sys_role["id"]

        res = await client.put(f"/api/v1/roles/{role_id}/permissions",
                               json={"permission_ids": []})
        assert res.status_code == 403

    async def test_set_role_permissions_not_found(self, client):
        """存在しないロールへの権限設定は 404"""
        res = await client.put("/api/v1/roles/99999/permissions",
                               json={"permission_ids": []})
        assert res.status_code == 404


# ---------------------------------------------------------------------------
# ユーザー×ロール
# ---------------------------------------------------------------------------

class TestUserRoles:
    """ユーザーへのロール割り当て確認"""

    async def test_get_user_roles_empty(self, client):
        """ロール未割当ユーザーは空リストを返す"""
        # テストユーザー(id=999)は user_roles に何も入っていない
        res = await client.get("/api/v1/users/999/roles")
        assert res.status_code == 200
        assert res.json() == []

    async def test_get_user_roles_after_insert(self, client, db_session):
        """ロールを割り当てた後に一覧で確認できる"""
        # ロール作成
        role_data = await _create_role(client, "割当確認ロール", priority=10)
        role_id = role_data["id"]

        # DB に直接 user_roles を挿入（set_user_roles は ANY を使うため）
        await db_session.execute(text(
            "INSERT INTO user_roles (user_id, role_id, assigned_by) VALUES (999, :rid, 999)"
        ), {"rid": role_id})
        await db_session.commit()

        res = await client.get("/api/v1/users/999/roles")
        assert res.status_code == 200
        role_names = [r["role_name"] for r in res.json()]
        assert "割当確認ロール" in role_names

    async def test_get_user_roles_user_not_found(self, client):
        """同テナントに存在しないユーザーIDは 404"""
        res = await client.get("/api/v1/users/99999/roles")
        assert res.status_code == 404
