-- Phase 1 再設計 / Migration 023: システム管理者・オーナーの is_system フラグ修正
--
-- 背景:
--   Migration 021 の INSERT ... ON CONFLICT (tenant_id, name) DO NOTHING は、
--   既にテナント内に同名のロールが存在する場合、新しい値（is_system=TRUE）を
--   無視して旧値を保持する。本番 VPS の一部テナントで「システム管理者」/
--   「オーナー」が is_system=FALSE のまま残っていた。
--
-- 冪等性:
--   - 非テンプレート（{schema} プレースホルダなし）。psql 直実行可能。
--   - WHERE is_system = FALSE により既に TRUE のロールは no-op。
--   - DO ブロック内で pg_namespace を走査し、全 tenant_NNN スキーマに自動適用。
--   - 複数回実行しても副作用なし（deploy.yml で自動実行される場合も安全）。
--
-- 実行方法:
--   docker exec -i astro-webapp-postgres-1 \
--     psql -U jarvis -d jarvis_db -v ON_ERROR_STOP=1 \
--     < migrations/023_fix_system_admin_is_system_flag.sql
--
-- 変更履歴:
--   2026-04-23: 初版作成（Phase 1 再設計 軽微課題）
--   2026-04-23: 非テンプレート化（reviewer PR #99 Major 1 対応）

DO $$
DECLARE
    schema_rec RECORD;
    updated_count INTEGER;
    total_updated INTEGER := 0;
BEGIN
    FOR schema_rec IN
        SELECT nspname FROM pg_namespace
        WHERE nspname ~ '^tenant_\d+$'
        ORDER BY nspname
    LOOP
        -- roles テーブルが存在するスキーマのみ対象
        IF EXISTS (
            SELECT 1 FROM pg_tables
            WHERE schemaname = schema_rec.nspname AND tablename = 'roles'
        ) THEN
            EXECUTE format(
                'UPDATE %I.roles SET is_system = TRUE, updated_at = NOW() '
                'WHERE name IN (''オーナー'', ''システム管理者'') AND is_system = FALSE',
                schema_rec.nspname
            );
            GET DIAGNOSTICS updated_count = ROW_COUNT;
            IF updated_count > 0 THEN
                RAISE NOTICE 'migration 023: %: % 行を is_system=TRUE に更新',
                    schema_rec.nspname, updated_count;
            END IF;
            total_updated := total_updated + updated_count;
        END IF;
    END LOOP;
    RAISE NOTICE 'migration 023: 全テナント合計 % 行を更新', total_updated;
END $$;
