"""
テスト基盤（conftest.py）

SQLiteインメモリDBを使用してCRM APIをテストする。
PostgreSQL固有のスキーマ分離はモックし、認証もモックする。

前提: Docker/PostgreSQL不要。ローカルで即実行可能。

変更履歴:
  2026-04-16: Phase 1対応（leads/teams/roles テーブル追加、
    customers/deals の拡張カラム、require_permission のバイパス）
"""

import os
# app.database が import される前に DATABASE_URL を SQLite に差し替える
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

import asyncio
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import text, event
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    """SQLiteインメモリエンジン"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    # SQLiteでNOW()を使えるようにし、Decimal型をサポートする
    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_compat(dbapi_conn, connection_record):
        import sqlite3
        from decimal import Decimal
        dbapi_conn.create_function("NOW", 0, lambda: "2026-04-07 00:00:00+00:00")
        dbapi_conn.create_function("LPAD", 3, lambda s, n, pad: str(s).rjust(int(n), pad))
        sqlite3.register_adapter(Decimal, lambda d: float(d))

    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="session")
async def setup_test_db(test_engine):
    """テスト用テーブルをセットアップする"""
    async with test_engine.begin() as conn:
        # 顧客テーブル（Phase 1拡張版）
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS customers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id INTEGER NOT NULL DEFAULT 999,
                customer_code VARCHAR(20),
                name VARCHAR(255) NOT NULL,
                email VARCHAR(255),
                phone VARCHAR(50),
                company VARCHAR(255),
                registration_source VARCHAR(50),
                status VARCHAR(20) DEFAULT 'active',
                billing_name VARCHAR(255),
                billing_phone VARCHAR(50),
                billing_email VARCHAR(255),
                billing_address TEXT,
                delivery_name VARCHAR(255),
                delivery_phone VARCHAR(50),
                delivery_email VARCHAR(255),
                delivery_address TEXT,
                delivery_country VARCHAR(100),
                business_id VARCHAR(100),
                transaction_count INTEGER DEFAULT 0,
                last_transaction_date TIMESTAMP,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        # リードテーブル
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id INTEGER NOT NULL DEFAULT 999,
                lead_code VARCHAR(20),
                customer_name VARCHAR(255) NOT NULL,
                company_name VARCHAR(255),
                email VARCHAR(255),
                phone VARCHAR(50),
                source VARCHAR(50),
                type VARCHAR(50),
                status VARCHAR(50) DEFAULT '新規',
                temperature VARCHAR(20),
                estimated_scale VARCHAR(20),
                customer_type VARCHAR(50),
                response_speed VARCHAR(20),
                monthly_forecast NUMERIC(15, 2),
                prospect_rank VARCHAR(10),
                assigned_to INTEGER,
                converted_deal_id INTEGER,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        # 案件テーブル（Phase 1拡張版）
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS deals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id INTEGER NOT NULL DEFAULT 999,
                deal_code VARCHAR(20),
                customer_id INTEGER REFERENCES customers(id),
                lead_id INTEGER REFERENCES leads(id),
                title VARCHAR(255) NOT NULL,
                amount NUMERIC(15, 2),
                currency VARCHAR(10) DEFAULT 'JPY',
                status VARCHAR(50) DEFAULT 'open',
                stage VARCHAR(50) DEFAULT 'open',
                probability INTEGER DEFAULT 10,
                lost_reason VARCHAR(255),
                assigned_to INTEGER,
                expected_close_date DATE,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        # 注文テーブル
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id INTEGER NOT NULL DEFAULT 999,
                customer_id INTEGER REFERENCES customers(id),
                deal_id INTEGER REFERENCES deals(id),
                order_number VARCHAR(100) NOT NULL,
                total_amount NUMERIC(15, 2),
                status VARCHAR(50) DEFAULT 'pending',
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        # 監査ログテーブル
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id INTEGER NOT NULL DEFAULT 999,
                user_id INTEGER NOT NULL,
                action VARCHAR(50) NOT NULL,
                table_name VARCHAR(100) NOT NULL,
                record_id INTEGER,
                old_data TEXT,
                new_data TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        # パーミッションマスタ（通常は public.permissions だがSQLite互換で無スキーマ）
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS permissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key VARCHAR(100) NOT NULL UNIQUE,
                resource VARCHAR(50) NOT NULL,
                action VARCHAR(50) NOT NULL,
                description VARCHAR(255) NOT NULL,
                category VARCHAR(50) NOT NULL
            )
        """))
        # ロール
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS roles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id INTEGER NOT NULL DEFAULT 999,
                name VARCHAR(100) NOT NULL,
                color VARCHAR(7) DEFAULT '#6c757d',
                priority INTEGER NOT NULL DEFAULT 0,
                is_system BOOLEAN DEFAULT FALSE,
                description VARCHAR(500),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(tenant_id, name)
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS role_permissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role_id INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
                permission_id INTEGER NOT NULL REFERENCES permissions(id) ON DELETE CASCADE,
                UNIQUE(role_id, permission_id)
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS user_roles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                role_id INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
                assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                assigned_by INTEGER,
                UNIQUE(user_id, role_id)
            )
        """))
        # チーム
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS teams (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id INTEGER NOT NULL DEFAULT 999,
                name VARCHAR(100) NOT NULL,
                leader_id INTEGER,
                description VARCHAR(500),
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(tenant_id, name)
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS team_members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
                user_id INTEGER NOT NULL,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(team_id, user_id)
            )
        """))
        # public.users 相当（SQLiteにはスキーマがないのでusersテーブルで代用）
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id INTEGER NOT NULL DEFAULT 999,
                username VARCHAR(255),
                email VARCHAR(255),
                role VARCHAR(50) DEFAULT 'user',
                is_active BOOLEAN DEFAULT TRUE
            )
        """))
        # テストユーザー投入
        await conn.execute(text("""
            INSERT OR IGNORE INTO users (id, tenant_id, username, email, role, is_active)
            VALUES (999, 999, 'testuser', 'test@example.com', 'admin', TRUE)
        """))
    yield


@pytest_asyncio.fixture
async def db_session(test_engine, setup_test_db):
    """各テスト用のDBセッション。テスト後にデータをクリーンアップ。"""
    async_session = sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session
        await session.rollback()

    # テスト後にデータを全削除
    async with test_engine.begin() as conn:
        await conn.execute(text("DELETE FROM audit_logs"))
        await conn.execute(text("DELETE FROM orders"))
        await conn.execute(text("DELETE FROM deals"))
        await conn.execute(text("DELETE FROM leads"))
        await conn.execute(text("DELETE FROM customers"))
        await conn.execute(text("DELETE FROM team_members"))
        await conn.execute(text("DELETE FROM teams"))
        await conn.execute(text("DELETE FROM user_roles"))
        await conn.execute(text("DELETE FROM role_permissions"))
        await conn.execute(text("DELETE FROM roles"))


def _mock_user():
    """テスト用のUserオブジェクトを生成"""
    from app.models import User
    user = User()
    user.id = 999
    user.tenant_id = 999
    user.username = "testuser"
    user.email = "test@example.com"
    user.role = "admin"
    user.is_active = True
    return user


def _make_noop_audit_log():
    """
    audit_logのスキーマ指定（tenant_NNN.audit_logs）をSQLiteで動くように差し替える。
    SQLiteにはスキーマの概念がないため、単にaudit_logsテーブルに直接INSERTする。
    """
    async def mock_record_audit_log(db, tenant_id, user_id, action, table_name,
                                     record_id=None, old_data=None, new_data=None):
        import json
        old_json = json.dumps(old_data, ensure_ascii=False, default=str) if old_data else None
        new_json = json.dumps(new_data, ensure_ascii=False, default=str) if new_data else None
        await db.execute(
            text("""
                INSERT INTO audit_logs (tenant_id, user_id, action, table_name, record_id, old_data, new_data)
                VALUES (:tenant_id, :user_id, :action, :table_name, :record_id, :old_data, :new_data)
            """),
            {
                "tenant_id": tenant_id, "user_id": user_id, "action": action,
                "table_name": table_name, "record_id": record_id,
                "old_data": old_json, "new_data": new_json,
            },
        )
    return mock_record_audit_log


ALL_TEST_PERMISSIONS = {
    "system.manage", "system.audit_view",
    "roles.view", "roles.create", "roles.update", "roles.delete", "roles.assign",
    "customers.view", "customers.create", "customers.update", "customers.delete",
    "leads.view", "leads.create", "leads.update", "leads.delete", "leads.convert",
    "deals.view", "deals.create", "deals.update", "deals.delete",
    "orders.view", "orders.create", "orders.update", "orders.delete",
    "teams.view", "teams.create", "teams.update", "teams.delete", "teams.manage_members",
    "dashboard.view", "reports.view", "reports.export",
}


async def _mock_load_user_permissions(db, tenant_id, user_id):
    """
    テスト中は全権限を持つものとして扱う（権限チェックを全パスさせる）。
    require_permission は内部で load_user_permissions を呼ぶため、
    ここで全キーを返すようにモックすれば全エンドポイントが通る。
    """
    return ALL_TEST_PERMISSIONS


@pytest.fixture(autouse=True)
def bypass_permissions():
    """
    全テストで `load_user_permissions` を自動モック。
    既存のget_db を MagicMock で差し替えているテスト（test_celery等）も
    権限チェックを通過できるようになる。
    """
    with patch("app.auth.dependencies.load_user_permissions", _mock_load_user_permissions):
        yield


@pytest_asyncio.fixture
async def client(db_session):
    """
    テスト用HTTPクライアント。
    認証・DB・audit_log・権限チェックをモックしてSQLiteで動作させる。
    """
    from app.main import app
    from app.auth.dependencies import (
        get_current_user,
        get_current_tenant,
    )
    from app.database import get_db

    mock_user = _mock_user()

    async def override_get_db():
        yield db_session

    async def override_get_current_user():
        return mock_user

    async def override_get_current_tenant():
        return 999

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_current_tenant] = override_get_current_tenant

    transport = ASGITransport(app=app)
    with patch("app.routers.customers.record_audit_log", _make_noop_audit_log()), \
         patch("app.routers.deals.record_audit_log", _make_noop_audit_log()), \
         patch("app.routers.orders.record_audit_log", _make_noop_audit_log()), \
         patch("app.routers.leads.record_audit_log", _make_noop_audit_log()), \
         patch("app.routers.teams.record_audit_log", _make_noop_audit_log()), \
         patch("app.routers.roles.record_audit_log", _make_noop_audit_log()), \
         patch("app.auth.dependencies.load_user_permissions", _mock_load_user_permissions):
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

    app.dependency_overrides.clear()
