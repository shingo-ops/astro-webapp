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
-- 顧客データ
CREATE TABLE IF NOT EXISTS {schema}.customers (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL DEFAULT {tenant_id},
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
    last_transaction_date TIMESTAMPTZ,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- リード管理
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
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 商談データ
CREATE TABLE IF NOT EXISTS {schema}.deals (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL DEFAULT {tenant_id},
    deal_code VARCHAR(20),
    customer_id INTEGER REFERENCES {schema}.customers(id),
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

-- 注文データ
CREATE TABLE IF NOT EXISTS {schema}.orders (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL DEFAULT {tenant_id},
    customer_id INTEGER REFERENCES {schema}.customers(id),
    deal_id INTEGER REFERENCES {schema}.deals(id),
    order_number VARCHAR(100) NOT NULL,
    total_amount NUMERIC(15, 2),
    status VARCHAR(50) DEFAULT 'pending',
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

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

-- === Phase 2: 販売・財務プロセス ===

-- 商品マスタ
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
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

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
    customer_id INTEGER NOT NULL REFERENCES {schema}.customers(id),
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
    customer_id INTEGER NOT NULL REFERENCES {schema}.customers(id),
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
    message_id  VARCHAR(100),
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
END $$
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

    # commitは呼び出し元で行う（監査ログ等と一括でcommitするため）
    return schema_name


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
    DO $$ ... END $$ ブロック内の ; を保持したまま SQL をステートメント単位に分割する。

    単純に ";" で split すると、DO $$ 内部の ; が文末と誤認されて
    SQL が壊れる。$$ ペアを検出して「ブロック内」か判定する。
    """
    result: list[str] = []
    buffer: list[str] = []
    in_dollar_block = False
    i = 0
    while i < len(sql):
        if sql[i:i + 2] == "$$":
            in_dollar_block = not in_dollar_block
            buffer.append("$$")
            i += 2
            continue
        ch = sql[i]
        if ch == ";" and not in_dollar_block:
            result.append("".join(buffer))
            buffer = []
        else:
            buffer.append(ch)
        i += 1
    if buffer:
        result.append("".join(buffer))
    return result
