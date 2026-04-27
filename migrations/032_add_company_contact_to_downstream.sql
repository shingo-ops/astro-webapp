-- Phase 1-B-2 Step 4 / Migration 032: 下流テーブル (deals/orders/quotes/invoices) に
-- company_id + contact_id カラム追加 + _customer_migration_map からの backfill + FK。
--
-- 本 migration の責務:
--   1. ALTER TABLE ADD COLUMN IF NOT EXISTS company_id / contact_id（nullable）
--   2. 既存行を _customer_migration_map 経由で backfill（company_id IS NULL の行のみ）
--   3. FK 制約を追加（nullable のまま、Step 5 まで customer_id と両立）
--
-- 非破壊:
--   - customer_id 列は一切触らない（Step 5 で drop）
--   - routers/schemas も本 migration では変更しない
--   - UI も変更なし（既存の顧客 selector は引き続き customer_id で動く）
--
-- 冪等:
--   - ADD COLUMN IF NOT EXISTS + UPDATE ... WHERE company_id IS NULL
--   - pg_constraint NOT EXISTS 判定で FK 重複追加を回避
--   - 再実行で no-op
--   - **post-035 状態（customer_id 列 DROP 済）でも安全**:
--     UPDATE 文を pg_attribute チェックで guard し、列が無ければ skip
--
-- 依存: migration 028-031（companies/contacts/_customer_migration_map 存在）
--
-- 作成日: 2026-04-24
-- 改修日: 2026-04-27（post-035 hotfix: customer_id 列削除後の冪等性保証）

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
        -- 前提: companies/contacts/_customer_migration_map が存在すること
        IF NOT EXISTS (
            SELECT 1 FROM pg_tables
            WHERE schemaname = schema_rec.nspname AND tablename = 'companies'
        ) OR NOT EXISTS (
            SELECT 1 FROM pg_tables
            WHERE schemaname = schema_rec.nspname AND tablename = '_customer_migration_map'
        ) THEN
            RAISE NOTICE 'migration 032: %: companies/_customer_migration_map が未作成、skip', schema_rec.nspname;
            CONTINUE;
        END IF;

        -- deals/orders/quotes/invoices が存在するスキーマのみ処理
        IF NOT EXISTS (
            SELECT 1 FROM pg_tables
            WHERE schemaname = schema_rec.nspname AND tablename = 'deals'
        ) THEN
            CONTINUE;
        END IF;

        -- =========================================================
        -- 1) deals
        -- =========================================================
        EXECUTE format('ALTER TABLE %I.deals ADD COLUMN IF NOT EXISTS company_id INTEGER', schema_rec.nspname);
        EXECUTE format('ALTER TABLE %I.deals ADD COLUMN IF NOT EXISTS contact_id INTEGER', schema_rec.nspname);

        -- backfill（company_id IS NULL の行のみ、再実行しても変化なし）
        -- post-035 状態では customer_id 列が無いので skip（後方互換 hotfix 2026-04-27）
        IF EXISTS (
            SELECT 1 FROM pg_attribute a
            JOIN pg_class c ON c.oid = a.attrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = schema_rec.nspname
              AND c.relname = 'deals' AND a.attname = 'customer_id'
              AND NOT a.attisdropped
        ) THEN
            EXECUTE format($q$
                UPDATE %I.deals d
                SET company_id = m.new_company_id,
                    contact_id = m.new_contact_id
                FROM %I._customer_migration_map m
                WHERE d.customer_id = m.old_customer_id
                  AND d.company_id IS NULL
            $q$, schema_rec.nspname, schema_rec.nspname);
        END IF;

        -- FK 追加（NOT EXISTS で idempotent）
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'fk_deals_company'
              AND connamespace = (SELECT oid FROM pg_namespace WHERE nspname = schema_rec.nspname)
        ) THEN
            EXECUTE format(
                'ALTER TABLE %I.deals ADD CONSTRAINT fk_deals_company FOREIGN KEY (company_id) REFERENCES %I.companies(id)',
                schema_rec.nspname, schema_rec.nspname
            );
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'fk_deals_contact'
              AND connamespace = (SELECT oid FROM pg_namespace WHERE nspname = schema_rec.nspname)
        ) THEN
            EXECUTE format(
                'ALTER TABLE %I.deals ADD CONSTRAINT fk_deals_contact FOREIGN KEY (contact_id) REFERENCES %I.contacts(id)',
                schema_rec.nspname, schema_rec.nspname
            );
        END IF;

        EXECUTE format('CREATE INDEX IF NOT EXISTS idx_deals_company_id ON %I.deals (company_id)', schema_rec.nspname);
        EXECUTE format('CREATE INDEX IF NOT EXISTS idx_deals_contact_id ON %I.deals (contact_id)', schema_rec.nspname);

        -- =========================================================
        -- 2) orders
        -- =========================================================
        IF EXISTS (SELECT 1 FROM pg_tables WHERE schemaname = schema_rec.nspname AND tablename = 'orders') THEN
            EXECUTE format('ALTER TABLE %I.orders ADD COLUMN IF NOT EXISTS company_id INTEGER', schema_rec.nspname);
            EXECUTE format('ALTER TABLE %I.orders ADD COLUMN IF NOT EXISTS contact_id INTEGER', schema_rec.nspname);

            -- post-035 状態では customer_id 列が無いので skip
            IF EXISTS (
                SELECT 1 FROM pg_attribute a
                JOIN pg_class c ON c.oid = a.attrelid
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = schema_rec.nspname
                  AND c.relname = 'orders' AND a.attname = 'customer_id'
                  AND NOT a.attisdropped
            ) THEN
                EXECUTE format($q$
                    UPDATE %I.orders o
                    SET company_id = m.new_company_id,
                        contact_id = m.new_contact_id
                    FROM %I._customer_migration_map m
                    WHERE o.customer_id = m.old_customer_id
                      AND o.company_id IS NULL
                $q$, schema_rec.nspname, schema_rec.nspname);
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'fk_orders_company'
                  AND connamespace = (SELECT oid FROM pg_namespace WHERE nspname = schema_rec.nspname)
            ) THEN
                EXECUTE format(
                    'ALTER TABLE %I.orders ADD CONSTRAINT fk_orders_company FOREIGN KEY (company_id) REFERENCES %I.companies(id)',
                    schema_rec.nspname, schema_rec.nspname
                );
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'fk_orders_contact'
                  AND connamespace = (SELECT oid FROM pg_namespace WHERE nspname = schema_rec.nspname)
            ) THEN
                EXECUTE format(
                    'ALTER TABLE %I.orders ADD CONSTRAINT fk_orders_contact FOREIGN KEY (contact_id) REFERENCES %I.contacts(id)',
                    schema_rec.nspname, schema_rec.nspname
                );
            END IF;

            EXECUTE format('CREATE INDEX IF NOT EXISTS idx_orders_company_id ON %I.orders (company_id)', schema_rec.nspname);
            EXECUTE format('CREATE INDEX IF NOT EXISTS idx_orders_contact_id ON %I.orders (contact_id)', schema_rec.nspname);
        END IF;

        -- =========================================================
        -- 3) quotes
        -- =========================================================
        IF EXISTS (SELECT 1 FROM pg_tables WHERE schemaname = schema_rec.nspname AND tablename = 'quotes') THEN
            EXECUTE format('ALTER TABLE %I.quotes ADD COLUMN IF NOT EXISTS company_id INTEGER', schema_rec.nspname);
            EXECUTE format('ALTER TABLE %I.quotes ADD COLUMN IF NOT EXISTS contact_id INTEGER', schema_rec.nspname);

            -- post-035 状態では customer_id 列が無いので skip
            IF EXISTS (
                SELECT 1 FROM pg_attribute a
                JOIN pg_class c ON c.oid = a.attrelid
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = schema_rec.nspname
                  AND c.relname = 'quotes' AND a.attname = 'customer_id'
                  AND NOT a.attisdropped
            ) THEN
                EXECUTE format($q$
                    UPDATE %I.quotes q
                    SET company_id = m.new_company_id,
                        contact_id = m.new_contact_id
                    FROM %I._customer_migration_map m
                    WHERE q.customer_id = m.old_customer_id
                      AND q.company_id IS NULL
                $q$, schema_rec.nspname, schema_rec.nspname);
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'fk_quotes_company'
                  AND connamespace = (SELECT oid FROM pg_namespace WHERE nspname = schema_rec.nspname)
            ) THEN
                EXECUTE format(
                    'ALTER TABLE %I.quotes ADD CONSTRAINT fk_quotes_company FOREIGN KEY (company_id) REFERENCES %I.companies(id)',
                    schema_rec.nspname, schema_rec.nspname
                );
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'fk_quotes_contact'
                  AND connamespace = (SELECT oid FROM pg_namespace WHERE nspname = schema_rec.nspname)
            ) THEN
                EXECUTE format(
                    'ALTER TABLE %I.quotes ADD CONSTRAINT fk_quotes_contact FOREIGN KEY (contact_id) REFERENCES %I.contacts(id)',
                    schema_rec.nspname, schema_rec.nspname
                );
            END IF;

            EXECUTE format('CREATE INDEX IF NOT EXISTS idx_quotes_company_id ON %I.quotes (company_id)', schema_rec.nspname);
            EXECUTE format('CREATE INDEX IF NOT EXISTS idx_quotes_contact_id ON %I.quotes (contact_id)', schema_rec.nspname);
        END IF;

        -- =========================================================
        -- 4) invoices
        -- =========================================================
        IF EXISTS (SELECT 1 FROM pg_tables WHERE schemaname = schema_rec.nspname AND tablename = 'invoices') THEN
            EXECUTE format('ALTER TABLE %I.invoices ADD COLUMN IF NOT EXISTS company_id INTEGER', schema_rec.nspname);
            EXECUTE format('ALTER TABLE %I.invoices ADD COLUMN IF NOT EXISTS contact_id INTEGER', schema_rec.nspname);

            -- post-035 状態では customer_id 列が無いので skip
            IF EXISTS (
                SELECT 1 FROM pg_attribute a
                JOIN pg_class c ON c.oid = a.attrelid
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = schema_rec.nspname
                  AND c.relname = 'invoices' AND a.attname = 'customer_id'
                  AND NOT a.attisdropped
            ) THEN
                EXECUTE format($q$
                    UPDATE %I.invoices i
                    SET company_id = m.new_company_id,
                        contact_id = m.new_contact_id
                    FROM %I._customer_migration_map m
                    WHERE i.customer_id = m.old_customer_id
                      AND i.company_id IS NULL
                $q$, schema_rec.nspname, schema_rec.nspname);
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'fk_invoices_company'
                  AND connamespace = (SELECT oid FROM pg_namespace WHERE nspname = schema_rec.nspname)
            ) THEN
                EXECUTE format(
                    'ALTER TABLE %I.invoices ADD CONSTRAINT fk_invoices_company FOREIGN KEY (company_id) REFERENCES %I.companies(id)',
                    schema_rec.nspname, schema_rec.nspname
                );
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'fk_invoices_contact'
                  AND connamespace = (SELECT oid FROM pg_namespace WHERE nspname = schema_rec.nspname)
            ) THEN
                EXECUTE format(
                    'ALTER TABLE %I.invoices ADD CONSTRAINT fk_invoices_contact FOREIGN KEY (contact_id) REFERENCES %I.contacts(id)',
                    schema_rec.nspname, schema_rec.nspname
                );
            END IF;

            EXECUTE format('CREATE INDEX IF NOT EXISTS idx_invoices_company_id ON %I.invoices (company_id)', schema_rec.nspname);
            EXECUTE format('CREATE INDEX IF NOT EXISTS idx_invoices_contact_id ON %I.invoices (contact_id)', schema_rec.nspname);
        END IF;

        applied_count := applied_count + 1;
        RAISE NOTICE 'migration 032: %: 下流 FK 切替適用完了', schema_rec.nspname;
    END LOOP;
    RAISE NOTICE 'migration 032: 全 % テナントに下流 FK を適用', applied_count;
END $$;
