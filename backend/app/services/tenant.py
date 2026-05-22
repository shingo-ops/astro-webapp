from __future__ import annotations

"""
テナント別スキーマ自動生成サービス。

新しいテナントが登録されるたびに:
  1. public.tenants に企業情報を保存
  2. tenant_{id:03d} スキーマを自動作成
  3. スキーマ内に業務テーブル（customers, deals, orders, audit_logs,
     roles, role_permissions, user_roles, leads, teams, team_members）を作成
  4. Row Level Security（RLS）ポリシーを自動適用
  5. システムロール（オーナー/メンバー）をシード

たとえ話:
  新しい入居者（テナント企業）が契約したら、
  専用の鍵付き個室が自動的に用意される仕組み。

変更履歴:
  2026-04-16: Phase 1対応（roles/leads/teams追加、system_rolesシード）
  2026-05-07: ADR-015 段階分割 Phase 1 — leads にカルテ・AI 収集・返信速度・
    次回アクション列を追加、lead_playbook 新設、customer_contact_channels に
    external_id 追加（migration 046 と同じ列を新テナント作成時から備える）
"""

import re

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


# GAS版互換の既定ロール定義。テナント作成時に自動シードされる。
#
# 「permissions」キーの値:
#   - "ALL": 全権限付与
#   - "ALL_EXCEPT_SYSTEM_MANAGE": system.manage 以外の全権限
#   - list[str]: 指定された権限キーのみ付与
#
# is_system=True の役割は編集/削除不可（オーナーのみ）。
# その他の4役割は default として作成されるがテナント管理者が自由に編集可能。
DEFAULT_ROLES = [
    {
        "name": "オーナー",
        "color": "#ef4444",  # 赤
        "priority": 1000,
        "is_system": True,
        "permissions": "ALL",
        "description": "テナントの全権限を持つシステムロール",
    },
    {
        "name": "システム管理者",
        "color": "#a855f7",  # 紫
        "priority": 900,
        "is_system": False,
        "permissions": "ALL_EXCEPT_SYSTEM_MANAGE",
        "description": "システム設定以外の全機能を管理する管理者",
    },
    {
        "name": "リーダー",
        "color": "#3b82f6",  # 青
        "priority": 500,
        "is_system": False,
        "permissions": [
            "dashboard.view", "reports.view", "reports.export",
            "customers.view", "customers.update",
            "leads.view", "leads.create", "leads.update", "leads.delete", "leads.convert",
            "deals.view", "deals.update",
            "orders.view",
            "teams.view", "teams.manage_members",
            "roles.view",
            # Phase 2
            "products.view",
            "quotes.view", "quotes.update", "quotes.approve",
            "invoices.view", "invoices.update",
            "shipping.view", "shipping.calculate",
            # Phase 3
            "suppliers.view",
            "purchase_orders.view", "purchase_orders.create", "purchase_orders.update", "purchase_orders.receive",
            # Phase 4
            "notifications.view",
            "staff_reports.view_own", "staff_reports.view_team", "staff_reports.create", "staff_reports.review",
            "archive.view",
        ],
        "description": "チーム単位でリードや案件を統括するリーダー",
    },
    {
        "name": "営業",
        "color": "#22c55e",  # 緑
        "priority": 300,
        "is_system": False,
        "permissions": [
            "dashboard.view", "reports.view",
            "customers.view", "customers.create", "customers.update",
            "leads.view", "leads.create", "leads.update", "leads.convert",
            "deals.view", "deals.create", "deals.update",
            "orders.view", "orders.create", "orders.update",
            # Phase 2
            "products.view",
            "quotes.view", "quotes.create", "quotes.update",
            "invoices.view", "invoices.create",
            "shipping.view", "shipping.calculate",
            # Phase 3
            "suppliers.view",
            "purchase_orders.view", "purchase_orders.create",
            # Phase 4
            "staff_reports.view_own", "staff_reports.create",
        ],
        "description": "顧客獲得から受注までを担当する営業担当者",
    },
    {
        "name": "CS",
        "color": "#f97316",  # オレンジ
        "priority": 300,
        "is_system": False,
        "permissions": [
            "dashboard.view", "reports.view",
            "customers.view", "customers.update",
            "leads.view",
            "deals.view",
            "orders.view",
            "teams.view",
            # Phase 2
            "products.view",
            "quotes.view",
            "invoices.view",
            "shipping.view",
            # Phase 4
            "staff_reports.view_own", "staff_reports.create",
        ],
        "description": "顧客からの問い合わせ対応を担当するカスタマーサポート",
    },
]


# 新規ユーザー登録時に自動付与するデフォルトロール名（auth.py から参照）
DEFAULT_NEW_USER_ROLE = "CS"


