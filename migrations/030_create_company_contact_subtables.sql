-- Phase 1-B-2 Step 2 / Migration 030: companies/contacts の副テーブル群
--
-- 新設する 5 テーブル:
--   1. company_addresses      - 会社単位の住所 (billing/delivery × branch_name で複数拠点対応 / Q3 H-C)
--   2. company_sales_channels - 会社が運営する販売チャネル (Q4 C-A)
--   3. contact_emails         - 担当者の追加メール (EMP-00005 問題対応と同パターン)
--   4. contact_discord        - 担当者単位の Discord 連携 (Q4 C-A)
--   5. contact_contact_channels - 担当者の連絡ツール (Phase 1-B-1 の customer_contact_channels を担当者単位に)
--
-- 既存テーブルとの関係:
--   - customer_addresses / customer_sales_channels / customer_discord / customer_contact_channels は
--     Step 3 のデータ移行完了まで維持。Step 5 で廃止。
--   - 本 migration で新テーブルを作るだけ（データ移行は Step 3）
--
-- 冪等: CREATE TABLE IF NOT EXISTS + pg_namespace 走査
-- 依存: migration 028 (companies) + 029 (contacts)

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

        -- 1) company_addresses
        EXECUTE format($q$
            CREATE TABLE IF NOT EXISTS %I.company_addresses (
                id SERIAL PRIMARY KEY,
                company_id INTEGER NOT NULL REFERENCES %I.companies(id) ON DELETE CASCADE,
                address_type VARCHAR(20) NOT NULL CHECK (address_type IN ('billing','delivery')),
                branch_name VARCHAR(100),
                name VARCHAR(255),
                email VARCHAR(255),
                telephone VARCHAR(50),
                tax_id VARCHAR(100),
                address_line_1 VARCHAR(255),
                address_line_2 VARCHAR(255),
                address_line_3 VARCHAR(255),
                city VARCHAR(100),
                state VARCHAR(100),
                zip VARCHAR(50),
                country_code CHAR(2),
                is_default BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        $q$, schema_rec.nspname, schema_rec.nspname);

        EXECUTE format('CREATE INDEX IF NOT EXISTS idx_company_addresses_company_id ON %I.company_addresses (company_id)', schema_rec.nspname);
        EXECUTE format('CREATE INDEX IF NOT EXISTS idx_company_addresses_type ON %I.company_addresses (company_id, address_type)', schema_rec.nspname);
        -- 1会社1 address_type につき is_default=TRUE は最大1つ
        EXECUTE format(
            'CREATE UNIQUE INDEX IF NOT EXISTS idx_company_addresses_one_default '
            'ON %I.company_addresses (company_id, address_type) WHERE is_default = TRUE',
            schema_rec.nspname
        );

        IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_company_addresses_updated_at' AND tgrelid = format('%I.company_addresses', schema_rec.nspname)::regclass) THEN
            EXECUTE format('CREATE TRIGGER trg_company_addresses_updated_at BEFORE UPDATE ON %I.company_addresses FOR EACH ROW EXECUTE FUNCTION %I.trg_set_updated_at()', schema_rec.nspname, schema_rec.nspname);
        END IF;

        -- 2) company_sales_channels
        EXECUTE format($q$
            CREATE TABLE IF NOT EXISTS %I.company_sales_channels (
                company_id INTEGER NOT NULL REFERENCES %I.companies(id) ON DELETE CASCADE,
                channel VARCHAR(30) NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (company_id, channel)
            )
        $q$, schema_rec.nspname, schema_rec.nspname);

        -- 3) contact_emails
        EXECUTE format($q$
            CREATE TABLE IF NOT EXISTS %I.contact_emails (
                id SERIAL PRIMARY KEY,
                contact_id INTEGER NOT NULL REFERENCES %I.contacts(id) ON DELETE CASCADE,
                email VARCHAR(255) NOT NULL,
                purpose VARCHAR(50),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE (contact_id, email)
            )
        $q$, schema_rec.nspname, schema_rec.nspname);

        EXECUTE format('CREATE INDEX IF NOT EXISTS idx_contact_emails_contact_id ON %I.contact_emails (contact_id)', schema_rec.nspname);

        -- 4) contact_discord（担当者単位、Discord固有情報）
        EXECUTE format($q$
            CREATE TABLE IF NOT EXISTS %I.contact_discord (
                contact_id INTEGER PRIMARY KEY REFERENCES %I.contacts(id) ON DELETE CASCADE,
                is_joined BOOLEAN NOT NULL DEFAULT FALSE,
                channel_id VARCHAR(50),
                user_id VARCHAR(50),
                invoice_webhook TEXT,
                shipment_webhook TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        $q$, schema_rec.nspname, schema_rec.nspname);

        IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_contact_discord_updated_at' AND tgrelid = format('%I.contact_discord', schema_rec.nspname)::regclass) THEN
            EXECUTE format('CREATE TRIGGER trg_contact_discord_updated_at BEFORE UPDATE ON %I.contact_discord FOR EACH ROW EXECUTE FUNCTION %I.trg_set_updated_at()', schema_rec.nspname, schema_rec.nspname);
        END IF;

        -- 5) contact_contact_channels（Phase 1-B-1 の customer_contact_channels を担当者単位に）
        EXECUTE format($q$
            CREATE TABLE IF NOT EXISTS %I.contact_contact_channels (
                id SERIAL PRIMARY KEY,
                contact_id INTEGER NOT NULL REFERENCES %I.contacts(id) ON DELETE CASCADE,
                channel VARCHAR(30) NOT NULL,
                purpose VARCHAR(50),
                is_primary BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        $q$, schema_rec.nspname, schema_rec.nspname);

        EXECUTE format('CREATE INDEX IF NOT EXISTS idx_ccc_new_contact_id ON %I.contact_contact_channels (contact_id)', schema_rec.nspname);
        EXECUTE format(
            'CREATE UNIQUE INDEX IF NOT EXISTS idx_ccc_new_one_primary_per_contact '
            'ON %I.contact_contact_channels (contact_id) WHERE is_primary = TRUE',
            schema_rec.nspname
        );

        IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_ccc_new_updated_at' AND tgrelid = format('%I.contact_contact_channels', schema_rec.nspname)::regclass) THEN
            EXECUTE format('CREATE TRIGGER trg_ccc_new_updated_at BEFORE UPDATE ON %I.contact_contact_channels FOR EACH ROW EXECUTE FUNCTION %I.trg_set_updated_at()', schema_rec.nspname, schema_rec.nspname);
        END IF;

        -- RLS: 全テーブルで親経由分離
        EXECUTE format('ALTER TABLE %I.company_addresses ENABLE ROW LEVEL SECURITY', schema_rec.nspname);
        EXECUTE format('ALTER TABLE %I.company_sales_channels ENABLE ROW LEVEL SECURITY', schema_rec.nspname);
        EXECUTE format('ALTER TABLE %I.contact_emails ENABLE ROW LEVEL SECURITY', schema_rec.nspname);
        EXECUTE format('ALTER TABLE %I.contact_discord ENABLE ROW LEVEL SECURITY', schema_rec.nspname);
        EXECUTE format('ALTER TABLE %I.contact_contact_channels ENABLE ROW LEVEL SECURITY', schema_rec.nspname);

        -- RLS ポリシー（companies/contacts 経由で tenant_id 分離）
        IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_company_addresses' AND schemaname = schema_rec.nspname) THEN
            EXECUTE format($q$
                CREATE POLICY tenant_isolation_company_addresses ON %I.company_addresses
                    USING (EXISTS (
                        SELECT 1 FROM %I.companies c
                        WHERE c.id = company_addresses.company_id AND c.tenant_id = public.current_tenant_id()
                    ))
            $q$, schema_rec.nspname, schema_rec.nspname);
        END IF;

        IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_company_sales_channels' AND schemaname = schema_rec.nspname) THEN
            EXECUTE format($q$
                CREATE POLICY tenant_isolation_company_sales_channels ON %I.company_sales_channels
                    USING (EXISTS (
                        SELECT 1 FROM %I.companies c
                        WHERE c.id = company_sales_channels.company_id AND c.tenant_id = public.current_tenant_id()
                    ))
            $q$, schema_rec.nspname, schema_rec.nspname);
        END IF;

        IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_contact_emails' AND schemaname = schema_rec.nspname) THEN
            EXECUTE format($q$
                CREATE POLICY tenant_isolation_contact_emails ON %I.contact_emails
                    USING (EXISTS (
                        SELECT 1 FROM %I.contacts ct
                        WHERE ct.id = contact_emails.contact_id AND ct.tenant_id = public.current_tenant_id()
                    ))
            $q$, schema_rec.nspname, schema_rec.nspname);
        END IF;

        IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_contact_discord' AND schemaname = schema_rec.nspname) THEN
            EXECUTE format($q$
                CREATE POLICY tenant_isolation_contact_discord ON %I.contact_discord
                    USING (EXISTS (
                        SELECT 1 FROM %I.contacts ct
                        WHERE ct.id = contact_discord.contact_id AND ct.tenant_id = public.current_tenant_id()
                    ))
            $q$, schema_rec.nspname, schema_rec.nspname);
        END IF;

        IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_contact_contact_channels' AND schemaname = schema_rec.nspname) THEN
            EXECUTE format($q$
                CREATE POLICY tenant_isolation_contact_contact_channels ON %I.contact_contact_channels
                    USING (EXISTS (
                        SELECT 1 FROM %I.contacts ct
                        WHERE ct.id = contact_contact_channels.contact_id AND ct.tenant_id = public.current_tenant_id()
                    ))
            $q$, schema_rec.nspname, schema_rec.nspname);
        END IF;

        applied_count := applied_count + 1;
        RAISE NOTICE 'migration 030: %: 副テーブル5本適用完了', schema_rec.nspname;
    END LOOP;
    RAISE NOTICE 'migration 030: 全 % テナントに副テーブルを適用', applied_count;
END $$;
