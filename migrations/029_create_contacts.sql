-- Phase 1-B-2 Step 2 / Migration 029: contacts テーブル作成
--
-- 会社 (companies) に紐付く担当者マスタ。
-- 1社に複数 contact、1 contact は 1 社（is_primary_contact で窓口フラグ）。
--
-- 冪等: CREATE TABLE IF NOT EXISTS + pg_namespace 走査
-- 依存: migration 028（companies） + 014（current_tenant_id）

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

        EXECUTE format($q$
            CREATE TABLE IF NOT EXISTS %I.contacts (
                id SERIAL PRIMARY KEY,
                tenant_id INTEGER NOT NULL,
                company_id INTEGER NOT NULL REFERENCES %I.companies(id) ON DELETE CASCADE,
                contact_code VARCHAR(20) NOT NULL,
                lead_id INTEGER REFERENCES %I.leads(id),
                surname VARCHAR(100),
                given_name VARCHAR(100),
                display_name VARCHAR(255),
                job_title VARCHAR(100),
                department VARCHAR(100),
                is_primary_contact BOOLEAN NOT NULL DEFAULT FALSE,
                primary_email VARCHAR(255),
                primary_phone VARCHAR(50),
                status VARCHAR(20) NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active','inactive','archived')),
                notes TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE (tenant_id, contact_code)
            )
        $q$, schema_rec.nspname, schema_rec.nspname, schema_rec.nspname);

        -- インデックス
        EXECUTE format(
            'CREATE INDEX IF NOT EXISTS idx_contacts_tenant_id ON %I.contacts (tenant_id)',
            schema_rec.nspname
        );
        EXECUTE format(
            'CREATE INDEX IF NOT EXISTS idx_contacts_company_id ON %I.contacts (company_id)',
            schema_rec.nspname
        );
        EXECUTE format(
            'CREATE INDEX IF NOT EXISTS idx_contacts_lead_id ON %I.contacts (lead_id)',
            schema_rec.nspname
        );
        EXECUTE format(
            'CREATE INDEX IF NOT EXISTS idx_contacts_primary_email ON %I.contacts (primary_email)',
            schema_rec.nspname
        );
        -- 1社につき is_primary_contact=TRUE は最大1つ（部分UNIQUE INDEX）
        EXECUTE format(
            'CREATE UNIQUE INDEX IF NOT EXISTS idx_contacts_one_primary_per_company '
            'ON %I.contacts (company_id) WHERE is_primary_contact = TRUE',
            schema_rec.nspname
        );

        -- updated_at トリガ
        IF NOT EXISTS (
            SELECT 1 FROM pg_trigger
            WHERE tgname = 'trg_contacts_updated_at'
              AND tgrelid = format('%I.contacts', schema_rec.nspname)::regclass
        ) THEN
            EXECUTE format(
                'CREATE TRIGGER trg_contacts_updated_at BEFORE UPDATE ON %I.contacts '
                'FOR EACH ROW EXECUTE FUNCTION %I.trg_set_updated_at()',
                schema_rec.nspname, schema_rec.nspname
            );
        END IF;

        -- RLS
        EXECUTE format(
            'ALTER TABLE %I.contacts ENABLE ROW LEVEL SECURITY',
            schema_rec.nspname
        );

        IF NOT EXISTS (
            SELECT 1 FROM pg_policies
            WHERE policyname = 'tenant_isolation_contacts'
              AND schemaname = schema_rec.nspname
        ) THEN
            EXECUTE format($q$
                CREATE POLICY tenant_isolation_contacts ON %I.contacts
                    USING (tenant_id = public.current_tenant_id())
            $q$, schema_rec.nspname);
        END IF;

        applied_count := applied_count + 1;
        RAISE NOTICE 'migration 029: %: contacts テーブル適用完了', schema_rec.nspname;
    END LOOP;
    RAISE NOTICE 'migration 029: 全 % テナントに contacts を適用', applied_count;
END $$;
