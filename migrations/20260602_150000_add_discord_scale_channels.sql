-- Migration: tenant_discord_ticket_config に顧客規模別チャンネル ID を追加 (ADR-091 KPI5)
--
-- 追加カラム:
--   small_channel_id VARCHAR(50) — 小口顧客向け専用チャンネルの Discord Snowflake ID
--   large_channel_id VARCHAR(50) — 大口顧客向け専用チャンネルの Discord Snowflake ID
--
-- 用途: estimated_scale (Small/Large) に対応するチャンネルへの招待メッセージ送信先
-- 冪等: ADD COLUMN IF NOT EXISTS

ALTER TABLE public.tenant_discord_ticket_config
    ADD COLUMN IF NOT EXISTS small_channel_id VARCHAR(50),
    ADD COLUMN IF NOT EXISTS large_channel_id VARCHAR(50);
