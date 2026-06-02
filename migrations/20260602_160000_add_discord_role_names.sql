-- ADR-091 KPI7 拡張: tenant_discord_ticket_config にロール名カラム追加
-- Small → small_role_name (デフォルト: Member)
-- Large → large_role_name (デフォルト: Partner)
-- 既存テナントはデフォルト値がそのまま適用される。

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relname = 'tenant_discord_ticket_config'
    ) THEN
        ALTER TABLE public.tenant_discord_ticket_config
            ADD COLUMN IF NOT EXISTS small_role_name VARCHAR(100) NOT NULL DEFAULT 'Member',
            ADD COLUMN IF NOT EXISTS large_role_name VARCHAR(100) NOT NULL DEFAULT 'Partner';
    END IF;
END
$$;
