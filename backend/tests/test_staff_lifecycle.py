"""
ADR-023: スタッフライフサイクル 3 層同期のテスト。

検証対象:
  - POST /staff が Firebase Auth + public.users + tenant.staff の 3 層を作成する
  - DELETE /staff/{id} が同 3 層から削除する
  - PATCH /staff/{id} で status が変わったとき public.users.is_active が同期する
  - 重複 email の場合は 409 を返す
  - 仮パスワードは 1 度きりレスポンスに含まれ、平文で DB に保存されない
"""

from unittest.mock import patch

import pytest
from sqlalchemy import text


async def _seed_role(db_session, role_id: int = 1, name: str = "staff") -> int:
    await db_session.execute(
        text("""
            INSERT INTO roles (id, tenant_id, name, color, priority, is_system)
            VALUES (:rid, 999, :name, '#888888', 0, FALSE)
        """),
        {"rid": role_id, "name": name},
    )
    await db_session.commit()
    return role_id


def _post_staff_body(email: str, role_id: int, status: str = "active", **extra) -> dict:
    body = {
        "surname_jp": "山田",
        "given_name_jp": "太郎",
        "primary_email": email,
        "role_id": role_id,
        "status": status,
    }
    body.update(extra)
    return body


@pytest.mark.asyncio
async def test_create_staff_provisions_three_layers(client, db_session):
    """POST /staff: Firebase Auth + public.users + tenant.staff が全部作られる。"""
    role_id = await _seed_role(db_session)

    res = await client.post(
        "/api/v1/staff",
        json=_post_staff_body("newhire@example.com", role_id),
    )
    assert res.status_code == 201, res.text
    body = res.json()

    # ① レスポンスに仮パスワードが入る（1 度きり）
    assert body["provisional_password"], "仮パスワードがレスポンスに含まれること"
    assert len(body["provisional_password"]) >= 16

    # ② tenant.staff に登録され、firebase_uid と user_id が紐づいている
    assert body["primary_email"] == "newhire@example.com"
    assert body["firebase_uid"] is not None
    assert body["user_id"] is not None

    # ③ public.users にも対応する行が作成され、password_hash は bcrypt（平文は保存されない）
    row = (await db_session.execute(
        text("SELECT id, email, password_hash, is_active FROM users WHERE email = :e"),
        {"e": "newhire@example.com"},
    )).mappings().first()
    assert row is not None, "public.users に作成されること"
    assert row["id"] == body["user_id"]
    assert row["password_hash"] != body["provisional_password"], "平文ではなくハッシュで保存"
    assert row["password_hash"].startswith("$2"), "bcrypt ハッシュ形式"
    assert row["is_active"] == 1 or row["is_active"] is True


@pytest.mark.asyncio
async def test_create_staff_inactive_syncs_users_is_active_false(client, db_session):
    """status=inactive で作ると public.users.is_active=False になる。"""
    role_id = await _seed_role(db_session)
    res = await client.post(
        "/api/v1/staff",
        json=_post_staff_body("inactive@example.com", role_id, status="inactive"),
    )
    assert res.status_code == 201, res.text
    user_id = res.json()["user_id"]
    row = (await db_session.execute(
        text("SELECT is_active FROM users WHERE id = :id"), {"id": user_id}
    )).mappings().first()
    assert row["is_active"] in (0, False)


@pytest.mark.asyncio
async def test_create_staff_duplicate_email_returns_409(client, db_session):
    """同じ email の public.users が既にあれば 409。Firebase user は作られない。"""
    role_id = await _seed_role(db_session)
    await db_session.execute(
        text("""
            INSERT INTO users (id, tenant_id, username, email, password_hash, role, is_active)
            VALUES (1001, 999, 'dup', 'dup@example.com', '$2b$12$x', 'user', TRUE)
        """),
    )
    await db_session.commit()

    with patch("app.services.staff_lifecycle.firebase_helpers.create_user") as fake_create:
        res = await client.post(
            "/api/v1/staff",
            json=_post_staff_body("dup@example.com", role_id),
        )
    assert res.status_code == 409, res.text
    fake_create.assert_not_called()  # public.users 重複は Firebase 呼ぶ前に判定


