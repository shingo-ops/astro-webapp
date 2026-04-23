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
-- Phase 1 再設計 / Migration 019: staff / staff_emails / staff_ui_preferences
--
-- 内容:
--   [1] staff（人間スタッフ本体）。既存 public.users との 1対1 紐付けを user_id 列で表現
--   [2] staff_emails（1スタッフが複数メールを持つケース、EMP-00005 問題への対応）
--   [3] staff_ui_preferences（ダークモード・各メニュー表示フラグ等のUI設定）
--   [4] updated_at トリガ
--
-- 前提:
--   - {schema}.roles は migration 003 で作成済（既存）
--   - 014 で public.current_tenant_id() 定義済
--   - 本 migration では sales_rep_id FK（customers → staff）は付けない
--     （循環依存回避）。FK 付与は 022 の後、データ投入前に別途実施する必要あり
--
-- 設計書参照:
--   - jarvis_crm_staff_roles_bots_design.docx §3-3
--   - migrate_staff_roles_bots_PATCH.md §3
--
-- 変更履歴:
--   2026-04-23: 初版作成（Phase 1 再設計）

-- === [1] staff 本体 ===

CREATE TABLE {schema}.staff (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL DEFAULT {tenant_id},
    user_id INTEGER UNIQUE REFERENCES public.users(id),   -- 既存 users との1対1紐付け（認証）。旧データ移行期は NULL 許容
    staff_code VARCHAR(20) NOT NULL,                      -- EMP-00001 形式
    surname_jp VARCHAR(50) NOT NULL,
    given_name_jp VARCHAR(50) NOT NULL,
    surname_kana VARCHAR(100),
    given_name_kana VARCHAR(100),
    surname_en VARCHAR(100),
    given_name_en VARCHAR(100),
    primary_email VARCHAR(255) NOT NULL,                  -- UNIQUE 制約なし（共有アドレス運用許容）
    discord_user_id VARCHAR(50),
    role_id INTEGER NOT NULL REFERENCES {schema}.roles(id),
    status VARCHAR(20) NOT NULL DEFAULT 'active'
        CHECK (status IN ('active','inactive','pending')),
    firebase_uid VARCHAR(128),                            -- Firebase Auth UID（JWT の sub）
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, staff_code),
    UNIQUE (tenant_id, discord_user_id),                  -- テナント内で Discord ID 重複なし（別テナントでは同一OK）
    UNIQUE (tenant_id, firebase_uid)                      -- 同上
);

CREATE INDEX idx_staff_tenant_id ON {schema}.staff (tenant_id);
CREATE INDEX idx_staff_role_id ON {schema}.staff (role_id);
CREATE INDEX idx_staff_primary_email ON {schema}.staff (primary_email);
CREATE INDEX idx_staff_user_id ON {schema}.staff (user_id);
CREATE INDEX idx_staff_status ON {schema}.staff (status);

COMMENT ON TABLE {schema}.staff IS
  '人間スタッフ本体。bot は bots テーブルで別管理';
COMMENT ON COLUMN {schema}.staff.user_id IS
  '既存 public.users(id) との1対1紐付け。Firebase 認証ユーザ行と対応';
COMMENT ON COLUMN {schema}.staff.primary_email IS
  'UNIQUE 制約なし。共有アドレス運用を許容';
COMMENT ON COLUMN {schema}.staff.firebase_uid IS
  'Firebase Auth の UID。JWT の sub claim と一致。認証時の突合に使用';

-- === [2] staff_emails（複数メールアドレス対応） ===

CREATE TABLE {schema}.staff_emails (
    id SERIAL PRIMARY KEY,
    staff_id INTEGER NOT NULL REFERENCES {schema}.staff(id) ON DELETE CASCADE,
    email VARCHAR(255) NOT NULL,
    purpose VARCHAR(50),                                  -- main / notification / discord_link / secondary 等
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (staff_id, email)
);

CREATE INDEX idx_staff_emails_staff_id ON {schema}.staff_emails (staff_id);

COMMENT ON TABLE {schema}.staff_emails IS
  'スタッフの追加メールアドレス。primary_email は staff 本体に、副メールはここに';

-- === [3] staff_ui_preferences ===

CREATE TABLE {schema}.staff_ui_preferences (
    staff_id INTEGER PRIMARY KEY REFERENCES {schema}.staff(id) ON DELETE CASCADE,
    dark_mode BOOLEAN NOT NULL DEFAULT FALSE,
    show_chat_menu BOOLEAN NOT NULL DEFAULT TRUE,
    show_sales_menu BOOLEAN NOT NULL DEFAULT TRUE,
    show_settings_menu BOOLEAN NOT NULL DEFAULT TRUE,
    show_admin_menu BOOLEAN NOT NULL DEFAULT FALSE,
    show_buddy_menu BOOLEAN NOT NULL DEFAULT TRUE,
    show_sidebar BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE {schema}.staff_ui_preferences IS
  'スタッフ自身のUI設定。最終メニュー表示は (役割が権限を持つ) AND (本人の表示設定) の AND';

-- === [4] updated_at トリガ ===

-- {schema}.trg_set_updated_at() は 015 で作成済みのため再利用可能。
-- 念のため冪等な CREATE OR REPLACE で定義しておく。
CREATE OR REPLACE FUNCTION {schema}.trg_set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_staff_updated_at
    BEFORE UPDATE ON {schema}.staff
    FOR EACH ROW EXECUTE FUNCTION {schema}.trg_set_updated_at();

CREATE TRIGGER trg_staff_ui_preferences_updated_at
    BEFORE UPDATE ON {schema}.staff_ui_preferences
    FOR EACH ROW EXECUTE FUNCTION {schema}.trg_set_updated_at();

-- === [5] customers.sales_rep_id → staff(id) の FK 付与 ===
-- 015 では staff テーブルが未作成だったため、ここで付与する

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_customers_sales_rep'
          AND connamespace = (SELECT oid FROM pg_namespace WHERE nspname = '{schema_raw}')
    ) THEN
        ALTER TABLE {schema}.customers
            ADD CONSTRAINT fk_customers_sales_rep
            FOREIGN KEY (sales_rep_id) REFERENCES {schema}.staff(id);
    END IF;
END $$;
