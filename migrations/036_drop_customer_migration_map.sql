-- Phase 1-B-2 Step 5d / Migration 036 (DRAFT — NOT YET APPLIED):
-- _customer_migration_map テーブルを完全撤去する。
--
-- 本 migration の責務:
--   1. 035 で customer_id 列が完全に消えたことを確認（precondition）
--   2. _customer_migration_map テーブルを DROP
--   3. tenant.py 側のブロックは別 PR でコード削除（本 SQL では関与しない）
--
-- 035 と分離する理由:
--   - 035 適用直後に問題発覚した場合、_customer_migration_map が残っていれば
--     DOWN migration のヒント（contact_id → 旧 customer_id 値）として使える。
--   - 035 が一定期間（例: 1 週間）安定稼働してから 036 を流すと、
--     「列を戻したいときに値も戻せる」最終保険を保てる。
--
-- 破壊的:
--   - _customer_migration_map のデータを物理削除する。再生成不可（原本 = 削除済 customers の id）。
--
-- 冪等:
--   - DROP TABLE IF EXISTS で再実行 no-op
--
-- 依存:
--   - migration 035 適用済み
--   - customer_resolver.py が backend から削除済み（コード経由の参照が完全に閉じている）
--
-- 作成日: 2026-04-27 (DRAFT)

DO $$
DECLARE
    schema_rec RECORD;
    bad_schemas TEXT := '';
BEGIN
    -- precondition: customer_id 列が存在しないことを確認
    FOR schema_rec IN
        SELECT nspname FROM pg_namespace
        WHERE nspname ~ '^tenant_\d+$'
        ORDER BY nspname
    LOOP
        FOR bad_schemas IN
            SELECT format('%s.%s', schema_rec.nspname, c.relname)
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            JOIN pg_attribute a ON a.attrelid = c.oid
            WHERE n.nspname = schema_rec.nspname
              AND c.relname IN ('deals','orders','quotes','invoices')
              AND a.attname = 'customer_id'
              AND NOT a.attisdropped
            LIMIT 1
        LOOP
            RAISE EXCEPTION
                'migration 036: precondition 違反: % にまだ customer_id 列が残っています。'
                ' 先に migration 035 を適用してください。',
                bad_schemas;
        END LOOP;
    END LOOP;

    -- _customer_migration_map を DROP
    FOR schema_rec IN
        SELECT nspname FROM pg_namespace
        WHERE nspname ~ '^tenant_\d+$'
        ORDER BY nspname
    LOOP
        EXECUTE format('DROP TABLE IF EXISTS %I._customer_migration_map CASCADE', schema_rec.nspname);
        RAISE NOTICE 'migration 036: %: _customer_migration_map を DROP', schema_rec.nspname;
    END LOOP;
END $$;

-- =====================================================================
-- DOWN migration（緊急時のみ手動実行）:
--   _customer_migration_map は drop されると再生成不可。
--   pg_dump バックアップから restore する以外の方法はない。
-- =====================================================================
