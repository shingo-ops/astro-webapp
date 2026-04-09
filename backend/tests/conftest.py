"""
テスト基盤（conftest.py）

SQLiteインメモリDBを使用してCRM APIをテストする。
PostgreSQL固有のスキーマ分離はモックし、認証もモックする。

前提: Docker/PostgreSQL不要。ローカルで即実行可能。
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
        sqlite3.register_adapter(Decimal, lambda d: float(d))

    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="session")
async def setup_test_db(test_engine):
    """テスト用テーブルをセットアップする"""
    async with test_engine.begin() as conn:
        # 顧客テーブル
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS customers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id INTEGER NOT NULL DEFAULT 999,
                name VARCHAR(255) NOT NULL,
                email VARCHAR(255),
                phone VARCHAR(50),
                company VARCHAR(255),
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        # 案件テーブル
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS deals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id INTEGER NOT NULL DEFAULT 999,
                customer_id INTEGER REFERENCES customers(id),
                title VARCHAR(255) NOT NULL,
                amount NUMERIC(15, 2),
                status VARCHAR(50) DEFAULT 'open',
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
        await conn.execute(text("DELETE FROM customers"))


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


@pytest_asyncio.fixture
async def client(db_session):
    """
    テスト用HTTPクライアント。
    認証・DB・audit_logをモックしてSQLiteで動作させる。
    """
    from app.main import app
    from app.auth.dependencies import get_current_user, get_current_tenant
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
    # audit_logのスキーマ指定をSQLite互換に差し替え
    with patch("app.routers.customers.record_audit_log", _make_noop_audit_log()), \
         patch("app.routers.deals.record_audit_log", _make_noop_audit_log()), \
         patch("app.routers.orders.record_audit_log", _make_noop_audit_log()):
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

    app.dependency_overrides.clear()
