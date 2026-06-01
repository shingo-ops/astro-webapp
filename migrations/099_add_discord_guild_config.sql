-- Migration 097: Discord Guild Config + Role Sync Status (Sprint D2)
--
-- 1. public.tenant_discord_config — テナントごとの Discord サーバー設定
-- 2. tenant_NNN.leads — discord_role_sync_status / discord_role_sync_at カラム追加

CREATE TABLE IF NOT EXISTS public.tenant_discord_config (
    tenant_id  INTEGER PRIMARY KEY REFERENCES public.tenants(id) ON DELETE CASCADE,
    guild_id   VARCHAR(32) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DO $$
DECLARE
    schema_name TEXT;
BEGIN
    FOR schema_name IN
        SELECT nspname FROM pg_namespace
        WHERE nspname ~ '^tenant_[0-9]+$'
    LOOP
        EXECUTE format(
            'ALTER TABLE %I.leads ADD COLUMN IF NOT EXISTS discord_role_sync_status VARCHAR(20)',
            schema_name
        );
        EXECUTE format(
            'ALTER TABLE %I.leads ADD COLUMN IF NOT EXISTS discord_role_sync_at TIMESTAMPTZ',
            schema_name
        );
    END LOOP;
END;
$$;
