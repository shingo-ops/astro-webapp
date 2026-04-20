-- =====================================================================
-- Migration: 013 - Meta Webhook冪等性とリード重複防止
-- =====================================================================
-- 目的:
--   1. meta_messagesのMeta再送による重複挿入を防止（C2）
--   2. leadsの並列リクエストによる重複作成を防止（C1）
-- 冪等性:
--   ADD COLUMN IF NOT EXISTS / CREATE UNIQUE INDEX IF NOT EXISTS を使用
--   何度実行しても安全
-- 既存データへの影響:
--   - message_id列はNULL許可で追加するため既存行に影響なし
--   - leads UNIQUE INDEX追加前に重複を検出した場合はWARNINGを出してスキップ
-- =====================================================================

DO $$
DECLARE
    schema_record  RECORD;
    duplicate_count INTEGER;
BEGIN
    FOR schema_record IN
        SELECT nspname AS schema_name
        FROM pg_namespace
        WHERE nspname LIKE 'tenant_%'
        ORDER BY nspname
    LOOP
        RAISE NOTICE 'Processing schema: %', schema_record.schema_name;

        -- ============================================================
        -- C2: meta_messages に message_id 列を追加
        --     NULL許可（既存行・mid未取得メッセージへの影響なし）
        -- ============================================================
        EXECUTE format(
            'ALTER TABLE %I.meta_messages
             ADD COLUMN IF NOT EXISTS message_id VARCHAR(100)',
            schema_record.schema_name
        );

        -- message_id の UNIQUE 部分インデックス（NULL は除外）
        EXECUTE format(
            'CREATE UNIQUE INDEX IF NOT EXISTS idx_meta_messages_message_id_unique
             ON %I.meta_messages (message_id)
             WHERE message_id IS NOT NULL',
            schema_record.schema_name
        );

        RAISE NOTICE 'meta_messages: message_id column and unique index applied for %',
            schema_record.schema_name;

        -- ============================================================
        -- C1: leads(source) に UNIQUE 部分インデックスを追加
        --     既存重複がある場合はスキップしてWARNINGを出す（原則4）
        -- ============================================================
        EXECUTE format(
            'SELECT COUNT(*) FROM (
                SELECT source
                FROM %I.leads
                WHERE source LIKE ''messenger:%%''
                   OR source LIKE ''instagram:%%''
                GROUP BY source
                HAVING COUNT(*) > 1
            ) dup',
            schema_record.schema_name
        ) INTO duplicate_count;

        IF duplicate_count > 0 THEN
            RAISE WARNING
                'Schema % has % duplicate leads with meta source. '
                'UNIQUE index idx_leads_meta_source_unique creation SKIPPED. '
                'Manually deduplicate before re-running.',
                schema_record.schema_name, duplicate_count;
        ELSE
            EXECUTE format(
                'CREATE UNIQUE INDEX IF NOT EXISTS idx_leads_meta_source_unique
                 ON %I.leads (source)
                 WHERE source LIKE ''messenger:%%''
                    OR source LIKE ''instagram:%%''',
                schema_record.schema_name
            );
            RAISE NOTICE 'leads: UNIQUE index idx_leads_meta_source_unique created for %',
                schema_record.schema_name;
        END IF;

    END LOOP;

    RAISE NOTICE 'Migration 013 completed.';
END $$;

-- =====================================================================
-- Rollback手順（緊急時のみ手動実行）:
--
-- DO $$
-- DECLARE
--     r RECORD;
-- BEGIN
--     FOR r IN SELECT nspname FROM pg_namespace WHERE nspname LIKE 'tenant_%'
--     LOOP
--         EXECUTE format('DROP INDEX IF EXISTS %I.idx_meta_messages_message_id_unique', r.nspname);
--         EXECUTE format('DROP INDEX IF EXISTS %I.idx_leads_meta_source_unique', r.nspname);
--         EXECUTE format('ALTER TABLE %I.meta_messages DROP COLUMN IF EXISTS message_id', r.nspname);
--     END LOOP;
-- END $$;
-- =====================================================================