# テナントスキーマ内に作成する業務テーブルのSQL定義
_TENANT_TABLES_SQL = """
-- 顧客データ（Phase 1 再設計: 正規化された本体 + 3副テーブル）
-- migration 015 と同等の構造。sales_rep_id の FK は staff テーブル作成後に付与
CREATE TABLE IF NOT EXISTS {schema}.customers (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL DEFAULT {tenant_id},
    customer_code VARCHAR(20) NOT NULL,
    lead_id INTEGER,                                   -- FK は leads 作成後に付与（下記ALTER）
    sales_rep_id INTEGER,                              -- FK は staff 作成後に付与（下記ALTER）
    company_name VARCHAR(255),
    trust_level SMALLINT CHECK (trust_level IS NULL OR trust_level BETWEEN 1 AND 5),
    priority_focus VARCHAR(50),
    per_order_amount NUMERIC(15,2),
    monthly_frequency SMALLINT,
    monthly_forecast NUMERIC(15,2),
    monthly_forecast_source VARCHAR(20)
        CHECK (monthly_forecast_source IS NULL OR monthly_forecast_source IN ('manual','ai_analysis')),
    monthly_forecast_updated_at TIMESTAMPTZ,
    meeting_requested BOOLEAN NOT NULL DEFAULT FALSE,
    billing_display_name VARCHAR(255),
    payment_recipient_name VARCHAR(255),
    fedex_account VARCHAR(100),
    shipping_note TEXT,
    primary_contact_channel VARCHAR(30),
    status VARCHAR(20) NOT NULL DEFAULT 'active'
        CHECK (status IN ('active','inactive','archived','pending_dedup_review')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, customer_code)
);

CREATE INDEX IF NOT EXISTS idx_customers_tenant_id ON {schema}.customers (tenant_id);
CREATE INDEX IF NOT EXISTS idx_customers_lead_id ON {schema}.customers (lead_id);
CREATE INDEX IF NOT EXISTS idx_customers_sales_rep_id ON {schema}.customers (sales_rep_id);
CREATE INDEX IF NOT EXISTS idx_customers_status ON {schema}.customers (status);

-- 顧客住所（billing / delivery の2行を持つ副テーブル、将来は複数配送先にも対応）
CREATE TABLE IF NOT EXISTS {schema}.customer_addresses (
    id SERIAL PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES {schema}.customers(id) ON DELETE CASCADE,
    address_type VARCHAR(20) NOT NULL CHECK (address_type IN ('billing','delivery')),
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
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_customer_addresses_customer_id ON {schema}.customer_addresses (customer_id);
CREATE INDEX IF NOT EXISTS idx_customer_addresses_type ON {schema}.customer_addresses (customer_id, address_type);

-- 顧客の販売チャネル（実店舗/EC/配信/PF 等、複数持てる中間テーブル）
CREATE TABLE IF NOT EXISTS {schema}.customer_sales_channels (
    customer_id INTEGER NOT NULL REFERENCES {schema}.customers(id) ON DELETE CASCADE,
    channel VARCHAR(30) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (customer_id, channel)
);

-- 連絡ツール（Phase 1-B-1: 複数チャネル × 用途の多対多）
-- ADR-015 §3: external_id は SNS プラットフォーム上のユーザー ID（既存顧客 dedup 用）
CREATE TABLE IF NOT EXISTS {schema}.customer_contact_channels (
    id SERIAL PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES {schema}.customers(id) ON DELETE CASCADE,
    channel VARCHAR(30) NOT NULL,
    purpose VARCHAR(50),
    is_primary BOOLEAN NOT NULL DEFAULT FALSE,
    external_id VARCHAR(100),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ccc_customer_id ON {schema}.customer_contact_channels (customer_id);
CREATE INDEX IF NOT EXISTS idx_ccc_channel ON {schema}.customer_contact_channels (channel);
CREATE UNIQUE INDEX IF NOT EXISTS idx_ccc_one_primary_per_customer
    ON {schema}.customer_contact_channels (customer_id) WHERE is_primary = TRUE;
CREATE INDEX IF NOT EXISTS idx_ccc_channel_external_id
    ON {schema}.customer_contact_channels (channel, external_id) WHERE external_id IS NOT NULL;

-- Phase 1-B-2: companies + contacts 階層（新テナントは最初から新構造）
CREATE TABLE IF NOT EXISTS {schema}.companies (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL DEFAULT {tenant_id},
    company_code VARCHAR(20) NOT NULL,
    lead_id INTEGER,                                   -- FK は leads 作成後に付与
    name VARCHAR(255) NOT NULL,
    name_en VARCHAR(255),
    normalized_name VARCHAR(255),
    -- is_individual は Phase 1-B-2 Step 5a で削除（個人/法人の区別を撤廃、migration 033）
    industry VARCHAR(100),
    website VARCHAR(255),
    trust_level SMALLINT CHECK (trust_level IS NULL OR trust_level BETWEEN 1 AND 5),
    priority_focus VARCHAR(50),
    per_order_amount NUMERIC(15,2),
    monthly_frequency SMALLINT,
    monthly_forecast NUMERIC(15,2),
    monthly_forecast_source VARCHAR(20)
        CHECK (monthly_forecast_source IS NULL OR monthly_forecast_source IN ('manual','ai_analysis')),
    monthly_forecast_updated_at TIMESTAMPTZ,
    billing_display_name VARCHAR(255),
    payment_recipient_name VARCHAR(255),
    fedex_account VARCHAR(100),
    shipping_note TEXT,
    status VARCHAR(20) NOT NULL DEFAULT 'active'
        CHECK (status IN ('active','inactive','archived','pending_dedup_review')),
    sales_rep_id INTEGER,                              -- FK は staff 作成後に付与
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, company_code)
);
CREATE INDEX IF NOT EXISTS idx_companies_tenant_id ON {schema}.companies (tenant_id);
CREATE INDEX IF NOT EXISTS idx_companies_normalized_name ON {schema}.companies (normalized_name);
CREATE INDEX IF NOT EXISTS idx_companies_lead_id ON {schema}.companies (lead_id);
CREATE INDEX IF NOT EXISTS idx_companies_sales_rep_id ON {schema}.companies (sales_rep_id);
CREATE INDEX IF NOT EXISTS idx_companies_status ON {schema}.companies (status);

CREATE TABLE IF NOT EXISTS {schema}.contacts (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL DEFAULT {tenant_id},
    company_id INTEGER NOT NULL REFERENCES {schema}.companies(id) ON DELETE CASCADE,
    contact_code VARCHAR(20) NOT NULL,
    lead_id INTEGER,                                   -- FK は leads 作成後に付与
    surname VARCHAR(100),
    given_name VARCHAR(100),
    display_name VARCHAR(255),
    job_title VARCHAR(100),
    department VARCHAR(100),
    is_primary_contact BOOLEAN NOT NULL DEFAULT FALSE,
    primary_email VARCHAR(255),
    primary_phone VARCHAR(50),
    -- PR #163 (PR #145 残課題 Q2): pending_dedup_review 解消フローのため
    -- companies.status と CHECK 制約を揃える（migration 037 で既存テナントには
    -- backport 済）。新テナント作成時は最初からこの 4 値を許容する。
    status VARCHAR(20) NOT NULL DEFAULT 'active'
        CHECK (status IN ('active','inactive','archived','pending_dedup_review')),
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, contact_code)
);
CREATE INDEX IF NOT EXISTS idx_contacts_tenant_id ON {schema}.contacts (tenant_id);
CREATE INDEX IF NOT EXISTS idx_contacts_company_id ON {schema}.contacts (company_id);
CREATE INDEX IF NOT EXISTS idx_contacts_lead_id ON {schema}.contacts (lead_id);
CREATE INDEX IF NOT EXISTS idx_contacts_primary_email ON {schema}.contacts (primary_email);
CREATE UNIQUE INDEX IF NOT EXISTS idx_contacts_one_primary_per_company
    ON {schema}.contacts (company_id) WHERE is_primary_contact = TRUE;

-- companies/contacts 副テーブル 5本
CREATE TABLE IF NOT EXISTS {schema}.company_addresses (
    id SERIAL PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES {schema}.companies(id) ON DELETE CASCADE,
    address_type VARCHAR(20) NOT NULL CHECK (address_type IN ('billing','delivery')),
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
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_company_addresses_company_id ON {schema}.company_addresses (company_id);
CREATE INDEX IF NOT EXISTS idx_company_addresses_type ON {schema}.company_addresses (company_id, address_type);
CREATE UNIQUE INDEX IF NOT EXISTS idx_company_addresses_one_default
    ON {schema}.company_addresses (company_id, address_type) WHERE is_default = TRUE;

CREATE TABLE IF NOT EXISTS {schema}.company_sales_channels (
    company_id INTEGER NOT NULL REFERENCES {schema}.companies(id) ON DELETE CASCADE,
    channel VARCHAR(30) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (company_id, channel)
);

CREATE TABLE IF NOT EXISTS {schema}.contact_emails (
    id SERIAL PRIMARY KEY,
    contact_id INTEGER NOT NULL REFERENCES {schema}.contacts(id) ON DELETE CASCADE,
    email VARCHAR(255) NOT NULL,
    purpose VARCHAR(50),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (contact_id, email)
);
CREATE INDEX IF NOT EXISTS idx_contact_emails_contact_id ON {schema}.contact_emails (contact_id);

CREATE TABLE IF NOT EXISTS {schema}.contact_discord (
    contact_id INTEGER PRIMARY KEY REFERENCES {schema}.contacts(id) ON DELETE CASCADE,
    is_joined BOOLEAN NOT NULL DEFAULT FALSE,
    channel_id VARCHAR(50),
    user_id VARCHAR(50),
    invoice_webhook TEXT,
    shipment_webhook TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS {schema}.contact_contact_channels (
    id SERIAL PRIMARY KEY,
    contact_id INTEGER NOT NULL REFERENCES {schema}.contacts(id) ON DELETE CASCADE,
    channel VARCHAR(30) NOT NULL,
    purpose VARCHAR(50),
    is_primary BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ccc_new_contact_id ON {schema}.contact_contact_channels (contact_id);
CREATE INDEX IF NOT EXISTS idx_ccc_new_channel ON {schema}.contact_contact_channels (channel);
CREATE UNIQUE INDEX IF NOT EXISTS idx_ccc_new_one_primary_per_contact
    ON {schema}.contact_contact_channels (contact_id) WHERE is_primary = TRUE;

-- Phase 1-B-2 Step 5d / PR γ:
--   _customer_migration_map は migration 036 で DROP 済。
--   新テナント作成時は本テーブル不要のため CREATE TABLE ブロックを撤去した。
--   過去履歴: migration 031 で追加 → migration 034 で UNIQUE 付与 → migration 036 で DROP。

-- Discord連携（任意、使う顧客のみ1行）
CREATE TABLE IF NOT EXISTS {schema}.customer_discord (
    customer_id INTEGER PRIMARY KEY REFERENCES {schema}.customers(id) ON DELETE CASCADE,
    is_joined BOOLEAN NOT NULL DEFAULT FALSE,
    channel_id VARCHAR(50),
    user_id VARCHAR(50),
    invoice_webhook TEXT,
    shipment_webhook TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- リード管理
-- ADR-015 §1〜§5 のカルテ・AI 収集・返信速度・次回アクション列を含める
-- （migration 046 と同じ列を新テナント作成時から備える）
CREATE TABLE IF NOT EXISTS {schema}.leads (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL DEFAULT {tenant_id},
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
    -- ADR-015 §1/§2: AI 自動収集データ
    country VARCHAR(100),
    target_titles VARCHAR(500),
    -- ADR-015 §3: 返信速度トラッキング
    first_inquiry_at TIMESTAMPTZ,
    first_response_at TIMESTAMPTZ,
    first_response_seconds INTEGER,
    -- ADR-015 §4: カルテ AI 補助対象
    sales_form VARCHAR(50),
    competitor_check BOOLEAN NOT NULL DEFAULT FALSE,
    cs_memo TEXT,
    per_order_amount NUMERIC(15, 2),
    monthly_frequency NUMERIC(10, 2),
    monthly_forecast_source VARCHAR(50),
    -- ADR-015 §4: 営業担当が記入する列
    challenge TEXT,
    english_name VARCHAR(255),
    meeting_impression VARCHAR(50),
    meeting_memo TEXT,
    -- ADR-015 §5: ダッシュボードの次回アクション
    next_action VARCHAR(500),
    next_action_date DATE,
    -- ADR-015 §1/§2/§3: AI 収集ステート
    ai_collection_state VARCHAR(20),
    escalation_flag BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_leads_next_action_date
    ON {schema}.leads (next_action_date) WHERE next_action_date IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_leads_ai_collection_state
    ON {schema}.leads (ai_collection_state) WHERE ai_collection_state IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_leads_escalation_flag
    ON {schema}.leads (escalation_flag) WHERE escalation_flag = TRUE;

-- ADR-015 §7: テナント別 AI 対応プレイブック
CREATE TABLE IF NOT EXISTS {schema}.lead_playbook (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL DEFAULT {tenant_id},
    name VARCHAR(100) NOT NULL DEFAULT 'default',
    greeting_message TEXT,
    questions JSONB NOT NULL DEFAULT '[]'::jsonb,
    assignment_condition VARCHAR(50) NOT NULL DEFAULT 'all_required',
    assignment_after_n_turns INTEGER,
    assignment_message TEXT,
    assignment_method VARCHAR(50) NOT NULL DEFAULT 'manual',
    country_assignment_map JSONB,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, name)
);
CREATE INDEX IF NOT EXISTS idx_lead_playbook_active
    ON {schema}.lead_playbook (tenant_id) WHERE is_active = TRUE;

-- 商談データ
CREATE TABLE IF NOT EXISTS {schema}.deals (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL DEFAULT {tenant_id},
    deal_code VARCHAR(20),
    -- Phase 1-B-2 Step 5d / PR γ: 旧 customer_id 列は migration 035 で DROP 済。
    --   新テナント作成時も customer_id 列を作らない（新 B2B モデル唯一の正）。
    -- CONSTRAINT 名は migration 032 と合わせる（verify の FK 存在 check が新旧テナントで揃うように）
    company_id INTEGER CONSTRAINT fk_deals_company REFERENCES {schema}.companies(id),
    contact_id INTEGER CONSTRAINT fk_deals_contact REFERENCES {schema}.contacts(id),
    lead_id INTEGER REFERENCES {schema}.leads(id),
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
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_deals_company_id ON {schema}.deals (company_id);
CREATE INDEX IF NOT EXISTS idx_deals_contact_id ON {schema}.deals (contact_id);

-- リード→案件への逆参照FK（leads作成時点ではdealsが未存在のため後から追加）
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_leads_converted_deal'
          AND connamespace = (SELECT oid FROM pg_namespace WHERE nspname = '{schema_raw}')
    ) THEN
        ALTER TABLE {schema}.leads
            ADD CONSTRAINT fk_leads_converted_deal
            FOREIGN KEY (converted_deal_id) REFERENCES {schema}.deals(id);
    END IF;
END $$;

-- customers.lead_id → leads.id（customers作成時点ではleadsが未存在のため後付け）
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_customers_lead'
          AND connamespace = (SELECT oid FROM pg_namespace WHERE nspname = '{schema_raw}')
    ) THEN
        ALTER TABLE {schema}.customers
            ADD CONSTRAINT fk_customers_lead
            FOREIGN KEY (lead_id) REFERENCES {schema}.leads(id);
    END IF;
END $$;

-- Phase 1-B-2: companies.lead_id / contacts.lead_id → leads.id
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_companies_lead'
          AND connamespace = (SELECT oid FROM pg_namespace WHERE nspname = '{schema_raw}')
    ) THEN
        ALTER TABLE {schema}.companies
            ADD CONSTRAINT fk_companies_lead
            FOREIGN KEY (lead_id) REFERENCES {schema}.leads(id);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_contacts_lead'
          AND connamespace = (SELECT oid FROM pg_namespace WHERE nspname = '{schema_raw}')
    ) THEN
        ALTER TABLE {schema}.contacts
            ADD CONSTRAINT fk_contacts_lead
            FOREIGN KEY (lead_id) REFERENCES {schema}.leads(id);
    END IF;
END $$;

-- 注文データ
CREATE TABLE IF NOT EXISTS {schema}.orders (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL DEFAULT {tenant_id},
    -- Phase 1-B-2 Step 5d / PR γ: 旧 customer_id 列は migration 035 で DROP 済。
    company_id INTEGER CONSTRAINT fk_orders_company REFERENCES {schema}.companies(id),
    contact_id INTEGER CONSTRAINT fk_orders_contact REFERENCES {schema}.contacts(id),
    deal_id INTEGER REFERENCES {schema}.deals(id),
    order_number VARCHAR(100) NOT NULL,
    total_amount NUMERIC(15, 2),
    status VARCHAR(50) DEFAULT 'pending',
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_orders_company_id ON {schema}.orders (company_id);
CREATE INDEX IF NOT EXISTS idx_orders_contact_id ON {schema}.orders (contact_id);

-- 操作履歴（監査ログ）
CREATE TABLE IF NOT EXISTS {schema}.audit_logs (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL DEFAULT {tenant_id},
    user_id INTEGER NOT NULL,
    action VARCHAR(50) NOT NULL,
    table_name VARCHAR(100) NOT NULL,
    record_id INTEGER,
    old_data JSONB,
    new_data JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ロール（Discord方式のカスタムロール）
CREATE TABLE IF NOT EXISTS {schema}.roles (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL DEFAULT {tenant_id},
    name VARCHAR(100) NOT NULL,
    color VARCHAR(7) DEFAULT '#6c757d',
    priority INTEGER NOT NULL DEFAULT 0,
    is_system BOOLEAN DEFAULT FALSE,
    description VARCHAR(500),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(tenant_id, name)
);

-- ロール×権限のリンク
CREATE TABLE IF NOT EXISTS {schema}.role_permissions (
    id SERIAL PRIMARY KEY,
    role_id INTEGER NOT NULL REFERENCES {schema}.roles(id) ON DELETE CASCADE,
    permission_id INTEGER NOT NULL REFERENCES public.permissions(id) ON DELETE CASCADE,
    UNIQUE(role_id, permission_id)
);

-- ユーザー×ロールのリンク（多対多）
CREATE TABLE IF NOT EXISTS {schema}.user_roles (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    role_id INTEGER NOT NULL REFERENCES {schema}.roles(id) ON DELETE CASCADE,
    assigned_at TIMESTAMPTZ DEFAULT NOW(),
    assigned_by INTEGER,
    UNIQUE(user_id, role_id)
);

-- チーム
CREATE TABLE IF NOT EXISTS {schema}.teams (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL DEFAULT {tenant_id},
    name VARCHAR(100) NOT NULL,
    leader_id INTEGER,
    description VARCHAR(500),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(tenant_id, name)
);

CREATE TABLE IF NOT EXISTS {schema}.team_members (
    id SERIAL PRIMARY KEY,
    team_id INTEGER NOT NULL REFERENCES {schema}.teams(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL,
    joined_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(team_id, user_id)
);

-- === Phase 1 再設計: updated_at 自動更新トリガ ===

CREATE OR REPLACE FUNCTION {schema}.trg_set_updated_at()
RETURNS TRIGGER AS $fn$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$fn$ LANGUAGE plpgsql;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_customers_updated_at' AND tgrelid = '{schema}.customers'::regclass) THEN
        CREATE TRIGGER trg_customers_updated_at BEFORE UPDATE ON {schema}.customers
            FOR EACH ROW EXECUTE FUNCTION {schema}.trg_set_updated_at();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_customer_addresses_updated_at' AND tgrelid = '{schema}.customer_addresses'::regclass) THEN
        CREATE TRIGGER trg_customer_addresses_updated_at BEFORE UPDATE ON {schema}.customer_addresses
            FOR EACH ROW EXECUTE FUNCTION {schema}.trg_set_updated_at();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_customer_discord_updated_at' AND tgrelid = '{schema}.customer_discord'::regclass) THEN
        CREATE TRIGGER trg_customer_discord_updated_at BEFORE UPDATE ON {schema}.customer_discord
            FOR EACH ROW EXECUTE FUNCTION {schema}.trg_set_updated_at();
    END IF;
    -- Phase 1-B-1: customer_contact_channels（PR #105 で tenant.py への反映が漏れていたため同時修正）
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_ccc_updated_at' AND tgrelid = '{schema}.customer_contact_channels'::regclass) THEN
        CREATE TRIGGER trg_ccc_updated_at BEFORE UPDATE ON {schema}.customer_contact_channels
            FOR EACH ROW EXECUTE FUNCTION {schema}.trg_set_updated_at();
    END IF;
    -- Phase 1-B-2: companies + contacts 階層（migration 028-030 と同じトリガ名で idempotent）
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_companies_updated_at' AND tgrelid = '{schema}.companies'::regclass) THEN
        CREATE TRIGGER trg_companies_updated_at BEFORE UPDATE ON {schema}.companies
            FOR EACH ROW EXECUTE FUNCTION {schema}.trg_set_updated_at();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_contacts_updated_at' AND tgrelid = '{schema}.contacts'::regclass) THEN
        CREATE TRIGGER trg_contacts_updated_at BEFORE UPDATE ON {schema}.contacts
            FOR EACH ROW EXECUTE FUNCTION {schema}.trg_set_updated_at();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_company_addresses_updated_at' AND tgrelid = '{schema}.company_addresses'::regclass) THEN
        CREATE TRIGGER trg_company_addresses_updated_at BEFORE UPDATE ON {schema}.company_addresses
            FOR EACH ROW EXECUTE FUNCTION {schema}.trg_set_updated_at();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_contact_discord_updated_at' AND tgrelid = '{schema}.contact_discord'::regclass) THEN
        CREATE TRIGGER trg_contact_discord_updated_at BEFORE UPDATE ON {schema}.contact_discord
            FOR EACH ROW EXECUTE FUNCTION {schema}.trg_set_updated_at();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_ccc_new_updated_at' AND tgrelid = '{schema}.contact_contact_channels'::regclass) THEN
        CREATE TRIGGER trg_ccc_new_updated_at BEFORE UPDATE ON {schema}.contact_contact_channels
            FOR EACH ROW EXECUTE FUNCTION {schema}.trg_set_updated_at();
    END IF;
    -- ADR-015 §7: lead_playbook の updated_at 自動更新
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_lead_playbook_updated_at' AND tgrelid = '{schema}.lead_playbook'::regclass) THEN
        CREATE TRIGGER trg_lead_playbook_updated_at BEFORE UPDATE ON {schema}.lead_playbook
            FOR EACH ROW EXECUTE FUNCTION {schema}.trg_set_updated_at();
    END IF;
END $$;

-- === Phase 1 再設計: スタッフ・bot ===

-- 人間スタッフ（public.users との1対1紐付け）
CREATE TABLE IF NOT EXISTS {schema}.staff (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL DEFAULT {tenant_id},
    user_id INTEGER UNIQUE REFERENCES public.users(id),
    staff_code VARCHAR(20) NOT NULL,
    surname_jp VARCHAR(50) NOT NULL,
    given_name_jp VARCHAR(50) NOT NULL,
    surname_kana VARCHAR(100),
    given_name_kana VARCHAR(100),
    surname_en VARCHAR(100),
    given_name_en VARCHAR(100),
    primary_email VARCHAR(255) NOT NULL,
    discord_user_id VARCHAR(50),
    role_id INTEGER NOT NULL REFERENCES {schema}.roles(id),
    status VARCHAR(20) NOT NULL DEFAULT 'active'
        CHECK (status IN ('active','inactive','pending')),
    firebase_uid VARCHAR(128) UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, staff_code),
    UNIQUE (tenant_id, discord_user_id)
);

CREATE INDEX IF NOT EXISTS idx_staff_tenant_id ON {schema}.staff (tenant_id);
CREATE INDEX IF NOT EXISTS idx_staff_role_id ON {schema}.staff (role_id);
CREATE INDEX IF NOT EXISTS idx_staff_primary_email ON {schema}.staff (primary_email);
CREATE INDEX IF NOT EXISTS idx_staff_user_id ON {schema}.staff (user_id);
CREATE INDEX IF NOT EXISTS idx_staff_status ON {schema}.staff (status);

-- スタッフの副メール（EMP-00005 のような1人複数メール対応）
CREATE TABLE IF NOT EXISTS {schema}.staff_emails (
    id SERIAL PRIMARY KEY,
    staff_id INTEGER NOT NULL REFERENCES {schema}.staff(id) ON DELETE CASCADE,
    email VARCHAR(255) NOT NULL,
    purpose VARCHAR(50),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (staff_id, email)
);

CREATE INDEX IF NOT EXISTS idx_staff_emails_staff_id ON {schema}.staff_emails (staff_id);

-- スタッフのUI設定
CREATE TABLE IF NOT EXISTS {schema}.staff_ui_preferences (
    staff_id INTEGER PRIMARY KEY REFERENCES {schema}.staff(id) ON DELETE CASCADE,
    dark_mode BOOLEAN NOT NULL DEFAULT FALSE,
    show_chat_menu BOOLEAN NOT NULL DEFAULT TRUE,
    show_sales_menu BOOLEAN NOT NULL DEFAULT TRUE,
    show_settings_menu BOOLEAN NOT NULL DEFAULT TRUE,
    show_admin_menu BOOLEAN NOT NULL DEFAULT FALSE,
    show_buddy_menu BOOLEAN NOT NULL DEFAULT TRUE,
    show_sidebar BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- customers.sales_rep_id → staff(id)（customers作成時点ではstaffが未存在のため後付け）
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_customers_sales_rep'
          AND connamespace = (SELECT oid FROM pg_namespace WHERE nspname = '{schema_raw}')
    ) THEN
        ALTER TABLE {schema}.customers
            ADD CONSTRAINT fk_customers_sales_rep
            FOREIGN KEY (sales_rep_id) REFERENCES {schema}.staff(id);
    END IF;
    -- Phase 1-B-2: companies.sales_rep_id → staff(id)
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_companies_sales_rep'
          AND connamespace = (SELECT oid FROM pg_namespace WHERE nspname = '{schema_raw}')
    ) THEN
        ALTER TABLE {schema}.companies
            ADD CONSTRAINT fk_companies_sales_rep
            FOREIGN KEY (sales_rep_id) REFERENCES {schema}.staff(id);
    END IF;
END $$;

-- 自動化bot（請求書送付bot / 発送通知bot 等）
CREATE TABLE IF NOT EXISTS {schema}.bots (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL DEFAULT {tenant_id},
    bot_code VARCHAR(20) NOT NULL,
    display_name VARCHAR(100) NOT NULL,
    purpose VARCHAR(50) NOT NULL
        CHECK (purpose IN ('invoice','shipment','notification','custom')),
    status VARCHAR(20) NOT NULL DEFAULT 'active'
        CHECK (status IN ('active','inactive','maintenance')),
    api_key_hash VARCHAR(128) NOT NULL,
    discord_user_id VARCHAR(50),
    sender_email VARCHAR(255),
    owner_staff_id INTEGER NOT NULL REFERENCES {schema}.staff(id),
    last_executed_at TIMESTAMPTZ,
    execution_count BIGINT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, bot_code),
    UNIQUE (tenant_id, discord_user_id)
);

CREATE INDEX IF NOT EXISTS idx_bots_tenant_id ON {schema}.bots (tenant_id);
CREATE INDEX IF NOT EXISTS idx_bots_owner_staff_id ON {schema}.bots (owner_staff_id);
CREATE INDEX IF NOT EXISTS idx_bots_purpose ON {schema}.bots (purpose);

-- staff / staff_ui_preferences / bots の updated_at 自動更新トリガ
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_staff_updated_at' AND tgrelid = '{schema}.staff'::regclass) THEN
        CREATE TRIGGER trg_staff_updated_at BEFORE UPDATE ON {schema}.staff
            FOR EACH ROW EXECUTE FUNCTION {schema}.trg_set_updated_at();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_staff_ui_preferences_updated_at' AND tgrelid = '{schema}.staff_ui_preferences'::regclass) THEN
        CREATE TRIGGER trg_staff_ui_preferences_updated_at BEFORE UPDATE ON {schema}.staff_ui_preferences
            FOR EACH ROW EXECUTE FUNCTION {schema}.trg_set_updated_at();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_bots_updated_at' AND tgrelid = '{schema}.bots'::regclass) THEN
        CREATE TRIGGER trg_bots_updated_at BEFORE UPDATE ON {schema}.bots
            FOR EACH ROW EXECUTE FUNCTION {schema}.trg_set_updated_at();
    END IF;
END $$;

-- 送信元統一ビュー（staff と bots を UNION）
CREATE OR REPLACE VIEW {schema}.v_senders AS
SELECT
    id, tenant_id, 'staff'::VARCHAR(10) AS sender_type,
    CONCAT(surname_jp, ' ', given_name_jp) AS display_name,
    primary_email AS contact_email
FROM {schema}.staff
UNION ALL
SELECT
    id, tenant_id, 'bot'::VARCHAR(10) AS sender_type,
    display_name, sender_email AS contact_email
FROM {schema}.bots;

-- === Phase 2: 販売・財務プロセス ===

-- 商品マスタ
-- 2026-04-28 (Phase 1-C M-MVP / migration 038): TCG 輸出向け 11 列追加
CREATE TABLE IF NOT EXISTS {schema}.products (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL DEFAULT {tenant_id},
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
    -- Phase 1-C M-MVP（2026-04-28、migration 038 同等）
    jan_code VARCHAR(20),
    card_number VARCHAR(50),
    expansion_code VARCHAR(20),
    rarity VARCHAR(20),
    language VARCHAR(10),
    unit_price_usd NUMERIC(15, 2),
    unit_price_eur NUMERIC(15, 2),
    image_url VARCHAR(500),
    is_archived BOOLEAN DEFAULT FALSE,
    archived_at TIMESTAMPTZ,
    supplier_default_id INTEGER,  -- FK は新テナント作成順序の都合で後付け
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- products 索引（migration 038 同等）
CREATE UNIQUE INDEX IF NOT EXISTS uq_products_tenant_code ON {schema}.products (tenant_id, product_code) WHERE product_code IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_products_tenant_jan ON {schema}.products (tenant_id, jan_code) WHERE jan_code IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_products_archived ON {schema}.products (is_archived);
CREATE INDEX IF NOT EXISTS idx_products_card_number ON {schema}.products (card_number) WHERE card_number IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_products_expansion ON {schema}.products (expansion_code) WHERE expansion_code IS NOT NULL;

-- 配送ゾーン
CREATE TABLE IF NOT EXISTS {schema}.shipping_zones (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL DEFAULT {tenant_id},
    country_code VARCHAR(3) NOT NULL,
    country_name VARCHAR(100) NOT NULL,
    carrier VARCHAR(50) NOT NULL,
    zone VARCHAR(20) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(tenant_id, country_code, carrier)
);

-- 配送料金
CREATE TABLE IF NOT EXISTS {schema}.shipping_rates (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL DEFAULT {tenant_id},
    carrier VARCHAR(50) NOT NULL,
    zone VARCHAR(20) NOT NULL,
    weight_min NUMERIC(10, 3) NOT NULL,
    weight_max NUMERIC(10, 3) NOT NULL,
    price NUMERIC(15, 2) NOT NULL,
    currency VARCHAR(10) DEFAULT 'JPY',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 見積ヘッダー
CREATE TABLE IF NOT EXISTS {schema}.quotes (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL DEFAULT {tenant_id},
    quote_code VARCHAR(20),
    deal_id INTEGER REFERENCES {schema}.deals(id),
    -- Phase 1-B-2 Step 5d / PR γ: 旧 customer_id 列は migration 035 で DROP 済。
    company_id INTEGER CONSTRAINT fk_quotes_company REFERENCES {schema}.companies(id),
    contact_id INTEGER CONSTRAINT fk_quotes_contact REFERENCES {schema}.contacts(id),
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
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_quotes_company_id ON {schema}.quotes (company_id);
CREATE INDEX IF NOT EXISTS idx_quotes_contact_id ON {schema}.quotes (contact_id);

-- 見積明細
CREATE TABLE IF NOT EXISTS {schema}.quote_items (
    id SERIAL PRIMARY KEY,
    quote_id INTEGER NOT NULL REFERENCES {schema}.quotes(id) ON DELETE CASCADE,
    product_id INTEGER REFERENCES {schema}.products(id),
    product_name VARCHAR(255) NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 1,
    unit_price NUMERIC(15, 2) NOT NULL,
    weight NUMERIC(10, 3),
    subtotal NUMERIC(15, 2) NOT NULL,
    sort_order INTEGER DEFAULT 0
);

-- 請求書ヘッダー
CREATE TABLE IF NOT EXISTS {schema}.invoices (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL DEFAULT {tenant_id},
    invoice_number VARCHAR(30),
    quote_id INTEGER REFERENCES {schema}.quotes(id),
    -- Phase 1-B-2 Step 5d / PR γ: 旧 customer_id 列は migration 035 で DROP 済。
    company_id INTEGER CONSTRAINT fk_invoices_company REFERENCES {schema}.companies(id),
    contact_id INTEGER CONSTRAINT fk_invoices_contact REFERENCES {schema}.contacts(id),
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
    issued_at TIMESTAMPTZ,
    due_date DATE,
    paid_at TIMESTAMPTZ,
    voided_at TIMESTAMPTZ,
    void_reason VARCHAR(500),
    notes TEXT,
    created_by INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_invoices_company_id ON {schema}.invoices (company_id);
CREATE INDEX IF NOT EXISTS idx_invoices_contact_id ON {schema}.invoices (contact_id);

-- 請求書明細
CREATE TABLE IF NOT EXISTS {schema}.invoice_items (
    id SERIAL PRIMARY KEY,
    invoice_id INTEGER NOT NULL REFERENCES {schema}.invoices(id) ON DELETE CASCADE,
    product_id INTEGER REFERENCES {schema}.products(id),
    product_name VARCHAR(255) NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 1,
    unit_price NUMERIC(15, 2) NOT NULL,
    weight NUMERIC(10, 3),
    subtotal NUMERIC(15, 2) NOT NULL,
    sort_order INTEGER DEFAULT 0
);

-- === Phase 3: 仕入れ・調達管理 ===

CREATE TABLE IF NOT EXISTS {schema}.suppliers (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL DEFAULT {tenant_id},
    supplier_code VARCHAR(20),
    name VARCHAR(255) NOT NULL,
    contact_name VARCHAR(255),
    email VARCHAR(255),
    phone VARCHAR(50),
    address TEXT,
    notes TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- products.supplier_default_id の FK を suppliers 作成後に付与
-- （Phase 1-C M-MVP / 2026-04-28）
DO $supplier_fk$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = '{schema}.products'::regclass
          AND conname = 'fk_products_supplier_default'
    ) THEN
        ALTER TABLE {schema}.products
        ADD CONSTRAINT fk_products_supplier_default
        FOREIGN KEY (supplier_default_id) REFERENCES {schema}.suppliers(id);
    END IF;
END $supplier_fk$;

CREATE TABLE IF NOT EXISTS {schema}.purchase_orders (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL DEFAULT {tenant_id},
    po_number VARCHAR(20),
    supplier_id INTEGER NOT NULL REFERENCES {schema}.suppliers(id),
    status VARCHAR(20) DEFAULT 'draft',
    total_amount NUMERIC(15, 2) DEFAULT 0,
    ordered_at TIMESTAMPTZ,
    received_at TIMESTAMPTZ,
    notes TEXT,
    created_by INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS {schema}.purchase_order_items (
    id SERIAL PRIMARY KEY,
    purchase_order_id INTEGER NOT NULL REFERENCES {schema}.purchase_orders(id) ON DELETE CASCADE,
    product_id INTEGER NOT NULL REFERENCES {schema}.products(id),
    quantity INTEGER NOT NULL DEFAULT 1,
    unit_cost NUMERIC(15, 2) NOT NULL,
    subtotal NUMERIC(15, 2) NOT NULL,
    sort_order INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS {schema}.meta_messages (
    id          SERIAL PRIMARY KEY,
    tenant_id   INTEGER NOT NULL DEFAULT {tenant_id},
    lead_id     INTEGER REFERENCES {schema}.leads(id) ON DELETE SET NULL,
    platform    VARCHAR(20) NOT NULL DEFAULT 'messenger',
    sender_id   VARCHAR(100) NOT NULL,
    sender_name VARCHAR(200),
    -- ADR-026 / migration 052: Instagram の mid は 157 文字に達するため TEXT を使う。
    -- 既存テナントは migration 052 で TEXT 化済 → 新規テナント provisioning も整合させる。
    message_id  TEXT,
    message_text TEXT,
    direction   VARCHAR(10) NOT NULL DEFAULT 'inbound',
    raw_payload JSONB,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_meta_messages_sender ON {schema}.meta_messages (sender_id);
CREATE INDEX IF NOT EXISTS idx_meta_messages_lead   ON {schema}.meta_messages (lead_id);
CREATE INDEX IF NOT EXISTS idx_meta_messages_ts     ON {schema}.meta_messages (created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_meta_messages_message_id_unique
    ON {schema}.meta_messages (message_id)
    WHERE message_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_leads_meta_source_unique
    ON {schema}.leads (source)
    WHERE source LIKE 'messenger:%' OR source LIKE 'instagram:%';

-- Phase 1-D Sprint 1 / migration 040: Meta OAuth 接続情報（Page / IG Business Account）
-- 同じ DDL は migrations/040_create_tenant_meta_config.sql にも置いてあり、
-- 既存テナントへの後付けはそちらの SQL を使う。新規テナントはこの本ブロックで自動作成される。
CREATE TABLE IF NOT EXISTS {schema}.tenant_meta_config (
    id                              SERIAL PRIMARY KEY,
    tenant_id                       INTEGER NOT NULL DEFAULT {tenant_id},
    page_id                         VARCHAR(50) NOT NULL,
    page_name                       VARCHAR(200) NOT NULL,
    page_access_token_encrypted     BYTEA NOT NULL,
    page_token_expires_at           TIMESTAMPTZ,
    instagram_business_account_id   VARCHAR(50),
    instagram_username              VARCHAR(100),
    subscribed_fields               JSONB,
    connected_by_staff_id           INTEGER REFERENCES {schema}.staff(id),
    connected_at                    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_token_refreshed_at         TIMESTAMPTZ,
    is_active                       BOOLEAN NOT NULL DEFAULT TRUE,
    deactivated_at                  TIMESTAMPTZ,
    notes                           TEXT,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_tenant_meta_config_active_page
    ON {schema}.tenant_meta_config (tenant_id, page_id)
    WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_tenant_meta_config_ig_id
    ON {schema}.tenant_meta_config (instagram_business_account_id)
    WHERE instagram_business_account_id IS NOT NULL;

-- Sprint 8 / migration 069: テナント発行者情報 (PO PDF / メール差出人)
-- ADR-034: 新規テナント作成時に最初から保持される。
-- 1 テナント 1 行運用、admin UI で内容編集。
CREATE TABLE IF NOT EXISTS {schema}.tenant_profile (
    id                  SERIAL PRIMARY KEY,
    company_name        VARCHAR(255),
    company_name_en     VARCHAR(255),
    address             TEXT,
    phone               VARCHAR(50),
    email               VARCHAR(255),
    website             VARCHAR(255),
    seal_image_url      TEXT,
    default_language    CHAR(2) NOT NULL DEFAULT 'ja',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT tenant_profile_default_language_check
        CHECK (default_language IN ('ja', 'en', 'ko', 'zh'))
);
-- 既定行を 1 行投入 (admin が UI で後から埋める)
INSERT INTO {schema}.tenant_profile (default_language)
SELECT 'ja' WHERE NOT EXISTS (SELECT 1 FROM {schema}.tenant_profile);
"""

