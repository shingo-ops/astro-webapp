-- Phase 1-B-2 Step 5c-3 follow-up / Migration 034:
-- _customer_migration_map.new_contact_id に UNIQUE 制約を追加する。
--
-- 経緯:
--   PR #147 review F3 で指摘された「resolver の `.first()` が非決定的になる」問題への対応。
--   `customer_resolver.resolve_customer_id` は new_contact_id から逆引きするとき
--   `WHERE new_contact_id = :cid` の結果を `.first()` で 1 行だけ採用するが、
--   migration script の慣習で 1:1 になっているだけで DB 制約では保証されていなかった。
--   manual_merge / manual_override / 将来の手動再マッピングで誰かが
--   1 contact に 2 customers を紐づけると resolver が偶然先に並んだ row を返してしまい、
--   audit log / invoice 連携 / dashboard 集計が silent にずれる。
--
-- 本 migration の責務:
--   1. 全 tenant_NNN スキーマの _customer_migration_map に new_contact_id 重複が無いことを確認
--   2. 重複がある場合は WARNING を出して当該スキーマでの UNIQUE 追加をスキップ
--      （migration 013 と同じ defensive な慣習。手動で重複解消してから再実行）
--   3. 重複が無いスキーマでは ADD CONSTRAINT uniq_new_contact_id UNIQUE (new_contact_id) を追加
--
-- 効果:
--   以後、同一 new_contact_id に複数 customer を紐づけようとすると INSERT/UPDATE で
--   IntegrityError になる。resolver の `.first()` の非決定性は DB レベルで構造的に解消される。
--   既存の idx_cmm_new_contact_id（migration 031 で作成）は UNIQUE 制約が暗黙で
--   作る INDEX と被るため、UNIQUE 追加後に削除する（idempotent）。
--
-- 冪等性:
--   - pg_constraint で UNIQUE 制約存在チェック → 重複追加なし
--   - DROP INDEX IF EXISTS で旧 INDEX を削除
--   - 重複データがある場合は SKIP（再実行時に手動解消後に追加可能）
--
-- 依存: migration 031（_customer_migration_map 存在）
--
-- 作成日: 2026-04-27

DO $$
DECLARE
    schema_rec RECORD;
    duplicate_count INTEGER;
    applied_new INTEGER := 0;          -- 今回新規に UNIQUE 制約を追加した件数
    skipped_existing INTEGER := 0;     -- 既に UNIQUE 制約が存在し no-op だった件数
    skipped_duplicate INTEGER := 0;    -- 重複データがあり追加できなかった件数
BEGIN
    FOR schema_rec IN
        SELECT nspname FROM pg_namespace
        WHERE nspname ~ '^tenant_\d+$'
        ORDER BY nspname
    LOOP
        -- 前提: _customer_migration_map が存在すること
        IF NOT EXISTS (
            SELECT 1 FROM pg_tables
            WHERE schemaname = schema_rec.nspname
              AND tablename = '_customer_migration_map'
        ) THEN
            CONTINUE;
        END IF;

        -- 既に UNIQUE 制約があるなら何もしない（再実行 no-op）
        IF EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'uniq_cmm_new_contact_id'
              AND connamespace = (
                  SELECT oid FROM pg_namespace WHERE nspname = schema_rec.nspname
              )
        ) THEN
            RAISE NOTICE 'migration 034: %: uniq_cmm_new_contact_id 既に存在、skip',
                schema_rec.nspname;
            skipped_existing := skipped_existing + 1;
            CONTINUE;
        END IF;

        -- new_contact_id 重複の事前チェック
        EXECUTE format($q$
            SELECT COUNT(*) FROM (
                SELECT new_contact_id
                FROM %I._customer_migration_map
                GROUP BY new_contact_id
                HAVING COUNT(*) > 1
            ) dup
        $q$, schema_rec.nspname) INTO duplicate_count;

        IF duplicate_count > 0 THEN
            RAISE WARNING
                'migration 034: %: _customer_migration_map に new_contact_id 重複が % 件あります。'
                ' UNIQUE 制約の追加をスキップします。'
                ' 手動で重複を解消してから本 migration を再実行してください。'
                ' 検出 SQL: SELECT new_contact_id, array_agg(old_customer_id), COUNT(*)'
                ' FROM %I._customer_migration_map GROUP BY new_contact_id HAVING COUNT(*) > 1;',
                schema_rec.nspname, duplicate_count, schema_rec.nspname;
            skipped_duplicate := skipped_duplicate + 1;
            CONTINUE;
        END IF;

        -- UNIQUE 制約を追加
        EXECUTE format(
            'ALTER TABLE %I._customer_migration_map'
            ' ADD CONSTRAINT uniq_cmm_new_contact_id UNIQUE (new_contact_id)',
            schema_rec.nspname
        );

        -- migration 031 で作成された非ユニーク INDEX は不要（UNIQUE 制約が暗黙で
        -- INDEX を作るため）。重複は明示的に削除して PostgreSQL の最適化を妨げない
        EXECUTE format(
            'DROP INDEX IF EXISTS %I.idx_cmm_new_contact_id',
            schema_rec.nspname
        );

        applied_new := applied_new + 1;
        RAISE NOTICE 'migration 034: %: uniq_cmm_new_contact_id 追加完了',
            schema_rec.nspname;
    END LOOP;
    -- 完了サマリ。VPS 適用ログを grep で判定する場合に区別できるよう 3 バケツに分離。
    -- (PR #150 review M2)
    RAISE NOTICE 'migration 034: 完了。新規追加 % テナント、既存検出 % テナント、重複SKIP % テナント',
        applied_new, skipped_existing, skipped_duplicate;
END $$;

-- =====================================================================
-- Rollback 手順（緊急時のみ手動実行）:
--
-- DO $$
-- DECLARE
--     r RECORD;
-- BEGIN
--     FOR r IN SELECT nspname FROM pg_namespace WHERE nspname ~ '^tenant_\d+$'
--     LOOP
--         -- UNIQUE 制約を削除
--         EXECUTE format(
--             'ALTER TABLE %I._customer_migration_map'
--             ' DROP CONSTRAINT IF EXISTS uniq_cmm_new_contact_id',
--             r.nspname
--         );
--         -- 元の非ユニーク INDEX を復元（migration 031 と同じ）
--         EXECUTE format(
--             'CREATE INDEX IF NOT EXISTS idx_cmm_new_contact_id'
--             ' ON %I._customer_migration_map (new_contact_id)',
--             r.nspname
--         );
--     END LOOP;
-- END $$;
-- =====================================================================
