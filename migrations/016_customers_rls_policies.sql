-- ============================================================================
-- !! 警告 !! 警告 !! 警告 !!
--
-- このSQLファイルは **テンプレート** です。`{schema}`, `{schema_raw}`,
-- `{tenant_id}` のプレースホルダを含むため、そのまま psql 等で実行すると
-- シンタックスエラーになります。
--
-- 必ず scripts/migrate_phase1_redesign.py 経由で実行してください。
--
-- ============================================================================
--
-- Phase 1 再設計 / Migration 016: customers 系テーブルの RLS ポリシー
--
-- 内容:
--   - customers / customer_addresses / customer_sales_channels / customer_discord
--     の4テーブルで RLS を有効化
--   - customers 本体は tenant_id 列で直接分離
--   - 副テーブル（住所/チャネル/Discord）は customers を経由して分離
--   - 新仕様 SQL 用の public.current_tenant_id() ラッパ関数を使用
--     （既存ポリシーの current_setting('app.tenant_id', true)::INTEGER と完全等価）
--
-- 前提:
--   - 014 で public.current_tenant_id() が定義済み
--   - 015 で customers 系4テーブルが作成済み
--
-- 変更履歴:
--   2026-04-23: 初版作成（Phase 1 再設計）

ALTER TABLE {schema}.customers ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.customer_addresses ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.customer_sales_channels ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.customer_discord ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    -- 本体: tenant_id 列で直接分離
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE policyname = 'tenant_isolation_customers'
          AND schemaname = '{schema_raw}'
    ) THEN
        CREATE POLICY tenant_isolation_customers ON {schema}.customers
            USING (tenant_id = public.current_tenant_id());
    END IF;

    -- 副テーブル: customers を経由して分離（副テーブルは tenant_id 列を持たない）
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE policyname = 'tenant_isolation_customer_addresses'
          AND schemaname = '{schema_raw}'
    ) THEN
        CREATE POLICY tenant_isolation_customer_addresses ON {schema}.customer_addresses
            USING (EXISTS (
                SELECT 1 FROM {schema}.customers c
                WHERE c.id = customer_addresses.customer_id
                  AND c.tenant_id = public.current_tenant_id()
            ));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE policyname = 'tenant_isolation_customer_sales_channels'
          AND schemaname = '{schema_raw}'
    ) THEN
        CREATE POLICY tenant_isolation_customer_sales_channels ON {schema}.customer_sales_channels
            USING (EXISTS (
                SELECT 1 FROM {schema}.customers c
                WHERE c.id = customer_sales_channels.customer_id
                  AND c.tenant_id = public.current_tenant_id()
            ));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE policyname = 'tenant_isolation_customer_discord'
          AND schemaname = '{schema_raw}'
    ) THEN
        CREATE POLICY tenant_isolation_customer_discord ON {schema}.customer_discord
            USING (EXISTS (
                SELECT 1 FROM {schema}.customers c
                WHERE c.id = customer_discord.customer_id
                  AND c.tenant_id = public.current_tenant_id()
            ));
    END IF;
END $$;
