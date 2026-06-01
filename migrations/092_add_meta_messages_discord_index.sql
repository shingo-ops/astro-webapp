-- Migration 092: meta_messages テーブルに Discord 用インデックスを追加
--
-- 目的:
--   platform='discord' のメッセージを効率よく検索するためのインデックス。
--   meta_messages.platform は VARCHAR(20) で CHECK 制約なし（migration 012 参照）。
--   platform='discord' は既存スキーマに追加作業なしで格納可能。
--
-- 影響テーブル: {tenant_NNN}.meta_messages
-- 適用対象: 全テナント（pg_namespace 走査で冪等適用）
-- 冪等: CREATE INDEX IF NOT EXISTS

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
            'CREATE INDEX IF NOT EXISTS idx_meta_messages_discord
             ON %I.meta_messages (tenant_id, platform, lead_id)
             WHERE platform = ''discord''',
            schema_record.schema_name
        );
    END LOOP;
END
$$;
