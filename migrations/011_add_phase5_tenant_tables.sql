-- ============================================================================
-- !! テンプレート。scripts/migrate_phase5.py 経由で実行。
-- ============================================================================
-- Phase 5: 拡張機能テーブル
-- 変更履歴: 2026-04-17 初版

-- === シフト管理 ===
CREATE TABLE IF NOT EXISTS {schema}.shifts (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL DEFAULT {tenant_id},
    user_id INTEGER NOT NULL,
    shift_date DATE NOT NULL,
    start_time TIME NOT NULL,
    end_time TIME NOT NULL,
    shift_type VARCHAR(20) DEFAULT 'normal',
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(tenant_id, user_id, shift_date)
);
CREATE INDEX IF NOT EXISTS idx_shifts_date ON {schema}.shifts (shift_date);
CREATE INDEX IF NOT EXISTS idx_shifts_user ON {schema}.shifts (user_id);

-- === ERP連携ログ ===
CREATE TABLE IF NOT EXISTS {schema}.erp_sync_logs (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL DEFAULT {tenant_id},
    sync_type VARCHAR(50) NOT NULL,
    direction VARCHAR(10) NOT NULL DEFAULT 'export',
    record_count INTEGER DEFAULT 0,
    status VARCHAR(20) DEFAULT 'pending',
    error_message TEXT,
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    created_by INTEGER
);

-- === RLS ===
ALTER TABLE {schema}.shifts ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.erp_sync_logs ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_shifts' AND schemaname = '{schema_raw}') THEN
        CREATE POLICY tenant_isolation_shifts ON {schema}.shifts
            USING (tenant_id = current_setting('app.tenant_id', true)::INTEGER);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_erp_sync_logs' AND schemaname = '{schema_raw}') THEN
        CREATE POLICY tenant_isolation_erp_sync_logs ON {schema}.erp_sync_logs
            USING (tenant_id = current_setting('app.tenant_id', true)::INTEGER);
    END IF;
END $$;
