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

# Sprint 2 Reviewer Out-of-scope #1 (PR #510 follow-up) は別 Issue で起票推奨。
# 本 PR では各テスト側 (test_super_admin_*.py / test_tenant_admin_*.py 等) で
#   os.getenv("TEST_PG_URL") or os.getenv("RLS_TEST_DATABASE_URL")
# の alias パターンに統一する方針 (各 test の skipif で対応済)。
# ここで env 補完 (TEST_PG_URL := RLS_TEST_DATABASE_URL) すると、
# 以前 skip されていた inventory 系テストが PG migration / seed 未投入の
# CI 環境で大量に失敗するため、env 補完は CI への migration 適用とセットで
# 別 PR で扱う。本 PR では各 test 側の or 連結のみで前進する。

from unittest.mock import patch

# Python 3.14: mock.patch は target の親 package が submodule を attribute として
# 保持していることを要求する。app.auth.dependencies を先に import しておく。
import app.auth.dependencies  # noqa: F401

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import text, event
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

# pytest-asyncio 0.25+ で event_loop fixture の上書きは deprecated。
# pytest.ini の asyncio_default_fixture_loop_scope = session で
# session-scoped fixture が同じイベントループを共有できるようにしている。


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    """SQLiteインメモリエンジン"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    # SQLiteでNOW()を使えるようにし、Decimal型をサポートする + FK制約を有効化
    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_compat(dbapi_conn, connection_record):
        import sqlite3
        from decimal import Decimal
        dbapi_conn.create_function("NOW", 0, lambda: "2026-04-07 00:00:00+00:00")
        dbapi_conn.create_function("LPAD", 3, lambda s, n, pad: str(s).rjust(int(n), pad))
        sqlite3.register_adapter(Decimal, lambda d: float(d))
        # SQLite は FK 制約がデフォルト OFF。ON DELETE CASCADE と 409 テストのために ON にする
        dbapi_conn.execute("PRAGMA foreign_keys = ON")
        # SQLite の LIKE をデフォルトで case-insensitive 化
        # （アプリ側で ILIKE を使うクエリのテスト時互換性のため）
        dbapi_conn.execute("PRAGMA case_sensitive_like = OFF")

    # ILIKE は PostgreSQL 専用。SQLite で実行されるテストのために LIKE に置換する。
    # 識別子・文字列リテラル中の "ILIKE" は出ない前提（SQL DSL 上の比較演算子のみ）。
    # retval=True を付けて (statement, parameters) を返すと SQLAlchemy が rewrite を採用する。
    @event.listens_for(engine.sync_engine, "before_cursor_execute", retval=True)
    def rewrite_ilike_for_sqlite(conn, cursor, statement, parameters, context, executemany):
        if "ILIKE" in statement:
            statement = statement.replace(" ILIKE ", " LIKE ").replace("\nILIKE ", "\nLIKE ")
        # SQLite はスキーマプレフィックスを持たない。public.users → users に書き換える。
        if "public.users" in statement:
            statement = statement.replace("public.users", "users")
        return statement, parameters

    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="session")
async def setup_test_db(test_engine):
    """テスト用テーブルをセットアップする"""
    async with test_engine.begin() as conn:
        # 顧客テーブル（Phase 1 再設計: 正規化本体）
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS customers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id INTEGER NOT NULL DEFAULT 999,
                customer_code VARCHAR(20),
                lead_id INTEGER,
                sales_rep_id INTEGER,
                company_name VARCHAR(255),
                trust_level SMALLINT,
                priority_focus VARCHAR(50),
                per_order_amount NUMERIC(15,2),
                monthly_frequency SMALLINT,
                monthly_forecast NUMERIC(15,2),
                monthly_forecast_source VARCHAR(20),
                monthly_forecast_updated_at TIMESTAMP,
                meeting_requested BOOLEAN NOT NULL DEFAULT 0,
                billing_display_name VARCHAR(255),
                payment_recipient_name VARCHAR(255),
                fedex_account VARCHAR(100),
                shipping_note TEXT,
                primary_contact_channel VARCHAR(30),
                status VARCHAR(20) NOT NULL DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (tenant_id, customer_code)
            )
        """))
        # 顧客副テーブル（Phase 1 再設計）
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS customer_addresses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
                address_type VARCHAR(20) NOT NULL,
                name VARCHAR(255),
                email VARCHAR(255),
                telephone VARCHAR(50),
                tax_id VARCHAR(100),
                address_line_1 VARCHAR(255),
                address_line_2 VARCHAR(255),
                address_line_3 VARCHAR(255),
                city VARCHAR(100),
                state VARCHAR(100),
                zip VARCHAR(50),
                country_code CHAR(2),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS customer_sales_channels (
                customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
                channel VARCHAR(30) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (customer_id, channel)
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS customer_discord (
                customer_id INTEGER PRIMARY KEY REFERENCES customers(id) ON DELETE CASCADE,
                is_joined BOOLEAN NOT NULL DEFAULT 0,
                channel_id VARCHAR(50),
                user_id VARCHAR(50),
                invoice_webhook TEXT,
                shipment_webhook TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        # Phase 1-B-1: 連絡ツール別テーブル
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS customer_contact_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
                channel VARCHAR(30) NOT NULL,
                purpose VARCHAR(50),
                is_primary BOOLEAN NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        # Phase 1-B-2: companies + contacts 階層（Step 5b-1 で routers.companies/contacts のテスト用）
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS companies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id INTEGER NOT NULL DEFAULT 999,
                company_code VARCHAR(20) NOT NULL,
                lead_id INTEGER,
                sales_rep_id INTEGER,
                name VARCHAR(255) NOT NULL,
                name_en VARCHAR(255),
                normalized_name VARCHAR(255),
                industry VARCHAR(100),
                website VARCHAR(255),
                trust_level SMALLINT,
                priority_focus VARCHAR(50),
                per_order_amount NUMERIC(15,2),
                monthly_frequency SMALLINT,
                monthly_forecast NUMERIC(15,2),
                monthly_forecast_source VARCHAR(20),
                monthly_forecast_updated_at TIMESTAMP,
                billing_display_name VARCHAR(255),
                payment_recipient_name VARCHAR(255),
                fedex_account VARCHAR(100),
                shipping_note TEXT,
                status VARCHAR(20) NOT NULL DEFAULT 'active',
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (tenant_id, company_code)
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS contacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id INTEGER NOT NULL DEFAULT 999,
                company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
                contact_code VARCHAR(20) NOT NULL,
                lead_id INTEGER,
                surname VARCHAR(100),
                given_name VARCHAR(100),
                display_name VARCHAR(255),
                job_title VARCHAR(100),
                department VARCHAR(100),
                is_primary_contact BOOLEAN NOT NULL DEFAULT 0,
                primary_email VARCHAR(255),
                primary_phone VARCHAR(50),
                status VARCHAR(20) NOT NULL DEFAULT 'active',
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (tenant_id, contact_code)
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS company_addresses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
                address_type VARCHAR(20) NOT NULL,
                branch_name VARCHAR(100),
                name VARCHAR(255),
                email VARCHAR(255),
                telephone VARCHAR(50),
                tax_id VARCHAR(100),
                address_line_1 VARCHAR(255),
                address_line_2 VARCHAR(255),
                address_line_3 VARCHAR(255),
                city VARCHAR(100),
                state VARCHAR(100),
                zip VARCHAR(50),
                country_code CHAR(2),
                is_default BOOLEAN NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS company_sales_channels (
                company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
                channel VARCHAR(30) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (company_id, channel)
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS contact_emails (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
                email VARCHAR(255) NOT NULL,
                purpose VARCHAR(50),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (contact_id, email)
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS contact_discord (
                contact_id INTEGER PRIMARY KEY REFERENCES contacts(id) ON DELETE CASCADE,
                is_joined BOOLEAN NOT NULL DEFAULT 0,
                channel_id VARCHAR(50),
                user_id VARCHAR(50),
                invoice_webhook TEXT,
                shipment_webhook TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS contact_contact_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
                channel VARCHAR(30) NOT NULL,
                purpose VARCHAR(50),
                is_primary BOOLEAN NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        # 部分UNIQUE INDEX（migration 028-030 と同じ、二重防御検証用）
        await conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_company_addresses_one_default_test
            ON company_addresses (company_id, address_type) WHERE is_default = 1
        """))
        await conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_contacts_one_primary_per_company_test
            ON contacts (company_id) WHERE is_primary_contact = 1
        """))
        await conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_ccc_new_one_primary_per_contact_test
            ON contact_contact_channels (contact_id) WHERE is_primary = 1
        """))
        # スタッフ関連テーブル（Phase 1 再設計）
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS staff (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id INTEGER NOT NULL DEFAULT 999,
                user_id INTEGER,
                staff_code VARCHAR(20) NOT NULL,
                surname_jp VARCHAR(50) NOT NULL,
                given_name_jp VARCHAR(50) NOT NULL,
                surname_kana VARCHAR(100),
                given_name_kana VARCHAR(100),
                surname_en VARCHAR(100),
                given_name_en VARCHAR(100),
                primary_email VARCHAR(255) NOT NULL,
                discord_user_id VARCHAR(50),
                role_id INTEGER NOT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'active',
                firebase_uid VARCHAR(128) UNIQUE,
                is_employee BOOLEAN NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (tenant_id, staff_code)
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS staff_emails (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                staff_id INTEGER NOT NULL REFERENCES staff(id) ON DELETE CASCADE,
                email VARCHAR(255) NOT NULL,
                purpose VARCHAR(50),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (staff_id, email)
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS staff_ui_preferences (
                staff_id INTEGER PRIMARY KEY REFERENCES staff(id) ON DELETE CASCADE,
                dark_mode BOOLEAN NOT NULL DEFAULT 0,
                show_chat_menu BOOLEAN NOT NULL DEFAULT 1,
                show_sales_menu BOOLEAN NOT NULL DEFAULT 1,
                show_settings_menu BOOLEAN NOT NULL DEFAULT 1,
                show_admin_menu BOOLEAN NOT NULL DEFAULT 0,
                show_buddy_menu BOOLEAN NOT NULL DEFAULT 1,
                show_sidebar BOOLEAN NOT NULL DEFAULT 1,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS bots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id INTEGER NOT NULL DEFAULT 999,
                bot_code VARCHAR(20) NOT NULL,
                display_name VARCHAR(100) NOT NULL,
                purpose VARCHAR(50) NOT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'active',
                api_key_hash VARCHAR(128) NOT NULL,
                discord_user_id VARCHAR(50),
                sender_email VARCHAR(255),
                owner_staff_id INTEGER NOT NULL REFERENCES staff(id),
                last_executed_at TIMESTAMP,
                execution_count INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (tenant_id, bot_code)
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
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                next_action VARCHAR(500),
                next_action_date DATE,
                challenge TEXT,
                meeting_memo TEXT,
                meeting_impression VARCHAR(50),
                cs_memo TEXT,
                sales_form VARCHAR(50),
                competitor_check BOOLEAN NOT NULL DEFAULT 0,
                per_order_amount NUMERIC(15, 2),
                monthly_frequency NUMERIC(10, 2),
                english_name VARCHAR(255)
            )
        """))
        # 案件テーブル（Step 5d: 旧 customer_id 列削除済）
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS deals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id INTEGER NOT NULL DEFAULT 999,
                deal_code VARCHAR(20),
                company_id INTEGER REFERENCES companies(id),
                contact_id INTEGER REFERENCES contacts(id),
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
        # 注文テーブル（Step 5d: 旧 customer_id 列削除済）
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id INTEGER NOT NULL DEFAULT 999,
                company_id INTEGER REFERENCES companies(id),
                contact_id INTEGER REFERENCES contacts(id),
                deal_id INTEGER REFERENCES deals(id),
                invoice_id INTEGER,
                order_number VARCHAR(100) NOT NULL,
                total_amount NUMERIC(15, 2),
                currency VARCHAR(10) DEFAULT 'JPY',
                status VARCHAR(50) DEFAULT 'pending',
                shipping_carrier VARCHAR(50),
                shipping_fee NUMERIC(15, 2),
                tracking_number VARCHAR(200),
                shipped_at TIMESTAMP,
                delivered_at TIMESTAMP,
                shipping_country VARCHAR(100),
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        # ADR-021 Sprint 2: 売上情報テーブル（migration 047）
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS order_financials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL UNIQUE
                    REFERENCES orders(id) ON DELETE CASCADE,
                tenant_id INTEGER NOT NULL DEFAULT 999,
                revenue_amount NUMERIC(14, 2) DEFAULT 0,
                purchase_cost NUMERIC(14, 2) DEFAULT 0,
                purchase_shipping NUMERIC(14, 2) DEFAULT 0,
                paypal_fee NUMERIC(14, 2) DEFAULT 0,
                wise_fee NUMERIC(14, 2) DEFAULT 0,
                exchange_fee NUMERIC(14, 2) DEFAULT 0,
                outsource_fee NUMERIC(14, 2) DEFAULT 0,
                packing_fee NUMERIC(14, 2) DEFAULT 0,
                ad_cost NUMERIC(14, 2) DEFAULT 0,
                return_fee NUMERIC(14, 2) DEFAULT 0,
                refund_amount NUMERIC(14, 2) DEFAULT 0,
                commission_base_amount NUMERIC(14, 2) DEFAULT 0,
                tax_refund NUMERIC(14, 2) DEFAULT 0,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        # ADR-021 Sprint 4: 仕入情報テーブル（migration 049）
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS order_purchase_details (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL UNIQUE
                    REFERENCES orders(id) ON DELETE CASCADE,
                tenant_id INTEGER NOT NULL DEFAULT 999,
                purchase_staff TEXT,
                purchase_date DATE,
                transaction_no TEXT,
                supplier_name TEXT,
                supplier_url TEXT,
                purchase_amount NUMERIC(14, 2) DEFAULT 0,
                purchase_quantity INTEGER DEFAULT 0,
                purchase_total NUMERIC(14, 2) DEFAULT 0,
                purchase_shipping NUMERIC(14, 2) DEFAULT 0,
                carrier_name TEXT,
                waybill_no TEXT,
                purchase_note TEXT,
                purchase_status TEXT NOT NULL DEFAULT ''
                    CHECK (purchase_status IN ('', 'confirmed')),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        # ADR-021 Sprint 3: 発送情報テーブル（migration 048）
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS order_shipping_details (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL UNIQUE
                    REFERENCES orders(id) ON DELETE CASCADE,
                tenant_id INTEGER NOT NULL DEFAULT 999,
                recipient_name VARCHAR(255),
                phone VARCHAR(50),
                email VARCHAR(255),
                tax_number VARCHAR(100),
                address1 VARCHAR(255),
                address2 VARCHAR(255),
                address3 VARCHAR(255),
                city VARCHAR(100),
                state_code VARCHAR(20),
                zip_code VARCHAR(50),
                country_code VARCHAR(10),
                length_cm NUMERIC(8, 2),
                width_cm NUMERIC(8, 2),
                height_cm NUMERIC(8, 2),
                weight_kg NUMERIC(8, 3),
                volume_g NUMERIC(10, 2),
                box_count INTEGER,
                packing_memo TEXT,
                packing_type VARCHAR(50),
                inspection_status VARCHAR(50),
                item_description VARCHAR(500),
                item_price_usd NUMERIC(12, 2),
                exchange_rate NUMERIC(12, 6),
                hs_code VARCHAR(50),
                tax_id VARCHAR(100),
                fedex_id VARCHAR(100),
                carrier VARCHAR(20)
                    CHECK (carrier IS NULL OR carrier IN ('elogi', 'fedex', 'dhl', 'yamato', 'other')),
                ship_method VARCHAR(50),
                ship_date DATE,
                tracking_number VARCHAR(200),
                est_shipping_fee NUMERIC(12, 2),
                label_issued_at TIMESTAMP,
                pickup_requested_at TIMESTAMP,
                shipped_at TIMESTAMP,
                notified_at TIMESTAMP,
                ship_memo TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        # ADR-021 Sprint 5: テナント別報酬計算設定（migration 050）
        # SQLite には JSONB が無いので TEXT に JSON 文字列で保存する。
        # 本番 PG では JSONB だがアプリ側のシリアライズ/パースで吸収する。
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS tenant_commission_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id INTEGER NOT NULL DEFAULT 999,
                commission_rates TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (tenant_id)
            )
        """))
        # ADR-021 Sprint 5: 受注ごとの報酬（migration 050）
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS order_commissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL
                    REFERENCES orders(id) ON DELETE CASCADE,
                tenant_id INTEGER NOT NULL DEFAULT 999,
                role TEXT NOT NULL
                    CHECK (role IN ('sales','order','ship','purchase','trouble')),
                staff_id INTEGER REFERENCES staff(id) ON DELETE SET NULL,
                calculated_amount NUMERIC(14,2) NOT NULL DEFAULT 0,
                calculated_at TIMESTAMP,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (order_id, role)
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
        # === Phase 2 テーブル ===
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id INTEGER NOT NULL DEFAULT 999,
                product_code VARCHAR(20),
                category VARCHAR(100),
                mark VARCHAR(100),
                name_en VARCHAR(255),
                name_ja VARCHAR(255) NOT NULL,
                status VARCHAR(20) DEFAULT 'active',
                condition VARCHAR(50),
                unit_price NUMERIC(15, 2),
                quantity INTEGER DEFAULT 0,
                weight NUMERIC(10, 3),
                notes TEXT,
                release_date DATE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS shipping_zones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id INTEGER NOT NULL DEFAULT 999,
                country_code VARCHAR(3) NOT NULL,
                country_name VARCHAR(100) NOT NULL,
                carrier VARCHAR(50) NOT NULL,
                zone VARCHAR(20) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(tenant_id, country_code, carrier)
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS shipping_rates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id INTEGER NOT NULL DEFAULT 999,
                carrier VARCHAR(50) NOT NULL,
                zone VARCHAR(20) NOT NULL,
                weight_min NUMERIC(10, 3) NOT NULL,
                weight_max NUMERIC(10, 3) NOT NULL,
                price NUMERIC(15, 2) NOT NULL,
                currency VARCHAR(10) DEFAULT 'JPY',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS quotes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id INTEGER NOT NULL DEFAULT 999,
                quote_code VARCHAR(20),
                deal_id INTEGER REFERENCES deals(id),
                company_id INTEGER NOT NULL REFERENCES companies(id),
                contact_id INTEGER REFERENCES contacts(id),
                currency VARCHAR(10) DEFAULT 'JPY',
                subtotal NUMERIC(15, 2) DEFAULT 0,
                shipping_fee NUMERIC(15, 2) DEFAULT 0,
                tax_amount NUMERIC(15, 2) DEFAULT 0,
                total_amount NUMERIC(15, 2) DEFAULT 0,
                status VARCHAR(20) DEFAULT 'draft',
                validity_date DATE,
                shipping_country VARCHAR(100),
                shipping_carrier VARCHAR(50),
                delivery_info TEXT,
                pdf_url VARCHAR(500),
                notes TEXT,
                created_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS quote_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                quote_id INTEGER NOT NULL REFERENCES quotes(id) ON DELETE CASCADE,
                product_id INTEGER REFERENCES products(id),
                product_name VARCHAR(255) NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 1,
                unit_price NUMERIC(15, 2) NOT NULL,
                weight NUMERIC(10, 3),
                subtotal NUMERIC(15, 2) NOT NULL,
                sort_order INTEGER DEFAULT 0
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS invoices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id INTEGER NOT NULL DEFAULT 999,
                invoice_number VARCHAR(30),
                quote_id INTEGER REFERENCES quotes(id),
                company_id INTEGER NOT NULL REFERENCES companies(id),
                contact_id INTEGER REFERENCES contacts(id),
                currency VARCHAR(10) DEFAULT 'JPY',
                subtotal NUMERIC(15, 2) DEFAULT 0,
                shipping_fee NUMERIC(15, 2) DEFAULT 0,
                tax_amount NUMERIC(15, 2) DEFAULT 0,
                total_amount NUMERIC(15, 2) DEFAULT 0,
                exchange_rate_jpy NUMERIC(12, 4),
                exchange_rate_usd NUMERIC(12, 4),
                amount_jpy NUMERIC(15, 2),
                amount_usd NUMERIC(15, 2),
                payment_method VARCHAR(50),
                status VARCHAR(20) DEFAULT 'draft',
                branch_number INTEGER DEFAULT 1,
                pdf_url VARCHAR(500),
                erp_key VARCHAR(100),
                issued_at TIMESTAMP,
                due_date DATE,
                paid_at TIMESTAMP,
                voided_at TIMESTAMP,
                void_reason VARCHAR(500),
                notes TEXT,
                created_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS invoice_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_id INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
                product_id INTEGER REFERENCES products(id),
                product_name VARCHAR(255) NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 1,
                unit_price NUMERIC(15, 2) NOT NULL,
                weight NUMERIC(10, 3),
                subtotal NUMERIC(15, 2) NOT NULL,
                sort_order INTEGER DEFAULT 0
            )
        """))
        # === Phase 3 テーブル ===
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS suppliers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id INTEGER NOT NULL DEFAULT 999,
                supplier_code VARCHAR(20),
                name VARCHAR(255) NOT NULL,
                contact_name VARCHAR(255),
                email VARCHAR(255),
                phone VARCHAR(50),
                address TEXT,
                notes TEXT,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS purchase_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id INTEGER NOT NULL DEFAULT 999,
                po_number VARCHAR(20),
                supplier_id INTEGER NOT NULL REFERENCES suppliers(id),
                status VARCHAR(20) DEFAULT 'draft',
                total_amount NUMERIC(15, 2) DEFAULT 0,
                ordered_at TIMESTAMP,
                received_at TIMESTAMP,
                notes TEXT,
                created_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS purchase_order_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                purchase_order_id INTEGER NOT NULL REFERENCES purchase_orders(id) ON DELETE CASCADE,
                product_id INTEGER NOT NULL REFERENCES products(id),
                quantity INTEGER NOT NULL DEFAULT 1,
                unit_cost NUMERIC(15, 2) NOT NULL,
                subtotal NUMERIC(15, 2) NOT NULL,
                sort_order INTEGER DEFAULT 0
            )
        """))
        # Sprint 8 / F8: テナント発行者情報 (PO PDF / メール差出人)
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS tenant_profile (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_name VARCHAR(255),
                company_name_en VARCHAR(255),
                address TEXT,
                phone VARCHAR(50),
                email VARCHAR(255),
                website VARCHAR(255),
                seal_image_url TEXT,
                default_language CHAR(2) NOT NULL DEFAULT 'ja',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        # === Phase 4 テーブル ===
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS notification_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id INTEGER NOT NULL DEFAULT 999,
                channel_type VARCHAR(20) DEFAULT 'discord',
                channel_name VARCHAR(100) NOT NULL,
                webhook_url VARCHAR(500) NOT NULL,
                event_types TEXT DEFAULT '[]',
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS notification_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id INTEGER NOT NULL DEFAULT 999,
                channel_id INTEGER,
                event_type VARCHAR(50) NOT NULL,
                title VARCHAR(255) NOT NULL,
                message TEXT,
                status VARCHAR(20) DEFAULT 'pending',
                sent_at TIMESTAMP,
                error_message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS staff_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id INTEGER NOT NULL DEFAULT 999,
                report_code VARCHAR(20),
                report_type VARCHAR(20) NOT NULL,
                user_id INTEGER NOT NULL,
                period VARCHAR(20) NOT NULL,
                review TEXT,
                goals TEXT,
                challenges TEXT,
                self_evaluation TEXT,
                ai_feedback TEXT,
                reviewer_id INTEGER,
                reviewer_comment TEXT,
                reviewed_at TIMESTAMP,
                submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS archives (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id INTEGER NOT NULL DEFAULT 999,
                source_table VARCHAR(100) NOT NULL,
                source_id INTEGER NOT NULL,
                archived_data TEXT NOT NULL,
                archived_by INTEGER,
                archived_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                restored_at TIMESTAMP,
                restored_by INTEGER
            )
        """))
        # public.users 相当（SQLiteにはスキーマがないのでusersテーブルで代用）
        # ADR-027: locale カラム追加 / ADR-033: theme カラム追加
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id INTEGER NOT NULL DEFAULT 999,
                username VARCHAR(255),
                email VARCHAR(255),
                role VARCHAR(50) DEFAULT 'user',
                is_active BOOLEAN DEFAULT TRUE,
                locale VARCHAR(10) NOT NULL DEFAULT 'ja',
                theme VARCHAR(10) NOT NULL DEFAULT 'light'
            )
        """))
        # テストユーザー投入
        await conn.execute(text("""
            INSERT OR IGNORE INTO users (id, tenant_id, username, email, role, is_active, locale, theme)
            VALUES (999, 999, 'testuser', 'test@example.com', 'admin', TRUE, 'ja', 'light')
        """))
    yield


@pytest_asyncio.fixture
async def db_session(test_engine, setup_test_db):
    """各テスト用のDBセッション。テスト後にデータをクリーンアップ。"""
    async_session = sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session
        await session.rollback()

    # テスト後にデータを全削除（FK制約順）
    async with test_engine.begin() as conn:
        await conn.execute(text("DELETE FROM audit_logs"))
        await conn.execute(text("DELETE FROM invoice_items"))
        await conn.execute(text("DELETE FROM invoices"))
        await conn.execute(text("DELETE FROM quote_items"))
        await conn.execute(text("DELETE FROM quotes"))
        await conn.execute(text("DELETE FROM shipping_rates"))
        await conn.execute(text("DELETE FROM shipping_zones"))
        await conn.execute(text("DELETE FROM archives"))
        await conn.execute(text("DELETE FROM staff_reports"))
        await conn.execute(text("DELETE FROM notification_logs"))
        await conn.execute(text("DELETE FROM notification_channels"))
        await conn.execute(text("DELETE FROM purchase_order_items"))
        await conn.execute(text("DELETE FROM purchase_orders"))
        await conn.execute(text("DELETE FROM suppliers"))
        # Sprint 8: tenant_profile
        await conn.execute(text("DELETE FROM tenant_profile"))
        await conn.execute(text("DELETE FROM order_commissions"))
        await conn.execute(text("DELETE FROM tenant_commission_settings"))
        await conn.execute(text("DELETE FROM order_shipping_details"))
        await conn.execute(text("DELETE FROM order_purchase_details"))
        await conn.execute(text("DELETE FROM order_financials"))
        await conn.execute(text("DELETE FROM orders"))
        await conn.execute(text("DELETE FROM products"))
        await conn.execute(text("DELETE FROM deals"))
        await conn.execute(text("DELETE FROM leads"))
        # Phase 1 再設計の副テーブル → 本体の順
        await conn.execute(text("DELETE FROM customer_contact_channels"))
        await conn.execute(text("DELETE FROM customer_discord"))
        await conn.execute(text("DELETE FROM customer_sales_channels"))
        await conn.execute(text("DELETE FROM customer_addresses"))
        # Phase 1-B-2 Step 5b-1: companies/contacts 副テーブル → 本体
        await conn.execute(text("DELETE FROM contact_contact_channels"))
        await conn.execute(text("DELETE FROM contact_discord"))
        await conn.execute(text("DELETE FROM contact_emails"))
        await conn.execute(text("DELETE FROM contacts"))
        await conn.execute(text("DELETE FROM company_sales_channels"))
        await conn.execute(text("DELETE FROM company_addresses"))
        await conn.execute(text("DELETE FROM companies"))
        await conn.execute(text("DELETE FROM bots"))
        await conn.execute(text("DELETE FROM staff_ui_preferences"))
        await conn.execute(text("DELETE FROM staff_emails"))
        await conn.execute(text("DELETE FROM staff"))
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
    # Phase 2
    "products.view", "products.create", "products.update", "products.delete",
    "quotes.view", "quotes.create", "quotes.update", "quotes.delete", "quotes.approve",
    "invoices.view", "invoices.create", "invoices.update", "invoices.void",
    "shipping.view", "shipping.manage", "shipping.calculate",
    # Phase 3
    "suppliers.view", "suppliers.create", "suppliers.update", "suppliers.delete",
    "purchase_orders.view", "purchase_orders.create", "purchase_orders.update", "purchase_orders.receive",
    # Phase 4
    "notifications.view", "notifications.manage",
    "staff_reports.view_own", "staff_reports.view_team", "staff_reports.create", "staff_reports.review",
    "archive.view", "archive.manage",
    # Phase 5
    "shifts.view", "shifts.manage",
    "buddy.view_own", "buddy.review", "buddy.manage",
    "badges.view", "badges.manage",
    "erp.view", "erp.sync",
    # Phase 1 再設計: staff / bots
    "staff.view", "staff.create", "staff.update", "staff.delete",
    "bots.view", "bots.create", "bots.update", "bots.delete",
    # Sprint 8 / F8: テナント発行者情報 (PO PDF / メール差出人)
    "tenant.profile.view", "tenant.profile.edit",
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
    # audit_log と権限チェックをまとめてモック（ネスト制限回避のため ExitStack 使用）
    from contextlib import ExitStack
    _audit_targets = [
        "app.routers.customers", "app.routers.deals", "app.routers.orders",
        "app.routers.order_financials",
        "app.routers.order_shipping_details",
        "app.routers.order_purchase_details",
        # ADR-021 Sprint 5: 報酬計算 MVP
        "app.routers.tenant_commission_settings",
        "app.routers.order_commissions",
        "app.routers.leads", "app.routers.teams", "app.routers.roles",
        "app.routers.products", "app.routers.shipping", "app.routers.quotes",
        "app.routers.invoices", "app.routers.suppliers", "app.routers.purchase_orders",
        "app.routers.notifications",
        "app.routers.staff_reports", "app.routers.archives",
        "app.routers.shifts", "app.routers.buddy", "app.routers.badges",
        "app.routers.erp",
        # Phase 1-B-2 Step 5b-1: 新 routers
        "app.routers.companies", "app.routers.contacts",
        # Phase 1-B-1 wiring (B-1): /staff/me 追加に伴うスタッフ系テスト
        "app.routers.staff",
        # Sprint 8 / F8: テナント発行者情報
        "app.routers.tenant_profile",
    ]
    with ExitStack() as stack:
        for target in _audit_targets:
            stack.enter_context(patch(f"{target}.record_audit_log", _make_noop_audit_log()))
        stack.enter_context(patch("app.auth.dependencies.load_user_permissions", _mock_load_user_permissions))
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

    app.dependency_overrides.clear()
