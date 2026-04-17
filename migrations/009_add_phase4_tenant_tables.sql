-- ============================================================================
-- !! 警告 !! テンプレート。scripts/migrate_phase4.py 経由で実行。
-- ============================================================================
-- Phase 4: コミュニケーション・運用テーブル
-- 変更履歴: 2026-04-17 初版

-- === Discord Webhook 設定 ===
CREATE TABLE IF NOT EXISTS {schema}.notification_channels (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL DEFAULT {tenant_id},
    channel_type VARCHAR(20) NOT NULL DEFAULT 'discord',
    channel_name VARCHAR(100) NOT NULL,
    webhook_url VARCHAR(500) NOT NULL,
    event_types TEXT DEFAULT '[]',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- === 通知ログ ===
CREATE TABLE IF NOT EXISTS {schema}.notification_logs (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL DEFAULT {tenant_id},
    channel_id INTEGER REFERENCES {schema}.notification_channels(id),
    event_type VARCHAR(50) NOT NULL,
    title VARCHAR(255) NOT NULL,
    message TEXT,
    status VARCHAR(20) DEFAULT 'pending',
    sent_at TIMESTAMPTZ,
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- === 日報・週報・月報 ===
CREATE TABLE IF NOT EXISTS {schema}.staff_reports (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL DEFAULT {tenant_id},
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
    reviewed_at TIMESTAMPTZ,
    submitted_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_staff_reports_user ON {schema}.staff_reports (user_id);
CREATE INDEX IF NOT EXISTS idx_staff_reports_type ON {schema}.staff_reports (report_type);

-- === アーカイブ管理 ===
CREATE TABLE IF NOT EXISTS {schema}.archives (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL DEFAULT {tenant_id},
    source_table VARCHAR(100) NOT NULL,
    source_id INTEGER NOT NULL,
    archived_data JSONB NOT NULL,
    archived_by INTEGER,
    archived_at TIMESTAMPTZ DEFAULT NOW(),
    restored_at TIMESTAMPTZ,
    restored_by INTEGER
);
CREATE INDEX IF NOT EXISTS idx_archives_source ON {schema}.archives (source_table, source_id);

-- === RLS ===
ALTER TABLE {schema}.notification_channels ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.notification_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.staff_reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.archives ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_notification_channels' AND schemaname = '{schema_raw}') THEN
        CREATE POLICY tenant_isolation_notification_channels ON {schema}.notification_channels
            USING (tenant_id = current_setting('app.tenant_id', true)::INTEGER);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_notification_logs' AND schemaname = '{schema_raw}') THEN
        CREATE POLICY tenant_isolation_notification_logs ON {schema}.notification_logs
            USING (tenant_id = current_setting('app.tenant_id', true)::INTEGER);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_staff_reports' AND schemaname = '{schema_raw}') THEN
        CREATE POLICY tenant_isolation_staff_reports ON {schema}.staff_reports
            USING (tenant_id = current_setting('app.tenant_id', true)::INTEGER);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_archives' AND schemaname = '{schema_raw}') THEN
        CREATE POLICY tenant_isolation_archives ON {schema}.archives
            USING (tenant_id = current_setting('app.tenant_id', true)::INTEGER);
    END IF;
END $$;
