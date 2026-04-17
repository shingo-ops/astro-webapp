-- ============================================================================
-- !! 警告 !! このSQLファイルは **テンプレート** です。
-- {schema}, {schema_raw}, {tenant_id} のプレースホルダを含むため、
-- そのまま psql で実行するとシンタックスエラーになります。
--
-- 必ず scripts/migrate_phase2.py 経由で実行してください:
--   docker compose exec backend python /app/scripts/migrate_phase2.py
-- ============================================================================
--
-- Phase 2: テナントスキーマ拡張テンプレート（販売・財務プロセス）
--
-- 内容:
--   - 新テーブル: products, shipping_zones, shipping_rates,
--                 quotes, quote_items, invoices, invoice_items
--   - 既存テーブルへの拡張: orders（配送カラム追加）
--   - RLS有効化＋ポリシー
--
-- 変更履歴:
--   2026-04-17: 初版作成

-- === 商品マスタ ===
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
CREATE INDEX IF NOT EXISTS idx_products_category ON {schema}.products (category);
CREATE INDEX IF NOT EXISTS idx_products_status ON {schema}.products (status);

-- === 配送ゾーン ===
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

-- === 配送料金 ===
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
CREATE INDEX IF NOT EXISTS idx_shipping_rates_lookup ON {schema}.shipping_rates (carrier, zone);

-- === 見積ヘッダー ===
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
CREATE INDEX IF NOT EXISTS idx_quotes_status ON {schema}.quotes (status);
CREATE INDEX IF NOT EXISTS idx_quotes_customer ON {schema}.quotes (customer_id);

-- === 見積明細 ===
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

-- === 請求書ヘッダー ===
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
CREATE INDEX IF NOT EXISTS idx_invoices_status ON {schema}.invoices (status);
CREATE INDEX IF NOT EXISTS idx_invoices_customer ON {schema}.invoices (customer_id);

-- === 請求書明細 ===
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

-- === 注文テーブル拡張（配送情報追加） ===
ALTER TABLE {schema}.orders ADD COLUMN IF NOT EXISTS invoice_id INTEGER;
ALTER TABLE {schema}.orders ADD COLUMN IF NOT EXISTS currency VARCHAR(10) DEFAULT 'JPY';
ALTER TABLE {schema}.orders ADD COLUMN IF NOT EXISTS shipping_carrier VARCHAR(50);
ALTER TABLE {schema}.orders ADD COLUMN IF NOT EXISTS shipping_fee NUMERIC(15, 2);
ALTER TABLE {schema}.orders ADD COLUMN IF NOT EXISTS tracking_number VARCHAR(200);
ALTER TABLE {schema}.orders ADD COLUMN IF NOT EXISTS shipped_at TIMESTAMPTZ;
ALTER TABLE {schema}.orders ADD COLUMN IF NOT EXISTS delivered_at TIMESTAMPTZ;
ALTER TABLE {schema}.orders ADD COLUMN IF NOT EXISTS shipping_country VARCHAR(100);

-- invoice_id FK
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_orders_invoice'
          AND connamespace = (SELECT oid FROM pg_namespace WHERE nspname = '{schema_raw}')
    ) THEN
        ALTER TABLE {schema}.orders
            ADD CONSTRAINT fk_orders_invoice
            FOREIGN KEY (invoice_id) REFERENCES {schema}.invoices(id);
    END IF;
END $$;

-- === RLS有効化（新テーブル） ===
ALTER TABLE {schema}.products ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.shipping_zones ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.shipping_rates ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.quotes ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.quote_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.invoices ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.invoice_items ENABLE ROW LEVEL SECURITY;

-- === RLSポリシー ===
DO $$
BEGIN
    -- tenant_id 直接保持テーブル
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
END $$;
