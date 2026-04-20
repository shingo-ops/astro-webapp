-- ============================================================================
-- !! テンプレート。scripts/migrate_meta.py 経由で実行。
-- ============================================================================
-- Meta Messaging: メッセージ受信ログテーブル
-- 変更履歴: 2026-04-18 初版

-- === Meta メッセージログ ===
CREATE TABLE IF NOT EXISTS {schema}.meta_messages (
    id          SERIAL PRIMARY KEY,
    tenant_id   INTEGER NOT NULL DEFAULT {tenant_id},
    lead_id     INTEGER REFERENCES {schema}.leads(id) ON DELETE SET NULL,
    platform    VARCHAR(20) NOT NULL DEFAULT 'messenger',
    sender_id   VARCHAR(100) NOT NULL,
    sender_name VARCHAR(200),
    message_text TEXT,
    direction   VARCHAR(10) NOT NULL DEFAULT 'inbound',
    raw_payload JSONB,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_meta_messages_sender ON {schema}.meta_messages (sender_id);
CREATE INDEX IF NOT EXISTS idx_meta_messages_lead   ON {schema}.meta_messages (lead_id);
CREATE INDEX IF NOT EXISTS idx_meta_messages_ts     ON {schema}.meta_messages (created_at DESC);

-- === RLS ===
ALTER TABLE {schema}.meta_messages ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE policyname = 'tenant_isolation_meta_messages'
          AND schemaname = '{schema_raw}'
    ) THEN
        CREATE POLICY tenant_isolation_meta_messages ON {schema}.meta_messages
            USING (tenant_id = current_setting('app.tenant_id', true)::INTEGER);
    END IF;
END $$;
