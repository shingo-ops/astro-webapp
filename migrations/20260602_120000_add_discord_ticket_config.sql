-- ADR-091 KPI3: Discord チケット機能設定テーブル追加
-- 顧客専用チャンネル自動発行のための設定をテナント単位で管理する

-- チケット機能設定テーブル（publicスキーマ・テナント単位）
CREATE TABLE IF NOT EXISTS public.tenant_discord_ticket_config (
    tenant_id               INTEGER PRIMARY KEY REFERENCES public.tenants(id) ON DELETE CASCADE,
    ticket_category_id      VARCHAR(32) NOT NULL,
    ticket_button_channel_id VARCHAR(32) NOT NULL,
    staff_role_id           VARCHAR(32),
    welcome_template        TEXT NOT NULL DEFAULT 'ご連絡ありがとうございます。こちらのチャンネルでサポートいたします。',
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 全テナントの leads テーブルに discord_guild_channel_id カラムを追加
-- leads テーブルが存在するスキーマのみ適用（冪等）
DO $$
DECLARE
    schema_record RECORD;
BEGIN
    FOR schema_record IN
        SELECT nspname AS schema_name
        FROM pg_namespace
        WHERE nspname LIKE 'tenant_%'
        ORDER BY nspname
    LOOP
        -- leads テーブルが存在する場合のみ適用
        IF EXISTS (
            SELECT 1 FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = schema_record.schema_name
              AND c.relname = 'leads'
        ) THEN
            EXECUTE format(
                'ALTER TABLE %I.leads ADD COLUMN IF NOT EXISTS discord_guild_channel_id VARCHAR(50)',
                schema_record.schema_name
            );
            EXECUTE format(
                'CREATE INDEX IF NOT EXISTS idx_leads_discord_guild_channel_id
                 ON %I.leads (tenant_id, discord_guild_channel_id)
                 WHERE discord_guild_channel_id IS NOT NULL',
                schema_record.schema_name
            );
            RAISE NOTICE 'discord_guild_channel_id added to %.leads', schema_record.schema_name;
        ELSE
            RAISE NOTICE 'Skipping %.leads (table not found)', schema_record.schema_name;
        END IF;
    END LOOP;
END
$$;
