-- ============================================================================
-- !! テンプレート。scripts/migrate_inventory_sprint1.py 経由で全テナントに展開。
-- ============================================================================
-- Migration 063: テナント側 RBAC 拡張
--                + {tenant_xxx}.purchase_orders にテナント名義出力用列を追加
--
-- 経緯:
--   spec.md v1.1 F1 / F2 / F8:
--     - {tenant_xxx}.role_permissions に inventory.visibility.* キーを seed
--       （テナント admin が UI で「在庫を誰に見せるか」を絞れる、AC1.8 / AC2.8）
--     - {tenant_xxx}.purchase_orders に company_name_snapshot / contact_info_snapshot 列
--       追加（F8 でテナント名義出力時のスナップショット用）
--
-- 設計:
--   - public.permissions に inventory.visibility.* キー 3 件を追加（既存テナント
--     ロール（オーナー / システム管理者）に紐付ける）
--   - 既存ロール seed は migration 042 のパターンを踏襲
--   - {tenant_xxx}.purchase_orders 列追加は ALTER ... ADD COLUMN IF NOT EXISTS
--
-- ADR-034 観点: テンプレート / {tenant_xxx} 系のため全テナントループ + 新規テナント
--   テンプレートにも反映が必要（_TENANT_TABLES_SQL 連動は別ステップで判断、Sprint 1
--   では既存 deploy.yml ループに後追い同期は手動で承認）。
--
-- 関連:
--   .claude-pipeline/spec.md F1 / F2 / F8 / AC1.8 / AC2.8
--   migrations/002_add_permissions_master.sql (public.permissions 本体)
--   migrations/042_seed_meta_inbox_permissions.sql (seed パターン)
--   migrations/007_add_phase3_tenant_tables.sql (purchase_orders 本体)
--
-- 作成日: 2026-05-21
-- ============================================================================

-- === 1. public.permissions に inventory.visibility.* + tenant.inventory_visibility.edit 追加 ===
INSERT INTO public.permissions (key, resource, action, description, category) VALUES
    ('inventory.visibility.full',
        'inventory_visibility', 'view_full',
        '在庫の数量・単価・状態をすべて閲覧（営業 / オーナー想定）',
        '在庫'),
    ('inventory.visibility.staff',
        'inventory_visibility', 'view_staff',
        '在庫の品名・単価は閲覧、数量は ***マスク（経理 / 観測者想定）',
        '在庫'),
    ('inventory.visibility.viewer',
        'inventory_visibility', 'view_viewer',
        '在庫の品名のみ閲覧、単価・数量はすべて ***マスク（外部観測者想定）',
        '在庫'),
    ('tenant.inventory_visibility.edit',
        'tenant_inventory_visibility', 'edit',
        '自社内ロールに inventory.visibility.* を割り当てる（テナント admin 専用）',
        '在庫')
ON CONFLICT (key) DO NOTHING;

-- === 2. 既存テナントの「オーナー」「システム管理者」ロールに紐付け ===
-- migration 042 と同様のパターン:
--   オーナー         : ALL (inventory.visibility.full + tenant.inventory_visibility.edit)
--   システム管理者   : ALL (同上、system.manage 以外なので 2 件)
DO $rbac_perms$
DECLARE
    schema_rec RECORD;
    role_rec RECORD;
    inserted_count INTEGER;
    total_inserted INTEGER := 0;
BEGIN
    FOR schema_rec IN
        SELECT nspname FROM pg_namespace
        WHERE nspname ~ '^tenant_\d+$'
        ORDER BY nspname
    LOOP
        IF NOT EXISTS (
            SELECT 1 FROM pg_tables WHERE schemaname = schema_rec.nspname AND tablename = 'roles'
        ) OR NOT EXISTS (
            SELECT 1 FROM pg_tables WHERE schemaname = schema_rec.nspname AND tablename = 'role_permissions'
        ) THEN
            CONTINUE;
        END IF;

        FOR role_rec IN
            EXECUTE format(
                'SELECT id, name FROM %I.roles WHERE name IN (''オーナー'', ''システム管理者'')',
                schema_rec.nspname
            )
        LOOP
            EXECUTE format(
                'INSERT INTO %I.role_permissions (role_id, permission_id) '
                'SELECT %s, p.id FROM public.permissions p '
                'WHERE p.key IN (''inventory.visibility.full'', ''inventory.visibility.staff'', '
                '                ''inventory.visibility.viewer'', ''tenant.inventory_visibility.edit'') '
                'ON CONFLICT (role_id, permission_id) DO NOTHING',
                schema_rec.nspname, role_rec.id
            );
            GET DIAGNOSTICS inserted_count = ROW_COUNT;
            IF inserted_count > 0 THEN
                RAISE NOTICE 'migration 063: %: % (id=%) に % 件の inventory.visibility 権限を追加',
                    schema_rec.nspname, role_rec.name, role_rec.id, inserted_count;
            END IF;
            total_inserted := total_inserted + inserted_count;
        END LOOP;
    END LOOP;
    RAISE NOTICE 'migration 063 / RBAC: 全テナント合計 % 件の権限割当を追加', total_inserted;
END $rbac_perms$;

-- === 3. {tenant_xxx}.purchase_orders にテナント名義出力用 snapshot 列を追加 ===
DO $po_columns$
DECLARE
    schema_rec RECORD;
    applied_count INTEGER := 0;
BEGIN
    FOR schema_rec IN
        SELECT nspname FROM pg_namespace
        WHERE nspname ~ '^tenant_\d+$'
        ORDER BY nspname
    LOOP
        IF NOT EXISTS (
            SELECT 1 FROM pg_tables
            WHERE schemaname = schema_rec.nspname AND tablename = 'purchase_orders'
        ) THEN
            CONTINUE;
        END IF;

        -- F8 でテナント名義 PO PDF 出力時に「発行時点の」テナント情報を保存するため
        EXECUTE format(
            'ALTER TABLE %I.purchase_orders ADD COLUMN IF NOT EXISTS company_name_snapshot VARCHAR(255)',
            schema_rec.nspname
        );
        EXECUTE format(
            'ALTER TABLE %I.purchase_orders ADD COLUMN IF NOT EXISTS contact_info_snapshot TEXT',
            schema_rec.nspname
        );

        applied_count := applied_count + 1;
        RAISE NOTICE 'migration 063: %: purchase_orders に snapshot 列 2 件を追加',
            schema_rec.nspname;
    END LOOP;
    RAISE NOTICE 'migration 063 / purchase_orders: % テナントに snapshot 列を追加', applied_count;
END $po_columns$;

-- ============================================================================
-- Rollback（緊急時のみ手動実行）:
--
-- DO $$
-- DECLARE r RECORD;
-- BEGIN
--     FOR r IN SELECT nspname FROM pg_namespace WHERE nspname ~ '^tenant_\d+$'
--     LOOP
--         IF NOT EXISTS (SELECT 1 FROM pg_tables WHERE schemaname = r.nspname AND tablename = 'purchase_orders') THEN
--             CONTINUE;
--         END IF;
--         EXECUTE format('ALTER TABLE %I.purchase_orders DROP COLUMN IF EXISTS contact_info_snapshot', r.nspname);
--         EXECUTE format('ALTER TABLE %I.purchase_orders DROP COLUMN IF EXISTS company_name_snapshot', r.nspname);
--     END LOOP;
-- END $$;
--
-- DELETE FROM public.permissions WHERE key IN (
--     'inventory.visibility.full', 'inventory.visibility.staff',
--     'inventory.visibility.viewer', 'tenant.inventory_visibility.edit'
-- );
-- ============================================================================
