-- Phase 1: テナントスキーマ拡張テンプレート
--
-- 注意: このファイルは scripts/migrate_phase1.py が `{schema}` `{schema_raw}` `{tenant_id}` を置換して使用する。
-- 直接 psql で実行せず、必ずスクリプト経由で適用すること。
--
-- 内容:
--   - 新テーブル: roles, role_permissions, user_roles, leads, teams, team_members
--   - 既存テーブルへの拡張: customers, deals
--   - シーケンス: customer_code_seq, deal_code_seq, lead_code_seq
--   - RLS有効化＋ポリシー: roles, leads, teams
--
-- 変更履歴:
--   2026-04-16: 初版作成

-- === シーケンス（コード自動採番用） ===
CREATE SEQUENCE IF NOT EXISTS {schema}.customer_code_seq START 1;
CREATE SEQUENCE IF NOT EXISTS {schema}.deal_code_seq START 1;
CREATE SEQUENCE IF NOT EXISTS {schema}.lead_code_seq START 1;

-- 既存レコードを跨いでシーケンスを進める（既存IDと衝突しないよう調整）
DO $$
DECLARE
    max_id INTEGER;
BEGIN
    SELECT COALESCE(MAX(id), 0) + 1 INTO max_id FROM {schema}.customers;
    PERFORM setval('{schema}.customer_code_seq', max_id, false);

    SELECT COALESCE(MAX(id), 0) + 1 INTO max_id FROM {schema}.deals;
    PERFORM setval('{schema}.deal_code_seq', max_id, false);
END $$;

-- === ロール管理テーブル ===
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

CREATE TABLE IF NOT EXISTS {schema}.role_permissions (
    id SERIAL PRIMARY KEY,
    role_id INTEGER NOT NULL REFERENCES {schema}.roles(id) ON DELETE CASCADE,
    permission_id INTEGER NOT NULL REFERENCES public.permissions(id) ON DELETE CASCADE,
    UNIQUE(role_id, permission_id)
);

CREATE TABLE IF NOT EXISTS {schema}.user_roles (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    role_id INTEGER NOT NULL REFERENCES {schema}.roles(id) ON DELETE CASCADE,
    assigned_at TIMESTAMPTZ DEFAULT NOW(),
    assigned_by INTEGER,
    UNIQUE(user_id, role_id)
);

CREATE INDEX IF NOT EXISTS idx_user_roles_user ON {schema}.user_roles (user_id);

-- === リード管理テーブル ===
CREATE TABLE IF NOT EXISTS {schema}.leads (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL DEFAULT {tenant_id},
    lead_code VARCHAR(20) NOT NULL DEFAULT 'LD-' || LPAD(nextval('{schema}.lead_code_seq')::TEXT, 5, '0'),
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
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(tenant_id, lead_code)
);

CREATE INDEX IF NOT EXISTS idx_leads_status ON {schema}.leads (status);
CREATE INDEX IF NOT EXISTS idx_leads_assigned_to ON {schema}.leads (assigned_to);

-- === チーム管理テーブル ===
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

CREATE INDEX IF NOT EXISTS idx_team_members_team ON {schema}.team_members (team_id);
CREATE INDEX IF NOT EXISTS idx_team_members_user ON {schema}.team_members (user_id);

-- === 顧客テーブル拡張 ===
ALTER TABLE {schema}.customers ADD COLUMN IF NOT EXISTS customer_code VARCHAR(20);
ALTER TABLE {schema}.customers ADD COLUMN IF NOT EXISTS registration_source VARCHAR(50);
ALTER TABLE {schema}.customers ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'active';
ALTER TABLE {schema}.customers ADD COLUMN IF NOT EXISTS billing_name VARCHAR(255);
ALTER TABLE {schema}.customers ADD COLUMN IF NOT EXISTS billing_phone VARCHAR(50);
ALTER TABLE {schema}.customers ADD COLUMN IF NOT EXISTS billing_email VARCHAR(255);
ALTER TABLE {schema}.customers ADD COLUMN IF NOT EXISTS billing_address TEXT;
ALTER TABLE {schema}.customers ADD COLUMN IF NOT EXISTS delivery_name VARCHAR(255);
ALTER TABLE {schema}.customers ADD COLUMN IF NOT EXISTS delivery_phone VARCHAR(50);
ALTER TABLE {schema}.customers ADD COLUMN IF NOT EXISTS delivery_email VARCHAR(255);
ALTER TABLE {schema}.customers ADD COLUMN IF NOT EXISTS delivery_address TEXT;
ALTER TABLE {schema}.customers ADD COLUMN IF NOT EXISTS delivery_country VARCHAR(100);
ALTER TABLE {schema}.customers ADD COLUMN IF NOT EXISTS business_id VARCHAR(100);
ALTER TABLE {schema}.customers ADD COLUMN IF NOT EXISTS transaction_count INTEGER DEFAULT 0;
ALTER TABLE {schema}.customers ADD COLUMN IF NOT EXISTS last_transaction_date TIMESTAMPTZ;

UPDATE {schema}.customers
SET customer_code = 'CT-' || LPAD(id::TEXT, 5, '0')
WHERE customer_code IS NULL;

-- === 案件テーブル拡張 ===
ALTER TABLE {schema}.deals ADD COLUMN IF NOT EXISTS deal_code VARCHAR(20);
ALTER TABLE {schema}.deals ADD COLUMN IF NOT EXISTS lead_id INTEGER REFERENCES {schema}.leads(id);
ALTER TABLE {schema}.deals ADD COLUMN IF NOT EXISTS assigned_to INTEGER;
ALTER TABLE {schema}.deals ADD COLUMN IF NOT EXISTS stage VARCHAR(50) DEFAULT 'open';
ALTER TABLE {schema}.deals ADD COLUMN IF NOT EXISTS probability INTEGER DEFAULT 10;
ALTER TABLE {schema}.deals ADD COLUMN IF NOT EXISTS lost_reason VARCHAR(255);
ALTER TABLE {schema}.deals ADD COLUMN IF NOT EXISTS currency VARCHAR(10) DEFAULT 'JPY';

UPDATE {schema}.deals
SET deal_code = 'DL-' || LPAD(id::TEXT, 5, '0')
WHERE deal_code IS NULL;

-- リード→案件のリンクは案件作成後に追加（forward reference 解決）
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

-- === RLS有効化（新テーブル） ===
ALTER TABLE {schema}.roles ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.leads ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.teams ENABLE ROW LEVEL SECURITY;

-- === RLSポリシー（新テーブル） ===
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_roles' AND schemaname = '{schema_raw}') THEN
        CREATE POLICY tenant_isolation_roles ON {schema}.roles
            USING (tenant_id = current_setting('app.tenant_id', true)::INTEGER);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_leads' AND schemaname = '{schema_raw}') THEN
        CREATE POLICY tenant_isolation_leads ON {schema}.leads
            USING (tenant_id = current_setting('app.tenant_id', true)::INTEGER);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_teams' AND schemaname = '{schema_raw}') THEN
        CREATE POLICY tenant_isolation_teams ON {schema}.teams
            USING (tenant_id = current_setting('app.tenant_id', true)::INTEGER);
    END IF;
END $$;
