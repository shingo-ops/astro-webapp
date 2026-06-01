-- Migration 20260601_140000: customers 関連テーブルを全テナントから DROP（ADR-089 最終）
--
-- 目的:
--   ADR-089 Sprint 1–7 で全 API・ORM・UI を companies に移行完了。
--   migration 097/098 で company_discord 新設・customer_discord データ移行済み。
--   本 migration で customers および関連副テーブルを全テナントから削除する。
--
-- 廃止対象テーブル（テナントスキーマ内）:
--   - customers
--   - customer_addresses
--   - customer_discord
--   - customer_sales_channels
--   - customer_contact_channels
--   - customers_legacy_{schema_name}（migration 015 で退避された旧データ）
--
-- 前提条件:
--   - migration 097: company_discord テーブル新設済み
--   - migration 098: customer_discord データを company_discord へ移行済み
--   - customers API・ORM（customers.py）は Sprint 1–7 で廃止済み
--
-- 安全弁:
--   - 各テーブルは IF EXISTS で DROP（テーブルがなくてもエラーにならない）
--   - customer_discord が移行漏れの場合は RAISE WARNING を出してスキップ
-- 適用対象: 全テナント（pg_namespace 走査）
-- 冪等: DROP TABLE IF EXISTS

DO $$
DECLARE
    schema_rec RECORD;
    unmapped_count INTEGER;
    dropped_count INTEGER := 0;
BEGIN
    FOR schema_rec IN
        SELECT nspname FROM pg_namespace
        WHERE nspname ~ '^tenant_\d+$'
        ORDER BY nspname
    LOOP
        -- customers テーブルが存在しないテナントはスキップ（既に DROP 済み）
        IF NOT EXISTS (
            SELECT 1 FROM pg_tables
            WHERE schemaname = schema_rec.nspname AND tablename = 'customers'
        ) THEN
            RAISE NOTICE 'migration drop_customers: %: customers テーブルが存在しないためスキップ', schema_rec.nspname;
            CONTINUE;
        END IF;

        -- customer_discord のデータ移行漏れチェック
        IF EXISTS (
            SELECT 1 FROM pg_tables
            WHERE schemaname = schema_rec.nspname AND tablename = 'customer_discord'
        ) THEN
            EXECUTE format(
                'SELECT COUNT(*) FROM %I.customer_discord cd '
                'WHERE NOT EXISTS (SELECT 1 FROM %I.company_discord cpd WHERE cpd.company_id = ('
                '  SELECT c.id FROM %I.companies c '
                '  JOIN %I.customers cu ON LOWER(TRIM(cu.company_name)) = LOWER(TRIM(c.name)) '
                '  WHERE cu.id = cd.customer_id LIMIT 1'
                '))',
                schema_rec.nspname, schema_rec.nspname, schema_rec.nspname, schema_rec.nspname
            ) INTO unmapped_count;

            IF unmapped_count > 0 THEN
                RAISE WARNING 'migration drop_customers: %: customer_discord に % 件の移行漏れがあります。migration 098 を先に再実行してください。このテナントをスキップします。',
                    schema_rec.nspname, unmapped_count;
                CONTINUE;
            END IF;
        END IF;

        -- customer_contact_channels DROP（migration 026 で追加、Sprint 5 で ORM 削除済み）
        EXECUTE format('DROP TABLE IF EXISTS %I.customer_contact_channels CASCADE', schema_rec.nspname);

        -- customer_sales_channels DROP
        EXECUTE format('DROP TABLE IF EXISTS %I.customer_sales_channels CASCADE', schema_rec.nspname);

        -- customer_discord DROP（データは company_discord に移行済み）
        EXECUTE format('DROP TABLE IF EXISTS %I.customer_discord CASCADE', schema_rec.nspname);

        -- customer_addresses DROP
        EXECUTE format('DROP TABLE IF EXISTS %I.customer_addresses CASCADE', schema_rec.nspname);

        -- customers_legacy DROP（migration 015 で退避された旧データ）
        EXECUTE format('DROP TABLE IF EXISTS %I.customers_legacy_%s CASCADE',
            schema_rec.nspname, schema_rec.nspname);

        -- customers DROP（最後に削除：他テーブルが FK を持つため CASCADE で安全に削除）
        EXECUTE format('DROP TABLE IF EXISTS %I.customers CASCADE', schema_rec.nspname);

        dropped_count := dropped_count + 1;
        RAISE NOTICE 'migration drop_customers: %: customers 関連テーブルを DROP しました', schema_rec.nspname;
    END LOOP;

    RAISE NOTICE 'migration drop_customers: 完了 — % テナントから customers 関連テーブルを削除', dropped_count;
END $$;