@pytest.mark.asyncio
async def test_delete_staff_removes_three_layers(client, db_session):
    """DELETE /staff/{id}: tenant.staff + public.users + Firebase の全層から消える。"""
    role_id = await _seed_role(db_session)

    # まず POST で 3 層作成
    created = (await client.post(
        "/api/v1/staff",
        json=_post_staff_body("delme@example.com", role_id),
    )).json()
    staff_id = created["id"]
    user_id = created["user_id"]
    fb_uid = created["firebase_uid"]

    # Firebase delete を観測
    with patch("app.services.staff_lifecycle.firebase_helpers.delete_user") as fake_delete:
        del_res = await client.delete(f"/api/v1/staff/{staff_id}")
    assert del_res.status_code == 204, del_res.text

    # tenant.staff から消えた
    row = (await db_session.execute(
        text("SELECT id FROM staff WHERE id = :id"), {"id": staff_id}
    )).first()
    assert row is None

    # public.users からも消えた
    urow = (await db_session.execute(
        text("SELECT id FROM users WHERE id = :id"), {"id": user_id}
    )).first()
    assert urow is None

    # Firebase delete_user が firebase_uid 付きで呼ばれた
    fake_delete.assert_called_once_with(fb_uid)


@pytest.mark.asyncio
async def test_patch_staff_status_syncs_users_is_active(client, db_session):
    """PATCH で status を active→inactive にすると users.is_active が False になる。"""
    role_id = await _seed_role(db_session)
    created = (await client.post(
        "/api/v1/staff",
        json=_post_staff_body("toggle@example.com", role_id),
    )).json()
    staff_id = created["id"]
    user_id = created["user_id"]

    # 初期は active
    is_active = (await db_session.execute(
        text("SELECT is_active FROM users WHERE id = :id"), {"id": user_id}
    )).scalar_one()
    assert is_active in (1, True)

    # inactive に変更
    with patch("app.services.staff_lifecycle.firebase_helpers.set_disabled") as fake_set:
        res = await client.patch(f"/api/v1/staff/{staff_id}", json={"status": "inactive"})
    assert res.status_code == 200, res.text
    is_active = (await db_session.execute(
        text("SELECT is_active FROM users WHERE id = :id"), {"id": user_id}
    )).scalar_one()
    assert is_active in (0, False)
    # Firebase 側も disabled=True
    fake_set.assert_called_once()
    _, kwargs = fake_set.call_args
    args = fake_set.call_args.args
    assert args[1] is True  # disabled=True

    # active に戻す
    with patch("app.services.staff_lifecycle.firebase_helpers.set_disabled") as fake_set2:
        res = await client.patch(f"/api/v1/staff/{staff_id}", json={"status": "active"})
    assert res.status_code == 200, res.text
    is_active = (await db_session.execute(
        text("SELECT is_active FROM users WHERE id = :id"), {"id": user_id}
    )).scalar_one()
    assert is_active in (1, True)
    fake_set2.assert_called_once()
    assert fake_set2.call_args.args[1] is False


@pytest.mark.asyncio
async def test_patch_staff_status_unchanged_does_not_call_firebase(client, db_session):
    """PATCH で status が変わらないなら Firebase 同期は呼ばれない（無駄な API 呼び出し回避）。"""
    role_id = await _seed_role(db_session)
    created = (await client.post(
        "/api/v1/staff",
        json=_post_staff_body("nochange@example.com", role_id),
    )).json()
    staff_id = created["id"]

    # status を変えず、surname_jp だけ更新
    with patch("app.services.staff_lifecycle.firebase_helpers.set_disabled") as fake_set:
        res = await client.patch(f"/api/v1/staff/{staff_id}", json={"surname_jp": "佐藤"})
    assert res.status_code == 200, res.text
    fake_set.assert_not_called()


@pytest.mark.asyncio
async def test_create_staff_with_existing_user_id_skips_provisioning(client, db_session):
    """user_id を明示すると Firebase + public.users 作成をスキップする（管理者オーバーライド）。"""
    role_id = await _seed_role(db_session)

    # 事前に public.users を作る
    await db_session.execute(
        text("""
            INSERT INTO users (id, tenant_id, username, email, password_hash, role, is_active)
            VALUES (2001, 999, 'existing', 'existing@example.com', '$2b$12$x', 'user', TRUE)
        """),
    )
    await db_session.commit()

    with patch("app.services.staff_lifecycle.firebase_helpers.create_user") as fake_create:
        res = await client.post(
            "/api/v1/staff",
            json={
                **_post_staff_body("existing@example.com", role_id),
                "user_id": 2001,
                "firebase_uid": "preexisting-uid",
            },
        )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["user_id"] == 2001
    assert body["firebase_uid"] == "preexisting-uid"
    assert body["provisional_password"] is None
    fake_create.assert_not_called()