# RLS有効化のALTER TABLE群（;で安全に分割可能）
# 連携テーブル（role_permissions, user_roles, team_members）は tenant_id カラムを持たないが、
# 親テーブルのRLSを経由した保護を追加することで防御の二重化を実現する。
_RLS_ENABLE_SQL = """
ALTER TABLE {schema}.customers ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.deals ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.audit_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.leads ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.roles ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.role_permissions ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.user_roles ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.teams ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.team_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.products ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.shipping_zones ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.shipping_rates ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.quotes ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.quote_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.invoices ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.invoice_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.suppliers ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.purchase_orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.purchase_order_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.team_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.meta_messages ENABLE ROW LEVEL SECURITY;
-- Phase 1-D Sprint 1: Meta OAuth 接続情報
ALTER TABLE {schema}.tenant_meta_config ENABLE ROW LEVEL SECURITY;
-- Phase 1 再設計の新テーブル
ALTER TABLE {schema}.customer_addresses ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.customer_sales_channels ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.customer_discord ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.customer_contact_channels ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.staff ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.staff_emails ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.staff_ui_preferences ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.bots ENABLE ROW LEVEL SECURITY;
-- Phase 1-B-2: companies + contacts 階層
ALTER TABLE {schema}.companies ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.contacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.company_addresses ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.company_sales_channels ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.contact_emails ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.contact_discord ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.contact_contact_channels ENABLE ROW LEVEL SECURITY;
-- ADR-015 §7: テナント別 AI 対応プレイブック
ALTER TABLE {schema}.lead_playbook ENABLE ROW LEVEL SECURITY;
-- Phase 1-B-2 Step 5d / PR γ: _customer_migration_map は migration 036 で DROP 済。
"""

