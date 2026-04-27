-- Phase 1-B-2 Step 5c-2 follow-up / Migration 037:
-- contacts.status の CHECK 制約に 'pending_dedup_review' を追加する。
--
-- 経緯:
--   PR #163 (PR #145 残課題 Q2: pending_dedup_review 手動解消 UI) の Reviewer round 1
--   Critical 指摘への対応。
--
--   companies.status は migration 028 / tenant.py:161 で当初から
--     CHECK (status IN ('active','inactive','archived','pending_dedup_review'))
--   と定義されているのに対し、contacts.status は migration 029 / tenant.py:271-272 で
--     CHECK (status IN ('active','inactive','archived'))
--   のままだった。PR #163 で ContactStatus enum と UI の <select> に
--   'pending_dedup_review' 選択肢を追加したため、UI から POST /contacts または
--   PATCH /contacts/{id} で status='pending_dedup_review' を送ると Pydantic は通すが
--   PostgreSQL が CheckViolationError を返し 500 になる。
--
--   smoke test (test_contacts.py) は SQLite で動いており conftest.py には
--   CHECK 制約が無いためテストは緑だが、本番 PostgreSQL では赤になる。
--
-- 本 migration の責務:
--   1. 全 tenant_NNN スキーマの contacts テーブルに対して既存の status CHECK 制約を
--      pg_constraint から動的に検出（CHECK 制約は無名で定義されており、PostgreSQL が
--      自動採番する制約名 (例: contacts_status_check) は環境依存）
--   2. 既存制約を DROP（あれば）→ 新 CHECK 制約 (pending_dedup_review 追加版) を ADD
--   3. 既に新 CHECK 制約と同等の定義になっていれば SKIP（再実行 no-op、冪等）
--
-- 効果:
--   contacts も companies と同様に pending_dedup_review を受領できる。
--   PR #163 の解消フロー UI から status を pending_dedup_review に切り替え保存しても
--   500 にならず、解消フローも正しく動く。
--
-- 冪等性:
--   - pg_get_constraintdef で既存 CHECK 制約の SQL 表現を取得し、
--     'pending_dedup_review' の有無で分岐
--   - 既に pending_dedup_review を含む CHECK 制約があれば何もしない
--   - 制約が複数ある場合（手動運用で複数 ADD された場合）は全て DROP してから 1 本に統一
--
-- 注意:
--   - 本番 contacts には 'pending_dedup_review' 行は 1 件も存在しない見込み
--     （migration script `migrate_companies_contacts_from_customers.py:591` が
--     INSERT 直前に 'active' へ昇格しているため）が、念のため本 migration は
--     既存データには触らない（CHECK 制約は新しい範囲を含むスーパーセットなので
--     既存の 'active' 'inactive' 'archived' 行は全て validate される）。
--
-- 依存: migration 029（contacts テーブル存在）
--
-- 作成日: 2026-04-27 (PR #163 Critical fix)

DO $$
DECLARE
    schema_rec RECORD;
    constraint_rec RECORD;
    existing_def TEXT;
    applied_count INTEGER := 0;          -- CHECK 制約を更新したテナント数
    skipped_already_ok INTEGER := 0;     -- 既に pending_dedup_review を含む（no-op）
    skipped_no_table INTEGER := 0;       -- contacts テーブルが無いスキーマ
BEGIN
    FOR schema_rec IN
        SELECT nspname FROM pg_namespace
        WHERE nspname ~ '^tenant_\d+$'
        ORDER BY nspname
    LOOP
        -- 前提: contacts テーブルが存在すること
        IF NOT EXISTS (
            SELECT 1 FROM pg_tables
            WHERE schemaname = schema_rec.nspname
              AND tablename = 'contacts'
        ) THEN
            skipped_no_table := skipped_no_table + 1;
            CONTINUE;
        END IF;

        -- contacts.status に紐付く CHECK 制約を全て検出する。
        --   - CHECK 制約は migration 029 で無名定義されており、PostgreSQL が
        --     contacts_status_check 等の名前を自動採番する。環境ごとに名前が
        --     ぶれる可能性があるため pg_constraint から動的に拾う。
        --   - status 列だけを参照する CHECK 制約に絞り込む（trust_level など他列の
        --     CHECK は触らない）
        --
        -- 既に pending_dedup_review を含む制約があれば（再実行 / 既に手動修正済）
        -- skip。既存制約があり pending_dedup_review を含まない場合は
        -- DROP → ADD で更新する。

        -- まず既存制約の定義をまとめて検査
        existing_def := NULL;
        FOR constraint_rec IN
            SELECT con.conname, pg_get_constraintdef(con.oid) AS def
            FROM pg_constraint con
            JOIN pg_class cls ON cls.oid = con.conrelid
            JOIN pg_namespace nsp ON nsp.oid = cls.relnamespace
            WHERE nsp.nspname = schema_rec.nspname
              AND cls.relname = 'contacts'
              AND con.contype = 'c'  -- CHECK only
              AND pg_get_constraintdef(con.oid) ILIKE '%status%'
              AND pg_get_constraintdef(con.oid) NOT ILIKE '%trust_level%'
        LOOP
            existing_def := COALESCE(existing_def, '') || constraint_rec.def || ';';

            -- 既に pending_dedup_review を含む制約があるなら更新不要（次の制約も検査）
            CONTINUE WHEN constraint_rec.def ILIKE '%pending_dedup_review%';

            -- pending_dedup_review を含まない制約は DROP（後で 1 本に統一して ADD する）
            EXECUTE format(
                'ALTER TABLE %I.contacts DROP CONSTRAINT IF EXISTS %I',
                schema_rec.nspname, constraint_rec.conname
            );
            RAISE NOTICE 'migration 037: %: 旧 CHECK 制約 % を DROP', schema_rec.nspname, constraint_rec.conname;
        END LOOP;

        -- 既に pending_dedup_review を含む CHECK 制約が「全ての既存制約」に該当すれば
        -- skip（DROP も発火していない）。判定は「定義文に pending_dedup_review が含まれる
        -- AND DROP が発火していない」≒ existing_def が NULL ではなく、かつ全制約が含む。
        --
        -- 単純化: 制約をまとめて DROP した場合は次のステップで必ず 1 本 ADD する。
        -- DROP していなくて pending_dedup_review を含むものがあるなら ADD は不要。
        --
        -- → 既に新形式 CHECK が残っているかを再検査
        IF EXISTS (
            SELECT 1 FROM pg_constraint con
            JOIN pg_class cls ON cls.oid = con.conrelid
            JOIN pg_namespace nsp ON nsp.oid = cls.relnamespace
            WHERE nsp.nspname = schema_rec.nspname
              AND cls.relname = 'contacts'
              AND con.contype = 'c'
              AND pg_get_constraintdef(con.oid) ILIKE '%status%'
              AND pg_get_constraintdef(con.oid) ILIKE '%pending_dedup_review%'
              AND pg_get_constraintdef(con.oid) NOT ILIKE '%trust_level%'
        ) THEN
            skipped_already_ok := skipped_already_ok + 1;
            RAISE NOTICE 'migration 037: %: contacts.status は既に pending_dedup_review 対応済、skip',
                schema_rec.nspname;
            CONTINUE;
        END IF;

        -- 新 CHECK 制約を ADD（'active','inactive','archived','pending_dedup_review' の 4 値）
        EXECUTE format(
            'ALTER TABLE %I.contacts ADD CONSTRAINT contacts_status_check '
            'CHECK (status IN (''active'', ''inactive'', ''archived'', ''pending_dedup_review''))',
            schema_rec.nspname
        );

        applied_count := applied_count + 1;
        RAISE NOTICE 'migration 037: %: contacts.status CHECK 制約に pending_dedup_review を追加',
            schema_rec.nspname;
    END LOOP;

    RAISE NOTICE
        'migration 037: 完了。新規追加 % テナント、既存対応済 % テナント、contacts 未存在 % テナント',
        applied_count, skipped_already_ok, skipped_no_table;
END $$;

-- =====================================================================
-- Rollback 手順（緊急時のみ手動実行）:
--
-- 注意: 既に pending_dedup_review 値を持つ contacts 行がある状態で
--       元の 3 値 CHECK に戻すと CheckViolation で ALTER 自体が失敗する。
--       事前に UPDATE contacts SET status='active' WHERE status='pending_dedup_review';
--       で値を整理してから実行すること。
--
-- DO $$
-- DECLARE
--     r RECORD;
-- BEGIN
--     FOR r IN SELECT nspname FROM pg_namespace WHERE nspname ~ '^tenant_\d+$'
--     LOOP
--         IF NOT EXISTS (
--             SELECT 1 FROM pg_tables
--             WHERE schemaname = r.nspname AND tablename = 'contacts'
--         ) THEN
--             CONTINUE;
--         END IF;
--         EXECUTE format(
--             'ALTER TABLE %I.contacts DROP CONSTRAINT IF EXISTS contacts_status_check',
--             r.nspname
--         );
--         EXECUTE format(
--             'ALTER TABLE %I.contacts ADD CONSTRAINT contacts_status_check '
--             'CHECK (status IN (''active'', ''inactive'', ''archived''))',
--             r.nspname
--         );
--     END LOOP;
-- END $$;
-- =====================================================================
