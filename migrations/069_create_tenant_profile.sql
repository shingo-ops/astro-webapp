-- ============================================================================
-- !! テナント別テンプレート。scripts/migrate_inventory_sprint8.py 経由で
--    全テナントに展開。新規テナントは _TENANT_TABLES_SQL (tenant.py) で
--    最初から保持される（ADR-034 自動適用）。
-- ============================================================================
-- Migration 069: {tenant_xxx}.tenant_profile (PO PDF / メール差出人情報)
--
-- 経緯:
--   spec.md v1.1 F8 / A6 マーケットプレイス型確定: 各テナント (セラー) 名義で
--   仕入元に発注し、PDF / メールには各テナントの会社名・印鑑・連絡先を
--   差出人欄として表示する (AC8.7)。
--
--   既存 migration 063 で {tenant_xxx}.purchase_orders に
--   company_name_snapshot / contact_info_snapshot 列を追加済だが、
--   その snapshot のソースとなる「テナント本体の会社情報」を持つテーブルが
--   未整備だったため、本 migration で導入する。
--
-- 設計:
--   - {tenant_xxx} schema 配置 (テナント別、マーケットプレイス遵守)
--   - 1 テナント 1 行運用 (UNIQUE 制約なし、アプリ層が 1 行管理。
--     将来「複数の発行者」を持つ要件が出たら拡張)
--   - 印鑑画像 (seal_image_url) は本 Sprint では URL のみ保存。
--     画像 upload UI は Sprint 9 以降で評価 (Out-of-scope)。
--   - default_language: PO PDF / メールの既定言語、tenant 既定。
--     supplier.default_language を優先するが、未設定時 fallback として使用。
--
-- ADR-034 観点:
--   - 既存テナント: 本 migration を scripts/migrate_inventory_sprint8.py で
--     一括適用 (deploy.yml ループ)
--   - 新規テナント: backend/app/services/tenant.py の _TENANT_TABLES_SQL
--     テンプレ末尾に tenant_profile 定義を追加することで自動適用
--
-- 冪等性:
--   CREATE TABLE IF NOT EXISTS / ADD COLUMN IF NOT EXISTS / DO 块
--
-- 関連:
--   .claude-pipeline/spec.md F8 / AC8.7
--   migrations/063_tenant_rbac_extensions.sql (snapshot 列)
--   backend/app/services/po_renderer.py (本 migration 列を読み出す)
--   docs/adr/ADR-034 (新規テナント自動適用)
--
-- 作成日: 2026-05-22
-- ============================================================================

-- === 1. {tenant_xxx}.tenant_profile 作成 + tenant.profile.* 権限 seed ===
DO $tp_create$
DECLARE
    schema_rec RECORD;
    created_count INTEGER := 0;
    seeded_count INTEGER := 0;
    role_rec RECORD;
    inserted_perms INTEGER;