# テナント分離ポリシー（DO $$ ... END $$ ブロックは1ステートメントとして実行する。
# 内部の;でsplitすると$$ドル引用が分断されPostgresSyntaxErrorになるため）
_RLS_POLICY_SQL = """
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_customers' AND schemaname = '{schema_raw}') THEN
        CREATE POLICY tenant_isolation_customers ON {schema}.customers
            USING (tenant_id = current_setting('app.tenant_id', true)::INTEGER);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_deals' AND schemaname = '{schema_raw}') THEN
        CREATE POLICY tenant_isolation_deals ON {schema}.deals
            USING (tenant_id = current_setting('app.tenant_id', true)::INTEGER);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_orders' AND schemaname = '{schema_raw}') THEN
        CREATE POLICY tenant_isolation_orders ON {schema}.orders
            USING (tenant_id = current_setting('app.tenant_id', true)::INTEGER);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_audit_logs' AND schemaname = '{schema_raw}') THEN
        CREATE POLICY tenant_isolation_audit_logs ON {schema}.audit_logs
            USING (tenant_id = current_setting('app.tenant_id', true)::INTEGER);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_leads' AND schemaname = '{schema_raw}') THEN
        CREATE POLICY tenant_isolation_leads ON {schema}.leads
            USING (tenant_id = current_setting('app.tenant_id', true)::INTEGER);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_roles' AND schemaname = '{schema_raw}') THEN
        CREATE POLICY tenant_isolation_roles ON {schema}.roles
            USING (tenant_id = current_setting('app.tenant_id', true)::INTEGER);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_teams' AND schemaname = '{schema_raw}') THEN
        CREATE POLICY tenant_isolation_teams ON {schema}.teams
            USING (tenant_id = current_setting('app.tenant_id', true)::INTEGER);
    END IF;
    -- 連携テーブルは tenant_id カラムを持たないため、親テーブルのRLSをEXISTS経由で参照
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_role_permissions' AND schemaname = '{schema_raw}') THEN
        CREATE POLICY tenant_isolation_role_permissions ON {schema}.role_permissions
            USING (EXISTS (
                SELECT 1 FROM {schema}.roles r
                WHERE r.id = role_permissions.role_id
                  AND r.tenant_id = current_setting('app.tenant_id', true)::INTEGER
            ));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_user_roles' AND schemaname = '{schema_raw}') THEN
        CREATE POLICY tenant_isolation_user_roles ON {schema}.user_roles
            USING (EXISTS (
                SELECT 1 FROM {schema}.roles r
                WHERE r.id = user_roles.role_id
                  AND r.tenant_id = current_setting('app.tenant_id', true)::INTEGER
            ));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_team_members' AND schemaname = '{schema_raw}') THEN
        CREATE POLICY tenant_isolation_team_members ON {schema}.team_members
            USING (EXISTS (
                SELECT 1 FROM {schema}.teams t
                WHERE t.id = team_members.team_id
                  AND t.tenant_id = current_setting('app.tenant_id', true)::INTEGER
            ));
    END IF;
    -- Phase 2: 販売・財務プロセスのテーブル
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_products' AND schemaname = '{schema_raw}') THEN
        CREATE POLICY tenant_isolation_products ON {schema}.products
            USING (tenant_id = current_setting('app.tenant_id', true)::INTEGER);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_shipping_zones' AND schemaname = '{schema_raw}') THEN
        CREATE POLICY tenant_isolation_shipping_zones ON {schema}.shipping_zones
            USING (tenant_id = current_setting('app.tenant_id', true)::INTEGER);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_shipping_rates' AND schemaname = '{schema_raw}') THEN
        CREATE POLICY tenant_isolation_shipping_rates ON {schema}.shipping_rates
            USING (tenant_id = current_setting('app.tenant_id', true)::INTEGER);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_quotes' AND schemaname = '{schema_raw}') THEN
        CREATE POLICY tenant_isolation_quotes ON {schema}.quotes
            USING (tenant_id = current_setting('app.tenant_id', true)::INTEGER);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_invoices' AND schemaname = '{schema_raw}') THEN
        CREATE POLICY tenant_isolation_invoices ON {schema}.invoices
            USING (tenant_id = current_setting('app.tenant_id', true)::INTEGER);
    END IF;
    -- 明細テーブル（tenant_id なし → 親テーブル経由）
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_quote_items' AND schemaname = '{schema_raw}') THEN
        CREATE POLICY tenant_isolation_quote_items ON {schema}.quote_items
            USING (EXISTS (
                SELECT 1 FROM {schema}.quotes q
                WHERE q.id = quote_items.quote_id
                  AND q.tenant_id = current_setting('app.tenant_id', true)::INTEGER
            ));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_invoice_items' AND schemaname = '{schema_raw}') THEN
        CREATE POLICY tenant_isolation_invoice_items ON {schema}.invoice_items
            USING (EXISTS (
                SELECT 1 FROM {schema}.invoices inv
                WHERE inv.id = invoice_items.invoice_id
                  AND inv.tenant_id = current_setting('app.tenant_id', true)::INTEGER
            ));
    END IF;
    -- Phase 3: 仕入れ・調達管理
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_suppliers' AND schemaname = '{schema_raw}') THEN
        CREATE POLICY tenant_isolation_suppliers ON {schema}.suppliers
            USING (tenant_id = current_setting('app.tenant_id', true)::INTEGER);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_purchase_orders' AND schemaname = '{schema_raw}') THEN
        CREATE POLICY tenant_isolation_purchase_orders ON {schema}.purchase_orders
            USING (tenant_id = current_setting('app.tenant_id', true)::INTEGER);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_po_items' AND schemaname = '{schema_raw}') THEN
        CREATE POLICY tenant_isolation_po_items ON {schema}.purchase_order_items
            USING (EXISTS (
                SELECT 1 FROM {schema}.purchase_orders po
                WHERE po.id = purchase_order_items.purchase_order_id
                  AND po.tenant_id = current_setting('app.tenant_id', true)::INTEGER
            ));
    END IF;
    -- Meta Messaging
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_meta_messages' AND schemaname = '{schema_raw}') THEN
        CREATE POLICY tenant_isolation_meta_messages ON {schema}.meta_messages
            USING (tenant_id = current_setting('app.tenant_id', true)::INTEGER);
    END IF;
    -- Phase 1-D Sprint 1: tenant_meta_config（Page / IG OAuth 接続情報）
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_tenant_meta_config' AND schemaname = '{schema_raw}') THEN
        CREATE POLICY tenant_isolation_tenant_meta_config ON {schema}.tenant_meta_config
            USING (tenant_id = current_setting('app.tenant_id', true)::INTEGER);
    END IF;
    -- Phase 1 再設計: customer 副テーブル群
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_customer_addresses' AND schemaname = '{schema_raw}') THEN
        CREATE POLICY tenant_isolation_customer_addresses ON {schema}.customer_addresses
            USING (EXISTS (
                SELECT 1 FROM {schema}.customers c
                WHERE c.id = customer_addresses.customer_id
                  AND c.tenant_id = current_setting('app.tenant_id', true)::INTEGER
            ));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_customer_sales_channels' AND schemaname = '{schema_raw}') THEN
        CREATE POLICY tenant_isolation_customer_sales_channels ON {schema}.customer_sales_channels
            USING (EXISTS (
                SELECT 1 FROM {schema}.customers c
                WHERE c.id = customer_sales_channels.customer_id
                  AND c.tenant_id = current_setting('app.tenant_id', true)::INTEGER
            ));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_customer_discord' AND schemaname = '{schema_raw}') THEN
        CREATE POLICY tenant_isolation_customer_discord ON {schema}.customer_discord
            USING (EXISTS (
                SELECT 1 FROM {schema}.customers c
                WHERE c.id = customer_discord.customer_id
                  AND c.tenant_id = current_setting('app.tenant_id', true)::INTEGER
            ));
    END IF;
    -- Phase 1 再設計: staff / bots
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_staff' AND schemaname = '{schema_raw}') THEN
        CREATE POLICY tenant_isolation_staff ON {schema}.staff
            USING (tenant_id = current_setting('app.tenant_id', true)::INTEGER);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_bots' AND schemaname = '{schema_raw}') THEN
        CREATE POLICY tenant_isolation_bots ON {schema}.bots
            USING (tenant_id = current_setting('app.tenant_id', true)::INTEGER);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_staff_emails' AND schemaname = '{schema_raw}') THEN
        CREATE POLICY tenant_isolation_staff_emails ON {schema}.staff_emails
            USING (EXISTS (
                SELECT 1 FROM {schema}.staff s
                WHERE s.id = staff_emails.staff_id
                  AND s.tenant_id = current_setting('app.tenant_id', true)::INTEGER
            ));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_staff_ui_preferences' AND schemaname = '{schema_raw}') THEN
        CREATE POLICY tenant_isolation_staff_ui_preferences ON {schema}.staff_ui_preferences
            USING (EXISTS (
                SELECT 1 FROM {schema}.staff s
                WHERE s.id = staff_ui_preferences.staff_id
                  AND s.tenant_id = current_setting('app.tenant_id', true)::INTEGER
            ));
    END IF;
    -- Phase 1-B-1: customer_contact_channels（customer_id 経由で分離）
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_customer_contact_channels' AND schemaname = '{schema_raw}') THEN
        CREATE POLICY tenant_isolation_customer_contact_channels ON {schema}.customer_contact_channels
            USING (EXISTS (
                SELECT 1 FROM {schema}.customers c
                WHERE c.id = customer_contact_channels.customer_id
                  AND c.tenant_id = current_setting('app.tenant_id', true)::INTEGER
            ));
    END IF;
    -- Phase 1-B-2: companies + contacts 階層
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_companies' AND schemaname = '{schema_raw}') THEN
        CREATE POLICY tenant_isolation_companies ON {schema}.companies
            USING (tenant_id = current_setting('app.tenant_id', true)::INTEGER);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_contacts' AND schemaname = '{schema_raw}') THEN
        CREATE POLICY tenant_isolation_contacts ON {schema}.contacts
            USING (tenant_id = current_setting('app.tenant_id', true)::INTEGER);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_company_addresses' AND schemaname = '{schema_raw}') THEN
        CREATE POLICY tenant_isolation_company_addresses ON {schema}.company_addresses
            USING (EXISTS (
                SELECT 1 FROM {schema}.companies c
                WHERE c.id = company_addresses.company_id
                  AND c.tenant_id = current_setting('app.tenant_id', true)::INTEGER
            ));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_company_sales_channels' AND schemaname = '{schema_raw}') THEN
        CREATE POLICY tenant_isolation_company_sales_channels ON {schema}.company_sales_channels
            USING (EXISTS (
                SELECT 1 FROM {schema}.companies c
                WHERE c.id = company_sales_channels.company_id
                  AND c.tenant_id = current_setting('app.tenant_id', true)::INTEGER
            ));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_contact_emails' AND schemaname = '{schema_raw}') THEN
        CREATE POLICY tenant_isolation_contact_emails ON {schema}.contact_emails
            USING (EXISTS (
                SELECT 1 FROM {schema}.contacts ct
                WHERE ct.id = contact_emails.contact_id
                  AND ct.tenant_id = current_setting('app.tenant_id', true)::INTEGER
            ));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_contact_discord' AND schemaname = '{schema_raw}') THEN
        CREATE POLICY tenant_isolation_contact_discord ON {schema}.contact_discord
            USING (EXISTS (
                SELECT 1 FROM {schema}.contacts ct
                WHERE ct.id = contact_discord.contact_id
                  AND ct.tenant_id = current_setting('app.tenant_id', true)::INTEGER
            ));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_contact_contact_channels' AND schemaname = '{schema_raw}') THEN
        CREATE POLICY tenant_isolation_contact_contact_channels ON {schema}.contact_contact_channels
            USING (EXISTS (
                SELECT 1 FROM {schema}.contacts ct
                WHERE ct.id = contact_contact_channels.contact_id
                  AND ct.tenant_id = current_setting('app.tenant_id', true)::INTEGER
            ));
    END IF;
    -- Phase 1-B-2 Step 5d / PR γ: tenant_isolation_customer_migration_map policy は
    -- migration 036 で _customer_migration_map テーブルごと削除されるため撤去済。
    -- ADR-015 §7: テナント別 AI 対応プレイブック
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_lead_playbook' AND schemaname = '{schema_raw}') THEN
        CREATE POLICY tenant_isolation_lead_playbook ON {schema}.lead_playbook
            USING (tenant_id = current_setting('app.tenant_id', true)::INTEGER);
    END IF;
END $$
"""


