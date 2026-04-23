-- Phase 1 再設計 / Migration 025: オーナー/システム管理者に全権限を再割当
--
-- 背景:
--   migrate_phase1.py の seed_system_roles() は初期テナント作成時に1回だけ
--   オーナーに全権限を INSERT する（SELECT id FROM public.permissions）。
--   その後 migration 018（menu.* 19件）や 024（staff.*/bots.* 8件）で
--   permissions が追加されたが、オーナー・システム管理者にはまだ紐付いていない。
--
-- 修正内容:
--   全テナントの「オーナー」「システム管理者」ロールに対して、現時点で
--   public.permissions に存在する全権限を INSERT（ON CONFLICT DO NOTHING）。
--   既存の割当は保持、不足分のみ追加される。
--
-- 冪等性:
--   ON CONFLICT (role_id, permission_id) DO NOTHING で再実行しても副作用なし。
--   DO block で pg_namespace を走査、非テンプレートのため psql 直実行可能。
--
-- 変更履歴:
--   2026-04-23: 初版作成（Phase 1 再設計 follow-up）

DO $$
DECLARE
    schema_rec RECORD;
    role_rec RECORD;
    total_inserted INTEGER := 0;
    schema_inserted INTEGER;
BEGIN
    FOR schema_rec IN
        SELECT nspname FROM pg_namespace
        WHERE nspname ~ '^tenant_\d+$'
        ORDER BY nspname
    LOOP
        -- roles / role_permissions が存在するスキーマのみ対象
        IF NOT EXISTS (
            SELECT 1 FROM pg_tables
            WHERE schemaname = schema_rec.nspname AND tablename IN ('roles', 'role_permissions')
            GROUP BY schemaname HAVING COUNT(*) = 2
        ) THEN
            CONTINUE;
        END IF;

        schema_inserted := 0;

        -- オーナー / システム管理者 の role_id を取得して全権限を割当
        FOR role_rec IN
            EXECUTE format(
                'SELECT id, name FROM %I.roles WHERE name IN (''オーナー'', ''システム管理者'')',
                schema_rec.nspname
            )
        LOOP
            EXECUTE format(
                'INSERT INTO %I.role_permissions (role_id, permission_id) '
                'SELECT %s, p.id FROM public.permissions p '
                'ON CONFLICT (role_id, permission_id) DO NOTHING',
                schema_rec.nspname, role_rec.id
            );
            GET DIAGNOSTICS schema_inserted = ROW_COUNT;
            IF schema_inserted > 0 THEN
                RAISE NOTICE 'migration 025: %: % (%s) に % 件の権限を追加',
                    schema_rec.nspname, role_rec.name, role_rec.id, schema_inserted;
            END IF;
            total_inserted := total_inserted + schema_inserted;
        END LOOP;
    END LOOP;
    RAISE NOTICE 'migration 025: 全テナント合計 % 件の権限割当を追加', total_inserted;
END $$;
