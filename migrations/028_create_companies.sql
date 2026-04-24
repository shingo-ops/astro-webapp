-- Phase 1-B-2 Step 2 / Migration 028: companies テーブル作成
--
-- 背景:
--   customers を companies (会社) + contacts (担当者) の2階層に分離する
--   Phase 1-B-2 の第1弾。本 migration は companies 本体のみ作成する。
--   既存 customers テーブルは Step 5 まで維持（段階移行）。
--
-- 冪等性:
--   - CREATE TABLE IF NOT EXISTS
--   - pg_namespace 走査で全 tenant_NNN schema に自動適用
--   - 再実行 no-op
--
-- 依存:
--   - migration 003 で roles/leads
--   - migration 019 で staff（sales_rep_id の FK先）
--   - migration 014 で public.current_tenant_id()
--
-- 変更履歴:
--   2026-04-23: 初版作成（Phase 1-B-2 Step 2）

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
        -- leads / staff テーブルが存在するスキーマのみ対象
        IF NOT EXISTS (
            SELECT 1 FROM pg_tables
            WHERE schemaname = schema_rec.nspname AND tablename = 'leads'
        ) OR NOT EXISTS (
            SELECT 1 FROM pg_tables
            WHERE schemaname = schema_rec.nspname AND tablename = 'staff'
        ) THEN
            CONTINUE;
        END IF;

        -- trg_set_updated_at() 関数を念のため再定義（冪等）
        EXECUTE format($q$
            CREATE OR REPLACE FUNCTION %I.trg_set_updated_at()
            RETURNS TRIGGER AS $fn$
            BEGIN
                NEW.updated_at = NOW();
                RETURN NEW;
            END;
            $fn$ LANGUAGE plpgsql
        $q$, schema_rec.nspname);

        -- companies テーブル作成（IF NOT EXISTS で冪等）
        EXECUTE format($q$
            CREATE TABLE IF NOT EXISTS %I.companies (
                id SERIAL PRIMARY KEY,
                tenant_id INTEGER NOT NULL,
                company_code VARCHAR(20) NOT NULL,
                lead_id INTEGER REFERENCES %I.leads(id),
                name VARCHAR(255) NOT NULL,
                name_en VARCHAR(255),
                normalized_name VARCHAR(255),
                is_individual BOOLEAN NOT NULL DEFAULT FALSE,
                industry VARCHAR(100),
                website VARCHAR(255),
                trust_level SMALLINT CHECK (trust_level IS NULL OR trust_level BETWEEN 1 AND 5),
                priority_focus VARCHAR(50),
                per_order_amount NUMERIC(15,2),
                monthly_frequency SMALLINT,
                monthly_forecast NUMERIC(15,2),
                monthly_forecast_source VARCHAR(20)
                    CHECK (monthly_forecast_source IS NULL OR monthly_forecast_source IN ('manual','ai_analysis')),
                monthly_forecast_updated_at TIMESTAMPTZ,
                billing_display_name VARCHAR(255),
                payment_recipient_name VARCHAR(255),
                fedex_account VARCHAR(100),
                shipping_note TEXT,
                status VARCHAR(20) NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active','inactive','archived','pending_dedup_review')),
                sales_rep_id INTEGER REFERENCES %I.staff(id),
                notes TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE (tenant_id, company_code)
            )
        $q$, schema_rec.nspname, schema_rec.nspname, schema_rec.nspname);

        -- インデックス（冪等）
        EXECUTE format(
            'CREATE INDEX IF NOT EXISTS idx_companies_tenant_id ON %I.companies (tenant_id)',
            schema_rec.nspname
        );
        EXECUTE format(
            'CREATE INDEX IF NOT EXISTS idx_companies_normalized_name ON %I.companies (normalized_name)',
            schema_rec.nspname
        );
        EXECUTE format(
            'CREATE INDEX IF NOT EXISTS idx_companies_lead_id ON %I.companies (lead_id)',
            schema_rec.nspname
        );
        EXECUTE format(
            'CREATE INDEX IF NOT EXISTS idx_companies_sales_rep_id ON %I.companies (sales_rep_id)',
            schema_rec.nspname
        );
        EXECUTE format(
            'CREATE INDEX IF NOT EXISTS idx_companies_status ON %I.companies (status)',
            schema_rec.nspname
        );

        -- updated_at トリガ
        IF NOT EXISTS (
            SELECT 1 FROM pg_trigger
            WHERE tgname = 'trg_companies_updated_at'
              AND tgrelid = format('%I.companies', schema_rec.nspname)::regclass
        ) THEN
            EXECUTE format(
                'CREATE TRIGGER trg_companies_updated_at BEFORE UPDATE ON %I.companies '
                'FOR EACH ROW EXECUTE FUNCTION %I.trg_set_updated_at()',
                schema_rec.nspname, schema_rec.nspname
            );
        END IF;

        -- RLS 有効化
        EXECUTE format(
            'ALTER TABLE %I.companies ENABLE ROW LEVEL SECURITY',
            schema_rec.nspname
        );

        -- RLS ポリシー（既存パターン: current_tenant_id() ラッパ関数使用）
        IF NOT EXISTS (
            SELECT 1 FROM pg_policies
            WHERE policyname = 'tenant_isolation_companies'
              AND schemaname = schema_rec.nspname
        ) THEN
            EXECUTE format($q$
                CREATE POLICY tenant_isolation_companies ON %I.companies
                    USING (tenant_id = public.current_tenant_id())
            $q$, schema_rec.nspname);
        END IF;

        applied_count := applied_count + 1;
        RAISE NOTICE 'migration 028: %: companies テーブル適用完了', schema_rec.nspname;
    END LOOP;
    RAISE NOTICE 'migration 028: 全 % テナントに companies を適用', applied_count;
END $$;
