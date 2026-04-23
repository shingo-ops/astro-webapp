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
-- Phase 1 再設計 / Migration 017: 既存 quotes / invoices / deals / orders の customer_id FK 再構築
--
-- 内容:
--   - 015 で FK を DROP し、quotes / invoices / deals / orders の既存サンプルデータは
--     TRUNCATE 済。本 migration で新 customers(id) への FK を付け直す
--   - 新 customers は空なので、新たな FK 違反は発生しない
--   - 今後これらのテーブルに行を入れる際は新 customers の id を参照
--
-- 前提:
--   - 015 で新 customers 作成済、既存 4本の FK は DROP 済
--   - 016 で RLS ポリシー設定済
--
-- 変更履歴:
--   2026-04-23: 初版作成（Phase 1 再設計）
--   2026-04-23: deals / orders の FK 再構築を追加（reviewer 指摘の Critical 1 対応）

-- quotes.customer_id を新 customers(id) に参照付け直し
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_quotes_customer'
          AND connamespace = (SELECT oid FROM pg_namespace WHERE nspname = '{schema_raw}')
    ) THEN
        ALTER TABLE {schema}.quotes
            ADD CONSTRAINT fk_quotes_customer
            FOREIGN KEY (customer_id) REFERENCES {schema}.customers(id);
    END IF;
END $$;

-- invoices.customer_id を新 customers(id) に参照付け直し
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_invoices_customer'
          AND connamespace = (SELECT oid FROM pg_namespace WHERE nspname = '{schema_raw}')
    ) THEN
        ALTER TABLE {schema}.invoices
            ADD CONSTRAINT fk_invoices_customer
            FOREIGN KEY (customer_id) REFERENCES {schema}.customers(id);
    END IF;
END $$;

-- deals.customer_id を新 customers(id) に参照付け直し
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_deals_customer'
          AND connamespace = (SELECT oid FROM pg_namespace WHERE nspname = '{schema_raw}')
    ) THEN
        ALTER TABLE {schema}.deals
            ADD CONSTRAINT fk_deals_customer
            FOREIGN KEY (customer_id) REFERENCES {schema}.customers(id);
    END IF;
END $$;

-- orders.customer_id を新 customers(id) に参照付け直し
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_orders_customer'
          AND connamespace = (SELECT oid FROM pg_namespace WHERE nspname = '{schema_raw}')
    ) THEN
        ALTER TABLE {schema}.orders
            ADD CONSTRAINT fk_orders_customer
            FOREIGN KEY (customer_id) REFERENCES {schema}.customers(id);
    END IF;
END $$;