# Phase 1-E F16-FU2 (2026-05-03): 新規テナント作成時に migration 044 と同等のトリガを
# 自動セットアップする。既存テナントへの適用は `scripts/migrate_meta_page_routing.py`
# 側が担当し、本関数は **新規テナント onboard 経路** からの呼び出しでのみ動く。
#
# migration 044 とのコード重複だが、ファイル読み込みベースより inline 定数の方が
# 既存パターン（_TENANT_TABLES_SQL / _RLS_*_SQL）と一貫性がある。
# F16-FU1 の `SET search_path = pg_catalog, public` も含めた版を保持する。
_META_PAGE_ROUTING_TRIGGER_SQL = """
CREATE OR REPLACE FUNCTION {schema}.sync_meta_page_routing()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $sync_mpr$
BEGIN
    IF (TG_OP = 'DELETE') THEN
        DELETE FROM public.meta_page_routing
        WHERE tenant_id = OLD.tenant_id
          AND config_id = OLD.id;
        RETURN OLD;
    END IF;

    INSERT INTO public.meta_page_routing (
        tenant_id, config_id, schema_name,
        page_id, instagram_business_account_id, is_active, updated_at
    )
    VALUES (
        NEW.tenant_id,
        NEW.id,
        '{schema_raw}',
        NEW.page_id,
        NEW.instagram_business_account_id,
        NEW.is_active,
        NOW()
    )
    ON CONFLICT (tenant_id, config_id) DO UPDATE SET
        schema_name                     = EXCLUDED.schema_name,
        page_id                         = EXCLUDED.page_id,
        instagram_business_account_id   = EXCLUDED.instagram_business_account_id,
        is_active                       = EXCLUDED.is_active,
        updated_at                      = NOW();

    RETURN NEW;
END;
$sync_mpr$;

DROP TRIGGER IF EXISTS trg_sync_meta_page_routing ON {schema}.tenant_meta_config;
CREATE TRIGGER trg_sync_meta_page_routing
    AFTER INSERT OR UPDATE OR DELETE ON {schema}.tenant_meta_config
    FOR EACH ROW EXECUTE FUNCTION {schema}.sync_meta_page_routing();
"""


