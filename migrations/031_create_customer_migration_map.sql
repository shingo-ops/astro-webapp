-- Phase 1-B-2 Step 2 / Migration 031: 旧customer ID → 新company/contact ID マッピングテーブル
--
-- 用途:
--   Step 3 のデータ移行で customers 1 件ごとに (new_company_id, new_contact_id) を記録。
--   Step 4 の下流テーブル FK 切替時に、deals/quotes/invoices/orders.customer_id を
--   このマップで JOIN して新 company_id/contact_id に変換する。
--   Step 5 の旧 customers drop までは保持、監査ログとしても有用。
--
-- 配置: tenant schema 内（各テナントで独立）
-- 冪等: CREATE TABLE IF NOT EXISTS + pg_namespace 走査

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
        ) OR NOT EXISTS (
            SELECT 1 FROM pg_tables
            WHERE schemaname = schema_rec.nspname AND tablename = 'contacts'
        ) THEN
            CONTINUE;
        END IF;

        -- _customer_migration_map（アンダースコアプレフィックスで内部用テーブル明示）
        EXECUTE format($q$
            CREATE TABLE IF NOT EXISTS %I._customer_migration_map (
                old_customer_id INTEGER PRIMARY KEY,
                new_company_id INTEGER NOT NULL REFERENCES %I.companies(id),
                new_contact_id INTEGER NOT NULL REFERENCES %I.contacts(id),
                migration_method VARCHAR(30) NOT NULL,
                migrated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                notes TEXT,
                CHECK (migration_method IN (
                    'auto_single',        -- グループ単独（個人 or 単一法人）
                    'auto_multi_branch',  -- 自動検出された会社名重複（Card Galaxy 等）
                    'manual_merge',       -- 手動マージマップ由来（Ocean Harvest 等）
                    'manual_override'     -- しんごさんが個別に修正
                ))
            )
        $q$, schema_rec.nspname, schema_rec.nspname, schema_rec.nspname);

        EXECUTE format(
            'CREATE INDEX IF NOT EXISTS idx_cmm_new_company_id ON %I._customer_migration_map (new_company_id)',
            schema_rec.nspname
        );
        EXECUTE format(
            'CREATE INDEX IF NOT EXISTS idx_cmm_new_contact_id ON %I._customer_migration_map (new_contact_id)',
            schema_rec.nspname
        );

        -- RLS: companies 経由で tenant 分離
        EXECUTE format('ALTER TABLE %I._customer_migration_map ENABLE ROW LEVEL SECURITY', schema_rec.nspname);

        IF NOT EXISTS (
            SELECT 1 FROM pg_policies
            WHERE policyname = 'tenant_isolation_customer_migration_map'
              AND schemaname = schema_rec.nspname
        ) THEN
            EXECUTE format($q$
                CREATE POLICY tenant_isolation_customer_migration_map ON %I._customer_migration_map
                    USING (EXISTS (
                        SELECT 1 FROM %I.companies c
                        WHERE c.id = _customer_migration_map.new_company_id
                          AND c.tenant_id = public.current_tenant_id()
                    ))
            $q$, schema_rec.nspname, schema_rec.nspname);
        END IF;

        applied_count := applied_count + 1;
        RAISE NOTICE 'migration 031: %: _customer_migration_map 適用完了', schema_rec.nspname;
    END LOOP;
    RAISE NOTICE 'migration 031: 全 % テナントに _customer_migration_map を適用', applied_count;
END $$;
