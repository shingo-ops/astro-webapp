"""
B-1: GET /api/v1/staff/me のスモークテスト。

users.email == staff.primary_email でフォールバック検索する経路と、
staff レコード未紐づけの場合の 404 を検証する。
"""

import pytest
from sqlalchemy import text


@pytest.mark.asyncio
async def test_get_my_staff_via_email_fallback(client, db_session):
    """
    conftest の mock_user は email='test@example.com'。
    User モデルに firebase_uid が無いため /staff/me は email フォールバック経路を通る。
    """
    # 役割を1件作成
    await db_session.execute(text("""
        INSERT INTO roles (id, tenant_id, name, color, priority, is_system)
        VALUES (1, 999, 'staff', '#888888', 0, FALSE)
    """))
    # mock_user.email と一致する primary_email でスタッフを作る
    await db_session.execute(text("""
        INSERT INTO staff (
            id, tenant_id, staff_code, surname_jp, given_name_jp,
            primary_email, role_id, status
        ) VALUES (
            500, 999, 'EMP-TEST01', '山田', '太郎',
            'test@example.com', 1, 'active'
        )
    """))
    # ui_preferences 行を作る（dark_mode のみ true）
    await db_session.execute(text("""
        INSERT INTO staff_ui_preferences (
            staff_id, dark_mode, show_chat_menu, show_sales_menu,
            show_settings_menu, show_admin_menu, show_sidebar
        ) VALUES (500, 1, 1, 1, 1, 0, 1)
    """))
    await db_session.commit()

    res = await client.get("/api/v1/staff/me")
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["id"] == 500
    assert data["primary_email"] == "test@example.com"
    assert data["role_name"] == "staff"
    assert data["ui_preferences"] is not None
    assert data["ui_preferences"]["dark_mode"] is True
    assert data["ui_preferences"]["show_admin_menu"] is False
    assert data["ui_preferences"]["show_sidebar"] is True


@pytest.mark.asyncio
async def test_get_my_staff_404_when_no_link(client, db_session):
    """staff レコードが無いユーザは 404 を返す"""
    # 何も投入しない（mock_user.email='test@example.com' に対応する staff は存在しない）
    res = await client.get("/api/v1/staff/me")
    assert res.status_code == 404
    body = res.json()
    assert "staff" in body["detail"] or "見つかりません" in body["detail"]


@pytest.mark.asyncio
async def test_get_my_staff_deterministic_when_shared_email(client, db_session):
    """
    PR #166 round 1 fix (F1):
    primary_email は UNIQUE 制約なし（migration 019: 共有アドレス運用許容）。
    同じ email を持つ staff が複数存在する場合、`ORDER BY s.id ASC` により
    最も小さい id を持つ staff が決定的に返ることを保証する。
    """
    await db_session.execute(text("""
        INSERT INTO roles (id, tenant_id, name, color, priority, is_system)
        VALUES (3, 999, 'shared', '#555555', 0, FALSE)
    """))
    # 同じ primary_email を持つ staff を 2 件投入（id=700, 701）
    await db_session.execute(text("""
        INSERT INTO staff (
            id, tenant_id, staff_code, surname_jp, given_name_jp,
            primary_email, role_id, status
        ) VALUES
            (701, 999, 'EMP-SHARE2', '佐藤', '次郎', 'test@example.com', 3, 'active'),
            (700, 999, 'EMP-SHARE1', '佐藤', '一郎', 'test@example.com', 3, 'active')
    """))
    await db_session.commit()

    # 複数回叩いても常に id=700（最小）が返ることを確認
    for _ in range(3):
        res = await client.get("/api/v1/staff/me")
        assert res.status_code == 200, res.text
        assert res.json()["id"] == 700


@pytest.mark.asyncio
async def test_get_my_staff_no_ui_preferences_returns_null(client, db_session):
    """staff_ui_preferences 行が存在しない場合は ui_preferences=null を返す"""
    await db_session.execute(text("""
        INSERT INTO roles (id, tenant_id, name, color, priority, is_system)
        VALUES (2, 999, 'staff2', '#999999', 0, FALSE)
    """))
    await db_session.execute(text("""
        INSERT INTO staff (
            id, tenant_id, staff_code, surname_jp, given_name_jp,
            primary_email, role_id, status
        ) VALUES (
            600, 999, 'EMP-TEST02', '鈴木', '花子',
            'test@example.com', 2, 'active'
        )
    """))
    # ui_preferences は意図的に作らない
    await db_session.commit()

    res = await client.get("/api/v1/staff/me")
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["id"] == 600
    assert data["ui_preferences"] is None
