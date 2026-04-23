-- Phase 1-B-1 / Migration 027: customers.primary_contact_channel から contact_channels を backfill
--
-- 背景:
--   migration 026 で customer_contact_channels テーブルを作成した。
--   既存の customers.primary_contact_channel 値を新テーブルに移す。
--   値が null でなく contact_channels に同一 channel がまだ無い顧客のみ処理。
--
-- 冪等性:
--   WHERE NOT EXISTS で既に行がある場合はスキップ。再実行 no-op。
--
-- 変更履歴:
--   2026-04-23: 初版作成

DO $$
DECLARE
    schema_rec RECORD;
    backfilled INTEGER;
    total INTEGER := 0;
BEGIN
    FOR schema_rec IN
        SELECT nspname FROM pg_namespace
        WHERE nspname ~ '^tenant_\d+$'
        ORDER BY nspname
    LOOP
        -- customers / customer_contact_channels が両方存在するスキーマのみ
        IF NOT EXISTS (
            SELECT 1 FROM pg_tables
            WHERE schemaname = schema_rec.nspname AND tablename = 'customers'
        ) OR NOT EXISTS (
            SELECT 1 FROM pg_tables
            WHERE schemaname = schema_rec.nspname AND tablename = 'customer_contact_channels'
        ) THEN
            CONTINUE;
        END IF;

        EXECUTE format($q$
            INSERT INTO %I.customer_contact_channels (customer_id, channel, purpose, is_primary)
            SELECT
                c.id,
                c.primary_contact_channel,
                '主連絡ツール',
                TRUE
            FROM %I.customers c
            WHERE c.primary_contact_channel IS NOT NULL
              AND c.primary_contact_channel <> ''
              AND NOT EXISTS (
                  SELECT 1 FROM %I.customer_contact_channels ccc
                  WHERE ccc.customer_id = c.id AND ccc.channel = c.primary_contact_channel
              )
        $q$, schema_rec.nspname, schema_rec.nspname, schema_rec.nspname);
        GET DIAGNOSTICS backfilled = ROW_COUNT;
        IF backfilled > 0 THEN
            RAISE NOTICE 'migration 027: %: % 件を contact_channels に backfill', schema_rec.nspname, backfilled;
        END IF;
        total := total + backfilled;
    END LOOP;
    RAISE NOTICE 'migration 027: 全テナント合計 % 件を backfill', total;
END $$;
