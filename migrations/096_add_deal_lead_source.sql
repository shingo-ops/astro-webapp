-- Migration 096: 全テナントの deals に lead_source カラムを追加
--
-- 目的:
--   商談情報の顧客情報セクションに「流入元」を記録できるようにする。
--   リードの source と同じ自由入力テキスト（最大50文字）。
--
-- 影響テーブル: {tenant_NNN}.deals
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
            'ALTER TABLE %I.deals
             ADD COLUMN IF NOT EXISTS lead_source VARCHAR(50)',
            schema_record.schema_name
        );
    END LOOP;
END
$$;