async def _assign_permissions_to_role(
    db: AsyncSession,
    schema_name: str,
    role_id: int,
    permissions_spec,
) -> None:
    """ロールに対して指定された権限を適用する（既存割当は全クリア後に再投入）。"""
    await db.execute(
        text(f"DELETE FROM {schema_name}.role_permissions WHERE role_id = :rid"),
        {"rid": role_id},
    )

    if permissions_spec == "ALL":
        await db.execute(
            text(f"""
                INSERT INTO {schema_name}.role_permissions (role_id, permission_id)
                SELECT :rid, id FROM public.permissions
            """),
            {"rid": role_id},
        )
    elif permissions_spec == "ALL_EXCEPT_SYSTEM_MANAGE":
        await db.execute(
            text(f"""
                INSERT INTO {schema_name}.role_permissions (role_id, permission_id)
                SELECT :rid, id FROM public.permissions WHERE key != 'system.manage'
            """),
            {"rid": role_id},
        )
    elif isinstance(permissions_spec, list):
        for key in permissions_spec:
            await db.execute(
                text(f"""
                    INSERT INTO {schema_name}.role_permissions (role_id, permission_id)
                    SELECT :rid, id FROM public.permissions WHERE key = :key
                    ON CONFLICT DO NOTHING
                """),
                {"rid": role_id, "key": key},
            )


