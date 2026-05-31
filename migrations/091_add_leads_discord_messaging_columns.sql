-- Migration 091: leads テーブルに Discord 顧客メッセージング用カラムを追加
--
-- 目的:
--   Discord をMetaと同様の顧客向けメッセージングチャンネルとして受信箱に追加する。
--   - discord_user_id: Discord ユーザー Snowflake ID（API送信・受信の紐付け用）
--   - discord_dm_channel_id: BotとユーザーのDMチャンネルID（返信送信に使用）
--
-- 既存カラム:
--   migration 090 で discord_id（表示用ハンドル VARCHAR(255)）は追加済み。
--   本 migration はメッセージング処理に必要な別カラムを追加する。
--
-- 影響テーブル: {tenant_NNN}.leads
-- 適用対象: 全テナント（pg_namespace 走査で冪等適用）
-- 冪等: ADD COLUMN IF NOT EXISTS

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
        RAISE NOTICE 'Processing schema: %', schema_record.schema_name;

        EXECUTE format(
            'ALTER TABLE %I.leads
             ADD COLUMN IF NOT EXISTS discord_user_id       VARCHAR(50),
             ADD COLUMN IF NOT EXISTS discord_dm_channel_id VARCHAR(50)',
            schema_record.schema_name
        );

        -- discord_user_id ルックアップ用インデックス
        EXECUTE format(
            'CREATE INDEX IF NOT EXISTS idx_leads_discord_user_id
             ON %I.leads (tenant_id, discord_user_id)
             WHERE discord_user_id IS NOT NULL',
            schema_record.schema_name
        );

        -- source = ''discord:<user_id>'' で一意にする Partial Unique Index
        EXECUTE format(
            'CREATE UNIQUE INDEX IF NOT EXISTS idx_leads_discord_source_unique
             ON %I.leads (source)
             WHERE source LIKE ''discord:%%''',
            schema_record.schema_name
        );
    END LOOP;
END
$$;
