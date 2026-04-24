-- Phase 1-B-2 Step 5a / Migration 033: companies.is_individual カラム削除
--
-- 経緯:
--   Phase 1-B-2 設計時は個人顧客/法人顧客を区別する予定だったが、
--   実運用では区別が不要（Step 5 実装開始時にしんごさん判断）。
--   UI 側でも個人/法人を区別しない方針になったため、カラムごと削除する。
--
-- 本 migration で起こること:
--   ALTER TABLE companies DROP COLUMN IF EXISTS is_individual
--
-- 冪等:
--   - DROP COLUMN IF EXISTS で再実行 no-op
--   - pg_namespace 走査で全 tenant_NNN に適用
--
-- 依存: migration 028 (companies 存在)
--
-- 作成日: 2026-04-24

DO $$
DECLARE
    schema_rec RECORD;
    applied_count INTEGER := 0;
BEGIN
    FOR schema_rec IN
        SELECT nspname FROM pg_namespace
        WHERE nspname ~ '^tenant_\d+$'
        ORDER BY nspname
    LOOP
        IF NOT EXISTS (
            SELECT 1 FROM pg_tables
            WHERE schemaname = schema_rec.nspname AND tablename = 'companies'
        ) THEN
            CONTINUE;
        END IF;

        EXECUTE format(
            'ALTER TABLE %I.companies DROP COLUMN IF EXISTS is_individual',
            schema_rec.nspname
        );

        applied_count := applied_count + 1;
        RAISE NOTICE 'migration 033: %: is_individual カラム削除完了', schema_rec.nspname;
    END LOOP;
    RAISE NOTICE 'migration 033: 全 % テナントで is_individual を削除', applied_count;
END $$;