async def seed_system_roles(db: AsyncSession, tenant_id: int, schema_name: str) -> None:
    """
    GAS版互換の既定ロールをシードする（冪等）。

    - オーナー (system): 全権限、削除/編集不可
    - システム管理者: system.manage 以外の全権限、編集可
    - リーダー: チーム単位のリード/案件管理、編集可
    - 営業: 顧客〜案件〜注文の販売サイクル、編集可
    - CS: 顧客フォローアップ、編集可

    非システムロールは「名前が既存でない場合のみ」権限を初期設定する。
    既に存在する場合は権限のカスタマイズを上書きしない（priority/descriptionのみ更新）。
    """
    for role_def in DEFAULT_ROLES:
        # 既存チェック（編集済みロールの権限を上書きしないため）
        existing = await db.execute(
            text(f"SELECT id FROM {schema_name}.roles WHERE tenant_id = :tid AND name = :name"),
            {"tid": tenant_id, "name": role_def["name"]},
        )
        existing_row = existing.first()
        is_new = existing_row is None

        # upsert（名前で識別、color/priority/description は常に最新化）
        # color も更新対象とすることで、パレット変更時に既定ロールの色を一括同期できる。
        # カスタムロール（名前が DEFAULT_ROLES にないもの）はこのループの対象外なので
        # ユーザーのカスタマイズは保持される。
        result = await db.execute(
            text(f"""
                INSERT INTO {schema_name}.roles (tenant_id, name, color, priority, is_system, description)
                VALUES (:tid, :name, :color, :priority, :is_system, :description)
                ON CONFLICT (tenant_id, name) DO UPDATE
                SET color = EXCLUDED.color,
                    priority = EXCLUDED.priority,
                    description = EXCLUDED.description
                RETURNING id
            """),
            {
                "tid": tenant_id,
                "name": role_def["name"],
                "color": role_def["color"],
                "priority": role_def["priority"],
                "is_system": role_def["is_system"],
                "description": role_def["description"],
            },
        )
        role_id = result.scalar_one()

        # 権限割当: システムロールは常に同期（オーナーは必ず全権限）
        # 非システムロールは「新規作成時のみ」デフォルト権限を入れる
        # （既存の場合はテナント管理者によるカスタマイズを保持）
        if role_def["is_system"] or is_new:
            await _assign_permissions_to_role(db, schema_name, role_id, role_def["permissions"])


