-- ============================================================================
-- !! 警告 !! このSQLファイルは **テンプレート** です。
-- 必ず scripts/migrate_phase3.py 経由で実行してください。
-- ============================================================================
--
-- Phase 3: テナントスキーマ拡張（仕入れ・調達管理）
--
-- 変更履歴:
--   2026-04-17: 初版作成

-- === 仕入先マスタ ===
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
CREATE INDEX IF NOT EXISTS idx_suppliers_active ON {schema}.suppliers (is_active);

-- === 仕入注文ヘッダー ===
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
CREATE INDEX IF NOT EXISTS idx_po_status ON {schema}.purchase_orders (status);
CREATE INDEX IF NOT EXISTS idx_po_supplier ON {schema}.purchase_orders (supplier_id);

-- === 仕入注文明細 ===
CREATE TABLE IF NOT EXISTS {schema}.purchase_order_items (
    id SERIAL PRIMARY KEY,
    purchase_order_id INTEGER NOT NULL REFERENCES {schema}.purchase_orders(id) ON DELETE CASCADE,
    product_id INTEGER NOT NULL REFERENCES {schema}.products(id),
    quantity INTEGER NOT NULL DEFAULT 1,
    unit_cost NUMERIC(15, 2) NOT NULL,
    subtotal NUMERIC(15, 2) NOT NULL,
    sort_order INTEGER DEFAULT 0
);

-- === RLS有効化 ===
ALTER TABLE {schema}.suppliers ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.purchase_orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.purchase_order_items ENABLE ROW LEVEL SECURITY;

-- === RLSポリシー ===
DO $$
BEGIN
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
END $$;
