-- Migration 095: leads テーブルに instagram_link / whatsapp_link を追加
--
-- 目的:
--   受信箱の連絡先タブから Instagram プロフィールURL および
--   WhatsApp リンクを顧客ごとに保存できるようにする。
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
             ADD COLUMN IF NOT EXISTS instagram_link VARCHAR(1000),
             ADD COLUMN IF NOT EXISTS whatsapp_link  VARCHAR(1000)',
            schema_record.schema_name
        );
    END LOOP;
END
$$;
