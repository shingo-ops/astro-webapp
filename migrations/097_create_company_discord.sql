-- Migration 097: 全テナントに company_discord テーブルを新設（ADR-089 Sprint 1 / F1）
--
-- 目的:
--   customer_discord（customers 副テーブル）の後継として company_discord を作成する。
--   1会社1行の任意テーブル（Discord を使う会社のみ行が存在する）。
--
-- 構造:
--   customer_discord と同一カラム構成。PK が customer_id → company_id に変わるのみ。
--
-- 影響テーブル: {tenant_NNN}.company_discord（新設）
-- 適用対象: 全テナント（pg_namespace 走査・冪等適用）
-- 冪等: CREATE TABLE IF NOT EXISTS / CREATE POLICY IF NOT EXISTS
-- 依存: migration 028 (companies テーブル)

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
        -- companies テーブルが存在しないテナントはスキップ
        IF NOT EXISTS (
            SELECT 1 FROM pg_tables
            WHERE schemaname = schema_rec.nspname AND tablename = 'companies'
        ) THEN
            RAISE NOTICE 'migration 097: %: companies テーブルが存在しないためスキップ', schema_rec.nspname;
            CONTINUE;
        END IF;

        -- company_discord テーブル新設
        EXECUTE format($q$
            CREATE TABLE IF NOT EXISTS %I.company_discord (
                company_id INTEGER PRIMARY KEY REFERENCES %I.companies(id) ON DELETE CASCADE,
                is_joined BOOLEAN NOT NULL DEFAULT FALSE,
                channel_id VARCHAR(50),
                user_id VARCHAR(50),
                invoice_webhook TEXT,
                shipment_webhook TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        $q$, schema_rec.nspname, schema_rec.nspname);

        EXECUTE format(
            'COMMENT ON TABLE %I.company_discord IS '
            '''Discord を使う会社のみ1行（スカスカ列を本体に入れないため副テーブル化）''',
            schema_rec.nspname
        );

        -- updated_at トリガ（trg_set_updated_at は migration 015 以降全テナントに存在）
        IF NOT EXISTS (
            SELECT 1 FROM pg_trigger
            WHERE tgname = 'trg_company_discord_updated_at'
              AND tgrelid = format('%I.company_discord', schema_rec.nspname)::regclass
        ) THEN
            EXECUTE format(
                'CREATE TRIGGER trg_company_discord_updated_at '
                'BEFORE UPDATE ON %I.company_discord '
                'FOR EACH ROW EXECUTE FUNCTION %I.trg_set_updated_at()',
                schema_rec.nspname, schema_rec.nspname
            );
        END IF;

        -- RLS 有効化
        EXECUTE format('ALTER TABLE %I.company_discord ENABLE ROW LEVEL SECURITY', schema_rec.nspname);

        -- RLS ポリシー（companies 経由でテナント分離）
        IF NOT EXISTS (
            SELECT 1 FROM pg_policies
            WHERE policyname = 'tenant_isolation_company_discord'
              AND schemaname = schema_rec.nspname
        ) THEN
            EXECUTE format($q$
                CREATE POLICY tenant_isolation_company_discord ON %I.company_discord
                    USING (EXISTS (
                        SELECT 1 FROM %I.companies c
                        WHERE c.id = company_discord.company_id
                          AND c.tenant_id = public.current_tenant_id()
                    ))
            $q$, schema_rec.nspname, schema_rec.nspname);
        END IF;

        applied_count := applied_count + 1;
        RAISE NOTICE 'migration 097: %: company_discord 作成完了', schema_rec.nspname;
    END LOOP;

    RAISE NOTICE 'migration 097: 完了 — % テナントに company_discord を作成', applied_count;
END $$;
