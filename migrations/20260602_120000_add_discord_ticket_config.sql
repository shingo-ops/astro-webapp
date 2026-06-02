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
DO $$
DECLARE
    schema_name TEXT;
BEGIN
    FOR schema_name IN
        SELECT schema_name
        FROM information_schema.schemata
        WHERE schema_name LIKE 'tenant_%'
    LOOP
        EXECUTE format(
            'ALTER TABLE %I.leads ADD COLUMN IF NOT EXISTS discord_guild_channel_id VARCHAR(50)',
            schema_name
        );
        EXECUTE format(
            'CREATE INDEX IF NOT EXISTS idx_leads_discord_guild_channel_id
             ON %I.leads (tenant_id, discord_guild_channel_id)
             WHERE discord_guild_channel_id IS NOT NULL',
            schema_name
        );
    END LOOP;
END
$$;
