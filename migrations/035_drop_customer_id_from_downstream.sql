-- Phase 1-B-2 Step 5d / Migration 035 (DRAFT — NOT YET APPLIED):
-- 下流テーブル (deals/orders/quotes/invoices) から旧 customer_id 列を完全撤去する。
--
-- 経緯:
--   migration 031-034 で _customer_migration_map / company_id / contact_id を導入し、
--   Step 5c-3 (PR #147) で backend は contact_id ベースに切り替え済み。
--   本番 4 テナントで company_id IS NOT NULL かつ FK 整合性 OK が確認済み。
--   本 migration 035 で旧経路を「永久に閉じる」。
--
-- 本 migration の責務:
--   1. precondition: 下流テーブルの全行で company_id IS NOT NULL であることを確認
--      （違反があれば FAIL。033 と同じ defensive な作法）
--   2. company_id を NOT NULL 化（deals/orders は元々 nullable、quotes/invoices は元々 NOT NULL）
--   3. customer_id 列を DROP（FK 制約と暗黙 INDEX も連動して消える）
--   4. _customer_migration_map テーブルを DROP（resolver 撤去とセット）
--      ※ 037 など別 migration に分けることも検討（FU-2 / round 2 でも 037 提案あり）
--
-- 破壊的:
--   - customer_id 列を物理削除する。rollback には DOWN migration（末尾のコメント）が必要。
--   - audit_logs の new_data / old_data に過去の customer_id 値が残るが JSON テキストなので影響なし。
--
-- 冪等:
--   - DROP COLUMN IF EXISTS / DROP TABLE IF EXISTS で再実行 no-op
--   - precondition チェックは「列が既に DROP 済み」なら skip して進む
--
-- 依存:
--   - migration 028-034 すべて適用済み
--   - backend / frontend で customer_id を書き込む経路が完全に閉じていること（PR #1XX で別途切替）
--
-- 想定適用順序（重要）:
--   1) backend / frontend から customer_id 経路を削除した PR を main マージ → 本番反映
--   2) 本番 VPS で `astro-webapp/scripts/preflight_step5d.sh` を実行（後述）
--   3) 全テナントで preflight が PASS したら、本 migration 035 を適用
--
-- 作成日: 2026-04-27 (DRAFT)

DO $$
DECLARE
    schema_rec RECORD;
    bad_count INTEGER;
    failed_schemas TEXT := '';
BEGIN
    -- =========================================================
    -- precondition phase: 全テナントで company_id IS NOT NULL を確認
    -- =========================================================
    FOR schema_rec IN
        SELECT nspname FROM pg_namespace
        WHERE nspname ~ '^tenant_\d+$'
        ORDER BY nspname
    LOOP
        -- deals
        IF EXISTS (
            SELECT 1 FROM pg_attribute a
            JOIN pg_class c ON c.oid = a.attrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = schema_rec.nspname
              AND c.relname = 'deals' AND a.attname = 'customer_id'
              AND NOT a.attisdropped
        ) THEN
            EXECUTE format(
                'SELECT COUNT(*) FROM %I.deals WHERE company_id IS NULL',
                schema_rec.nspname
            ) INTO bad_count;
            IF bad_count > 0 THEN
                failed_schemas := failed_schemas || format(' %s.deals=%s', schema_rec.nspname, bad_count);
            END IF;
        END IF;

        -- orders
        IF EXISTS (
            SELECT 1 FROM pg_attribute a
            JOIN pg_class c ON c.oid = a.attrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = schema_rec.nspname
              AND c.relname = 'orders' AND a.attname = 'customer_id'
              AND NOT a.attisdropped
        ) THEN
            EXECUTE format(
                'SELECT COUNT(*) FROM %I.orders WHERE company_id IS NULL',
                schema_rec.nspname
            ) INTO bad_count;
            IF bad_count > 0 THEN
                failed_schemas := failed_schemas || format(' %s.orders=%s', schema_rec.nspname, bad_count);
            END IF;
        END IF;

        -- quotes
        IF EXISTS (
            SELECT 1 FROM pg_tables
            WHERE schemaname = schema_rec.nspname AND tablename = 'quotes'
        ) AND EXISTS (
            SELECT 1 FROM pg_attribute a
            JOIN pg_class c ON c.oid = a.attrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = schema_rec.nspname
              AND c.relname = 'quotes' AND a.attname = 'customer_id'
              AND NOT a.attisdropped
        ) THEN
            EXECUTE format(
                'SELECT COUNT(*) FROM %I.quotes WHERE company_id IS NULL',
                schema_rec.nspname
            ) INTO bad_count;
            IF bad_count > 0 THEN
                failed_schemas := failed_schemas || format(' %s.quotes=%s', schema_rec.nspname, bad_count);
            END IF;
        END IF;

        -- invoices
        IF EXISTS (
            SELECT 1 FROM pg_tables
            WHERE schemaname = schema_rec.nspname AND tablename = 'invoices'
        ) AND EXISTS (
            SELECT 1 FROM pg_attribute a
            JOIN pg_class c ON c.oid = a.attrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = schema_rec.nspname
              AND c.relname = 'invoices' AND a.attname = 'customer_id'
              AND NOT a.attisdropped
        ) THEN
            EXECUTE format(
                'SELECT COUNT(*) FROM %I.invoices WHERE company_id IS NULL',
                schema_rec.nspname
            ) INTO bad_count;
            IF bad_count > 0 THEN
                failed_schemas := failed_schemas || format(' %s.invoices=%s', schema_rec.nspname, bad_count);
            END IF;
        END IF;
    END LOOP;

    IF length(failed_schemas) > 0 THEN
        RAISE EXCEPTION
            'migration 035: precondition 違反: company_id IS NULL の行が残っています:%s。'
            ' migration 032 の backfill が完了しているか確認してください。',
            failed_schemas;
    END IF;
    RAISE NOTICE 'migration 035: precondition PASS（全テナントで company_id IS NULL の行なし）';