BEGIN
    -- 1a. 権限 master に tenant.profile.* キーを追加 (一度だけ)
    INSERT INTO public.permissions (key, resource, action, description, category) VALUES
        ('tenant.profile.view',
            'tenant_profile', 'view',
            '自社の発行者情報 (会社名・印鑑・連絡先) を閲覧',
            'テナント設定'),
        ('tenant.profile.edit',
            'tenant_profile', 'edit',
            '自社の発行者情報 (PO PDF / メール差出人欄) を編集',
            'テナント設定')
    ON CONFLICT (key) DO NOTHING;

    -- 1b. 全テナント schema にテーブル作成 + 既定行 INSERT + 権限割当
    FOR schema_rec IN
        SELECT nspname FROM pg_namespace
        WHERE nspname ~ '^tenant_\d+$'
        ORDER BY nspname
    LOOP
        -- テナントスキーマが users/role_permissions テーブルを持たない場合は skip
        IF NOT EXISTS (
            SELECT 1 FROM pg_tables
            WHERE schemaname = schema_rec.nspname AND tablename = 'role_permissions'
        ) THEN
            CONTINUE;
        END IF;

        EXECUTE format($create$
            CREATE TABLE IF NOT EXISTS %I.tenant_profile (
                id                  SERIAL PRIMARY KEY,
                company_name        VARCHAR(255),
                company_name_en     VARCHAR(255),
                address             TEXT,
                phone               VARCHAR(50),
                email               VARCHAR(255),
                website             VARCHAR(255),
                seal_image_url      TEXT,
                default_language    CHAR(2) NOT NULL DEFAULT 'ja',
                created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT tenant_profile_default_language_check
                    CHECK (default_language IN ('ja', 'en', 'ko', 'zh'))
            )
        $create$, schema_rec.nspname);

        -- 既定行 (空) を 1 行用意。admin が UI で後から埋める。
        EXECUTE format($seed$
            INSERT INTO %I.tenant_profile (default_language)
            SELECT 'ja' WHERE NOT EXISTS (SELECT 1 FROM %I.tenant_profile)
        $seed$, schema_rec.nspname, schema_rec.nspname);

        created_count := created_count + 1;

        -- 1c. オーナー / システム管理者ロールに tenant.profile.* 権限を割当
        FOR role_rec IN
            EXECUTE format(
                'SELECT id, name FROM %I.roles WHERE name IN (''オーナー'', ''システム管理者'')',
                schema_rec.nspname
            )
        LOOP
            EXECUTE format(
                'INSERT INTO %I.role_permissions (role_id, permission_id) '
                'SELECT %s, p.id FROM public.permissions p '
                'WHERE p.key IN (''tenant.profile.view'', ''tenant.profile.edit'') '
                'ON CONFLICT (role_id, permission_id) DO NOTHING',
                schema_rec.nspname, role_rec.id
            );
            GET DIAGNOSTICS inserted_perms = ROW_COUNT;
            seeded_count := seeded_count + inserted_perms;
        END LOOP;

        RAISE NOTICE 'migration 069: %: tenant_profile 作成 + 既定行 + 権限割当 OK', schema_rec.nspname;
    END LOOP;
    RAISE NOTICE 'migration 069: 全 % テナントに tenant_profile を導入、% 権限割当', created_count, seeded_count;
END $tp_create$;

-- === 2. updated_at 自動更新トリガを各テナントに付与 ===
DO $tp_trigger$
DECLARE
    schema_rec RECORD;
BEGIN
    FOR schema_rec IN
        SELECT nspname FROM pg_namespace
        WHERE nspname ~ '^tenant_\d+$'
        ORDER BY nspname
    LOOP
        IF NOT EXISTS (
            SELECT 1 FROM pg_tables
            WHERE schemaname = schema_rec.nspname AND tablename = 'tenant_profile'
        ) THEN
            CONTINUE;
        END IF;

        EXECUTE format($fn$
            CREATE OR REPLACE FUNCTION %I.set_updated_at_tenant_profile()
            RETURNS TRIGGER AS $upd$
            BEGIN
                NEW.updated_at = NOW();
                RETURN NEW;
            END;
            $upd$ LANGUAGE plpgsql
        $fn$, schema_rec.nspname);

        EXECUTE format(
            'DROP TRIGGER IF EXISTS trigger_set_updated_at_tenant_profile ON %I.tenant_profile',
            schema_rec.nspname
        );
        EXECUTE format(
            'CREATE TRIGGER trigger_set_updated_at_tenant_profile '
            'BEFORE UPDATE ON %I.tenant_profile '
            'FOR EACH ROW EXECUTE FUNCTION %I.set_updated_at_tenant_profile()',
            schema_rec.nspname, schema_rec.nspname
        );
    END LOOP;
END $tp_trigger$;

-- ============================================================================
-- Rollback (緊急時のみ手動実行):
-- DO $rb$
-- DECLARE r RECORD;
-- BEGIN
--     FOR r IN SELECT nspname FROM pg_namespace WHERE nspname ~ '^tenant_\d+$' LOOP
--         EXECUTE format('DROP TABLE IF EXISTS %I.tenant_profile CASCADE', r.nspname);
--         EXECUTE format('DROP FUNCTION IF EXISTS %I.set_updated_at_tenant_profile() CASCADE', r.nspname);
--     END LOOP;
-- END $rb$;
-- DELETE FROM public.permissions WHERE key IN ('tenant.profile.view', 'tenant.profile.edit');
-- ============================================================================
