-- ============================================================================
-- Migration 075: goals (目標管理テーブル)
--
-- 経緯:
--   ダッシュボード強化 (ADR-TBD) にあたり、週次/月次の売上・商談・リード目標を
--   チーム単位・個人単位で設定・閲覧できる基盤を整備する。
--
-- 設計:
--   - {tenant_xxx} schema 配置 (テナント別)
--   - user_id IS NULL かつ team_id IS NOT NULL → チーム目標
--   - team_id IS NULL かつ user_id IS NOT NULL → 個人目標
--   - period_type: 'monthly' | 'weekly'
--   - period_num: 月の場合 1-12、週の場合 1-53 (ISO週番号)
--   - kpi_type: 'revenue' | 'deal_count' | 'close_rate' |
--               'lead_count' | 'conversion_rate'
--
-- 権限:
--   - goals.view  → 閲覧 (全ロール)
--   - goals.edit  → 作成/編集 (チームリーダー以上)
--
-- 冪等性:
--   CREATE TABLE IF NOT EXISTS / INSERT ... ON CONFLICT DO NOTHING
--
-- 適用対象: 全テナント
-- 作成日: 2026-05-25
-- ============================================================================

DO $goals_create$
DECLARE
    schema_rec     RECORD;
    role_rec       RECORD;
    created_count  INTEGER := 0;
    seeded_count   INTEGER := 0;
BEGIN
    -- 1. 権限マスタに goals.* キーを追加 (一度だけ)
    INSERT INTO public.permissions (key, resource, action, description, category) VALUES
        ('goals.view', 'goals', 'view', '目標を閲覧する', '目標管理'),
        ('goals.edit', 'goals', 'edit', '目標を作成・編集する', '目標管理')
    ON CONFLICT (key) DO NOTHING;

    -- 2. 全テナント schema に goals テーブルを作成 + 権限割当
    FOR schema_rec IN
        SELECT nspname FROM pg_namespace
        WHERE nspname ~ '^tenant_\d+$'
        ORDER BY nspname
    LOOP
        IF NOT EXISTS (
            SELECT 1 FROM pg_tables
            WHERE schemaname = schema_rec.nspname AND tablename = 'role_permissions'
        ) THEN
            CONTINUE;
        END IF;

        -- 2a. テーブル作成
        EXECUTE format($create$
            CREATE TABLE IF NOT EXISTS %I.goals (
                id           SERIAL PRIMARY KEY,
                user_id      INTEGER REFERENCES public.users(id) ON DELETE CASCADE,
                team_id      INTEGER,
                period_type  VARCHAR(10)    NOT NULL
                                 CHECK (period_type IN ('monthly', 'weekly')),
                period_year  SMALLINT       NOT NULL CHECK (period_year >= 2020),
                period_num   SMALLINT       NOT NULL CHECK (period_num BETWEEN 1 AND 53),
                kpi_type     VARCHAR(30)    NOT NULL
                                 CHECK (kpi_type IN (
                                     'revenue', 'deal_count', 'close_rate',
                                     'lead_count', 'conversion_rate'
                                 )),
                target_value NUMERIC(15, 2) NOT NULL CHECK (target_value >= 0),
                created_by   INTEGER REFERENCES public.users(id) ON DELETE SET NULL,
                created_at   TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
                updated_at   TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
                -- チーム目標: user_id IS NULL AND team_id IS NOT NULL
                -- 個人目標:   team_id IS NULL AND user_id IS NOT NULL
                CONSTRAINT goals_owner_check
                    CHECK (
                        (user_id IS NOT NULL AND team_id IS NULL) OR
                        (user_id IS NULL AND team_id IS NOT NULL)
                    ),
                CONSTRAINT goals_unique_target
                    UNIQUE (user_id, team_id, period_type, period_year, period_num, kpi_type)
            )
        $create$, schema_rec.nspname);

        -- 2b. インデックス
        EXECUTE format(
            'CREATE INDEX IF NOT EXISTS idx_goals_user_period '
            'ON %I.goals (user_id, period_year, period_num)',
            schema_rec.nspname
        );
        EXECUTE format(
            'CREATE INDEX IF NOT EXISTS idx_goals_team_period '
            'ON %I.goals (team_id, period_year, period_num)',
            schema_rec.nspname
        );

        -- 2c. updated_at 自動更新トリガ
        EXECUTE format($fn$
            CREATE OR REPLACE FUNCTION %I.set_updated_at_goals()
            RETURNS TRIGGER AS $upd$
            BEGIN
                NEW.updated_at = NOW();
                RETURN NEW;
            END;
            $upd$ LANGUAGE plpgsql
        $fn$, schema_rec.nspname);
        EXECUTE format(
            'DROP TRIGGER IF EXISTS trigger_set_updated_at_goals ON %I.goals',
            schema_rec.nspname
        );
        EXECUTE format(
            'CREATE TRIGGER trigger_set_updated_at_goals '
            'BEFORE UPDATE ON %I.goals '
            'FOR EACH ROW EXECUTE FUNCTION %I.set_updated_at_goals()',
            schema_rec.nspname, schema_rec.nspname
        );

        created_count := created_count + 1;

        -- 2d. 全ロールに goals.view を付与、リーダー以上に goals.edit を付与
        FOR role_rec IN
            EXECUTE format(
                'SELECT id, name FROM %I.roles',
                schema_rec.nspname
            )
        LOOP
            -- goals.view は全ロール
            EXECUTE format(
                'INSERT INTO %I.role_permissions (role_id, permission_id) '
                'SELECT %s, p.id FROM public.permissions p '
                'WHERE p.key = ''goals.view'' '
                'ON CONFLICT (role_id, permission_id) DO NOTHING',
                schema_rec.nspname, role_rec.id
            );
            -- goals.edit はオーナー / システム管理者 / チームリーダー
            IF role_rec.name IN ('オーナー', 'システム管理者', 'チームリーダー', 'マネージャー') THEN
                EXECUTE format(
                    'INSERT INTO %I.role_permissions (role_id, permission_id) '
                    'SELECT %s, p.id FROM public.permissions p '
                    'WHERE p.key = ''goals.edit'' '
                    'ON CONFLICT (role_id, permission_id) DO NOTHING',
                    schema_rec.nspname, role_rec.id
                );
                GET DIAGNOSTICS seeded_count = ROW_COUNT;
            END IF;
        END LOOP;

        RAISE NOTICE 'migration 075: %: goals テーブル作成 + 権限割当 OK', schema_rec.nspname;
    END LOOP;

    RAISE NOTICE 'migration 075: 全 % テナントに goals を導入', created_count;
END $goals_create$;

-- ============================================================================
-- Rollback (緊急時のみ手動実行):
-- DO $rb$
-- DECLARE r RECORD;
-- BEGIN
--     FOR r IN SELECT nspname FROM pg_namespace WHERE nspname ~ '^tenant_\d+$' LOOP
--         EXECUTE format('DROP TABLE IF EXISTS %I.goals CASCADE', r.nspname);
--         EXECUTE format('DROP FUNCTION IF EXISTS %I.set_updated_at_goals() CASCADE', r.nspname);
--     END LOOP;
-- END $rb$;
-- DELETE FROM public.permissions WHERE key IN ('goals.view', 'goals.edit');
-- ============================================================================