END $$;

-- =========================================================
-- main phase: customer_id 列の DROP
-- =========================================================
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
        -- deals
        IF EXISTS (
            SELECT 1 FROM pg_tables WHERE schemaname = schema_rec.nspname AND tablename = 'deals'
        ) THEN
            -- company_id を NOT NULL に昇格（既に NOT NULL なら no-op）
            EXECUTE format('ALTER TABLE %I.deals ALTER COLUMN company_id SET NOT NULL', schema_rec.nspname);
            -- customer_id 列を DROP（依存 FK / INDEX も連動）
            EXECUTE format('ALTER TABLE %I.deals DROP COLUMN IF EXISTS customer_id', schema_rec.nspname);
        END IF;

        -- orders
        IF EXISTS (
            SELECT 1 FROM pg_tables WHERE schemaname = schema_rec.nspname AND tablename = 'orders'
        ) THEN
            EXECUTE format('ALTER TABLE %I.orders ALTER COLUMN company_id SET NOT NULL', schema_rec.nspname);
            EXECUTE format('ALTER TABLE %I.orders DROP COLUMN IF EXISTS customer_id', schema_rec.nspname);
        END IF;

        -- quotes
        IF EXISTS (
            SELECT 1 FROM pg_tables WHERE schemaname = schema_rec.nspname AND tablename = 'quotes'
        ) THEN
            EXECUTE format('ALTER TABLE %I.quotes ALTER COLUMN company_id SET NOT NULL', schema_rec.nspname);
            EXECUTE format('ALTER TABLE %I.quotes DROP COLUMN IF EXISTS customer_id', schema_rec.nspname);
        END IF;

        -- invoices
        IF EXISTS (
            SELECT 1 FROM pg_tables WHERE schemaname = schema_rec.nspname AND tablename = 'invoices'
        ) THEN
            EXECUTE format('ALTER TABLE %I.invoices ALTER COLUMN company_id SET NOT NULL', schema_rec.nspname);
            EXECUTE format('ALTER TABLE %I.invoices DROP COLUMN IF EXISTS customer_id', schema_rec.nspname);
        END IF;

        applied_count := applied_count + 1;
        RAISE NOTICE 'migration 035: %: customer_id DROP 完了', schema_rec.nspname;
    END LOOP;
    RAISE NOTICE 'migration 035: 全 % テナントで customer_id 列を物理削除', applied_count;
END $$;

-- =====================================================================
-- DOWN migration（緊急時のみ手動実行 / 推奨はバックアップから restore）:
--
-- ⚠ customer_id 値は失われているため、復活させても全行 NULL になる。
--   Step 5d 適用後の rollback では「列の存在だけ」復活し、データは戻らない。
--   pg_dump バックアップから restore するのが正攻法。
--
-- DO $$
-- DECLARE
--     r RECORD;
-- BEGIN
--     FOR r IN SELECT nspname FROM pg_namespace WHERE nspname ~ '^tenant_\d+$'
--     LOOP
--         IF EXISTS (SELECT 1 FROM pg_tables WHERE schemaname = r.nspname AND tablename = 'deals') THEN
--             EXECUTE format('ALTER TABLE %I.deals ADD COLUMN IF NOT EXISTS customer_id INTEGER REFERENCES %I.customers(id)',
--                 r.nspname, r.nspname);
--             EXECUTE format('ALTER TABLE %I.deals ALTER COLUMN company_id DROP NOT NULL', r.nspname);
--             -- customer_id 値を _customer_migration_map から復元（migration 036 で削除済みの場合は不可）
--             -- EXECUTE format('UPDATE %I.deals d SET customer_id = m.old_customer_id FROM %I._customer_migration_map m'
--             --     ' WHERE d.contact_id = m.new_contact_id', r.nspname, r.nspname);
--         END IF;
--         -- orders / quotes / invoices も同様
--     END LOOP;
-- END $$;
-- =====================================================================
