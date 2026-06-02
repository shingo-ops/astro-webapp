-- Migration: tenant_discord_ticket_config に顧客規模別チャンネル ID を追加 (ADR-091 KPI5)
--
-- 追加カラム:
--   small_channel_id VARCHAR(50) — 小口顧客向け専用チャンネルの Discord Snowflake ID
--   large_channel_id VARCHAR(50) — 大口顧客向け専用チャンネルの Discord Snowflake ID
--
-- 用途: estimated_scale (Small/Large) に対応するチャンネルへの招待メッセージ送信先
-- 冪等: ADD COLUMN IF NOT EXISTS / テーブル未存在時はスキップ

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relname = 'tenant_discord_ticket_config'
    ) THEN
        ALTER TABLE public.tenant_discord_ticket_config
            ADD COLUMN IF NOT EXISTS small_channel_id VARCHAR(50),
            ADD COLUMN IF NOT EXISTS large_channel_id VARCHAR(50);
        RAISE NOTICE 'Added small_channel_id and large_channel_id to tenant_discord_ticket_config';
    ELSE
        RAISE NOTICE 'tenant_discord_ticket_config does not exist, skipping';
    END IF;
END
$$;
