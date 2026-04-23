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
-- Phase 1 再設計 / Migration 022: staff / staff_emails / staff_ui_preferences / bots の RLS
--
-- 内容:
--   - staff 本体 / bots 本体: tenant_id 列で直接分離
--   - staff_emails / staff_ui_preferences: staff を経由して分離
--   - 新関数 public.current_tenant_id() を使用
--
-- 前提:
--   - 014 で public.current_tenant_id() 定義済
--   - 019 で staff 系、020 で bots 作成済
--
-- 変更履歴:
--   2026-04-23: 初版作成（Phase 1 再設計）

ALTER TABLE {schema}.staff ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.staff_emails ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.staff_ui_preferences ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.bots ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    -- 本体: tenant_id 列で直接分離
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE policyname = 'tenant_isolation_staff'
          AND schemaname = '{schema_raw}'
    ) THEN
        CREATE POLICY tenant_isolation_staff ON {schema}.staff
            USING (tenant_id = public.current_tenant_id());
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE policyname = 'tenant_isolation_bots'
          AND schemaname = '{schema_raw}'
    ) THEN
        CREATE POLICY tenant_isolation_bots ON {schema}.bots
            USING (tenant_id = public.current_tenant_id());
    END IF;

    -- 副テーブル: staff を経由して分離
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE policyname = 'tenant_isolation_staff_emails'
          AND schemaname = '{schema_raw}'
    ) THEN
        CREATE POLICY tenant_isolation_staff_emails ON {schema}.staff_emails
            USING (EXISTS (
                SELECT 1 FROM {schema}.staff s
                WHERE s.id = staff_emails.staff_id
                  AND s.tenant_id = public.current_tenant_id()
            ));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE policyname = 'tenant_isolation_staff_ui_preferences'
          AND schemaname = '{schema_raw}'
    ) THEN
        CREATE POLICY tenant_isolation_staff_ui_preferences ON {schema}.staff_ui_preferences
            USING (EXISTS (
                SELECT 1 FROM {schema}.staff s
                WHERE s.id = staff_ui_preferences.staff_id
                  AND s.tenant_id = public.current_tenant_id()
            ));
    END IF;
END $$;