async def create_tenant_schema(db: AsyncSession, tenant_id: int) -> str:
    """
    テナント専用スキーマを作成し、業務テーブルとRLSポリシー、
    システムロールを設定する。

    Args:
        db: データベースセッション
        tenant_id: テナントID（public.tenants.id）

    Returns:
        作成したスキーマ名（例: "tenant_001"）
    """
    # スキーマ名はtenant_{数値ID}形式（int()で型を強制しSQLインジェクション防止）
    # セキュリティ不変条件: schema_nameは必ず ^tenant_\d{3,}$ にマッチすること
    safe_id = int(tenant_id)
    schema_name = f"tenant_{safe_id:03d}"
    if not re.match(r"^tenant_\d{3,}$", schema_name):
        raise ValueError(f"不正なスキーマ名: {schema_name}")

    # 1. スキーマ作成
    await db.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema_name}"))

    # 2. 業務テーブル作成（DO $$ ブロックがあるため単純split不可、区切り工夫）
    tables_sql = _TENANT_TABLES_SQL.format(
        schema=schema_name,
        schema_raw=schema_name,
        tenant_id=safe_id,
    )
    # DO $$ ... END $$ ブロックを保ったまま分割するため、セミコロンでのsplitを避けて
    # ブロック単位で分割する（PostgreSQLは単一execute内で複数文を許容しないため
    # ステートメントを分ける必要がある）。
    await _execute_statements_preserving_do_blocks(db, tables_sql)

    # 3a. RLS有効化（ALTER TABLE群、;で分割可能）
    enable_sql = _RLS_ENABLE_SQL.format(schema=schema_name)
    for statement in enable_sql.strip().split(";"):
        statement = statement.strip()
        if statement:
            await db.execute(text(statement))

    # 3b. RLSポリシー（DOブロック、splitせず1ステートメントで実行）
    policy_sql = _RLS_POLICY_SQL.format(schema=schema_name, schema_raw=schema_name)
    await db.execute(text(policy_sql))

    # 4. システムロール（オーナー/メンバー）をシード
    await seed_system_roles(db, safe_id, schema_name)

    # 5. F16-FU2: meta_page_routing 同期トリガをセットアップ
    # 既存テナントへの適用は scripts/migrate_meta_page_routing.py が担当する。
    # 新規テナントは public.meta_page_routing 表 (migration 043) が既に存在する前提。
    trigger_sql = _META_PAGE_ROUTING_TRIGGER_SQL.format(
        schema=schema_name,
        schema_raw=schema_name,
    )
    await _execute_statements_preserving_do_blocks(db, trigger_sql)

    # 6. Sprint 9 / F9 v1.2: public.tenant_settings に Phase='A' で初期行を seed。
    #    migration 070 未適用環境では tenant_settings テーブルが存在しないので
    #    best-effort で実行する。phase_gate.get_phase は 'A' fallback してくれる。
    try:
        await db.execute(
            text(
                "INSERT INTO public.tenant_settings (tenant_id, spreadsheet_phase) "
                "VALUES (:tid, 'A') "
                "ON CONFLICT (tenant_id) DO NOTHING"
            ),
            {"tid": safe_id},
        )
    except Exception:
        # migration 070 未適用環境では skip
        pass

    # commitは呼び出し元で行う（監査ログ等と一括でcommitするため）
    return schema_name


def get_tenant_tables_sql(schema_name: str, tenant_id: int) -> str:
    """テナントテーブル作成SQL（フォーマット済み）を返す公開 API（ADR-034）。"""
    return _TENANT_TABLES_SQL.format(
        schema=schema_name, schema_raw=schema_name, tenant_id=tenant_id
    )


def get_rls_enable_sql(schema_name: str) -> str:
    """RLS 有効化SQL（フォーマット済み）を返す公開 API（ADR-034）。"""
    return _RLS_ENABLE_SQL.format(schema=schema_name)


def get_rls_policy_sql(schema_name: str) -> str:
    """テナント分離 RLS ポリシーSQL（フォーマット済み）を返す公開 API（ADR-034）。"""
    return _RLS_POLICY_SQL.format(schema=schema_name, schema_raw=schema_name)


async def _execute_statements_preserving_do_blocks(db: AsyncSession, sql: str) -> None:
    """
    DO $$ ... END $$ ブロックを壊さずに複数SQL文を順次実行する。
    $$ 区切り内部のセミコロンは文の終わりとみなさない。
    """
    statements = _split_sql_preserving_do_blocks(sql)
    for stmt in statements:
        stmt = stmt.strip()
        if stmt:
            await db.execute(text(stmt))


def _split_sql_preserving_do_blocks(sql: str) -> list[str]:
    """
    DO $$ ... END $$ や CREATE FUNCTION ... AS $tag$ ... $tag$ 等の
    dollar-quoted ブロック内の ; を保持したまま SQL をステートメント単位に分割する。

    単純に ";" で split すると、ブロック内部の ; が文末と誤認されて SQL が壊れる。
    PostgreSQL の dollar quoting は `$$` だけでなく `$tag$ ... $tag$` の named tag
    形式もサポートする（例: `AS $sync_mpr$ ... $sync_mpr$`）。

    PR #256 Reviewer F1 修正:
      旧版は `$$` ペアしか認識せず、F16-FU2 で導入した `$sync_mpr$` を含む
      `_META_PAGE_ROUTING_TRIGGER_SQL` を分割すると関数本体内の `;` が文末扱いされ
      `unterminated dollar-quoted string` エラーになっていた。
      `scripts/migrate_meta_page_routing.py` の同名関数で既に named tag 対応版が
      動作実績ありのため、その実装をこちらに移植する。
    """
    statements: list[str] = []
    buf: list[str] = []
    i = 0
    in_dollar = False
    dollar_tag = ""

    while i < len(sql):
        if sql[i] == "$":
            # `$tag$` 形式（tag は英数字 + アンダースコア、`$$` は tag 空）の境界検出
            j = i + 1
            while j < len(sql) and (sql[j].isalnum() or sql[j] == "_"):
                j += 1
            if j < len(sql) and sql[j] == "$":
                tag = sql[i : j + 1]  # `$...$`
                if not in_dollar:
                    in_dollar = True
                    dollar_tag = tag
                    buf.append(tag)
                    i = j + 1
                    continue
                elif tag == dollar_tag:
                    in_dollar = False
                    dollar_tag = ""
                    buf.append(tag)
                    i = j + 1
                    continue
                # ブロック内で別 tag に出会った場合（ネスト）は通常 SQL では稀。
                # そのまま文字として buffer に積む。

        if sql[i] == ";" and not in_dollar:
            statements.append("".join(buf))
            buf = []
        else:
            buf.append(sql[i])
        i += 1

    if buf:
        statements.append("".join(buf))
    return statements


# setup_tenant.py 等の外部スクリプト向け公開エイリアス（ADR-034）。
# 内部実装は _split_sql_preserving_do_blocks に集約し、こちらは名前だけ公開する。
split_sql_preserving_do_blocks = _split_sql_preserving_do_blocks
