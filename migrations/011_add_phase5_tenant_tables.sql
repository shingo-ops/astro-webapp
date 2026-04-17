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

-- === Buddyペアリング ===
CREATE TABLE IF NOT EXISTS {schema}.buddy_pairs (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL DEFAULT {tenant_id},
    coach_user_id INTEGER NOT NULL,
    mentee_user_id INTEGER NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    started_at TIMESTAMPTZ DEFAULT NOW(),
    ended_at TIMESTAMPTZ,
    notes TEXT,
    UNIQUE(tenant_id, coach_user_id, mentee_user_id)
);

-- === Buddyフィードバック ===
CREATE TABLE IF NOT EXISTS {schema}.buddy_feedbacks (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL DEFAULT {tenant_id},
    pair_id INTEGER NOT NULL REFERENCES {schema}.buddy_pairs(id) ON DELETE CASCADE,
    feedback_type VARCHAR(10) NOT NULL,
    reason TEXT,
    context TEXT,
    created_by INTEGER NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- === バッジ定義 ===
CREATE TABLE IF NOT EXISTS {schema}.badge_definitions (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL DEFAULT {tenant_id},
    name VARCHAR(100) NOT NULL,
    description VARCHAR(500),
    icon VARCHAR(10),
    criteria VARCHAR(500),
    points INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- === ユーザーバッジ獲得 ===
CREATE TABLE IF NOT EXISTS {schema}.user_badges (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL DEFAULT {tenant_id},
    user_id INTEGER NOT NULL,
    badge_id INTEGER NOT NULL REFERENCES {schema}.badge_definitions(id) ON DELETE CASCADE,
    earned_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(tenant_id, user_id, badge_id)
);

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
ALTER TABLE {schema}.buddy_pairs ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.buddy_feedbacks ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.badge_definitions ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.user_badges ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.erp_sync_logs ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_shifts' AND schemaname = '{schema_raw}') THEN
        CREATE POLICY tenant_isolation_shifts ON {schema}.shifts
            USING (tenant_id = current_setting('app.tenant_id', true)::INTEGER);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_buddy_pairs' AND schemaname = '{schema_raw}') THEN
        CREATE POLICY tenant_isolation_buddy_pairs ON {schema}.buddy_pairs
            USING (tenant_id = current_setting('app.tenant_id', true)::INTEGER);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_buddy_feedbacks' AND schemaname = '{schema_raw}') THEN
        CREATE POLICY tenant_isolation_buddy_feedbacks ON {schema}.buddy_feedbacks
            USING (tenant_id = current_setting('app.tenant_id', true)::INTEGER);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_badge_definitions' AND schemaname = '{schema_raw}') THEN
        CREATE POLICY tenant_isolation_badge_definitions ON {schema}.badge_definitions
            USING (tenant_id = current_setting('app.tenant_id', true)::INTEGER);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_user_badges' AND schemaname = '{schema_raw}') THEN
        CREATE POLICY tenant_isolation_user_badges ON {schema}.user_badges
            USING (tenant_id = current_setting('app.tenant_id', true)::INTEGER);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_erp_sync_logs' AND schemaname = '{schema_raw}') THEN
        CREATE POLICY tenant_isolation_erp_sync_logs ON {schema}.erp_sync_logs
            USING (tenant_id = current_setting('app.tenant_id', true)::INTEGER);
    END IF;
END $$;
