-- ============================================================================
-- !! 警告 !! このSQLファイルは **テンプレート** です。
-- {schema}, {tenant_id} のプレースホルダを含むため、
-- そのまま psql で実行するとシンタックスエラーになります。
--
-- 必ず scripts/migrate_adr021_sprint5_commissions.py 経由で実行してください:
--   docker compose exec backend python /app/scripts/migrate_adr021_sprint5_commissions.py
-- ============================================================================
--
-- ADR-021 Phase 5 / Sprint 5 / Migration 050: 担当者報酬計算 MVP
--
-- 目的:
--   ADR-021 第 5 節「担当者報酬計算」AC-005 + AC-010 を最小実装する。
--   OrderFlow Manager の現行 5 ロール（営業/受注/発送/仕入/トラブル）の
--   報酬計算式を Sales Anchor 上で再現し、テナント別の掛け率カスタマイズと
--   is_employee による除外を実現する。
--
-- 含む 3 DDL:
--   a) staff.is_employee カラム追加（既存 staff テーブルに対する ALTER）
--   b) tenant_commission_settings テーブル新設（テナント別の rate 設定）
--   c) order_commissions テーブル新設（受注ごとに 5 ロール × 担当者 × 計算済額）
--
-- 設計（spec.md 完全準拠）:
--   - tenant_commission_settings: tenant_id UNIQUE で 1 テナント = 1 設定。
--     commission_rates JSONB に 5 ロールの type ("rate" | "fixed") と value を保持。
--     未設定テナントには router 側で get-or-create で default を作る（idempotent）。
--   - order_commissions: 縦持ち（5 ロール分の行を最大 5 行）。
--     UNIQUE (order_id, role) で 1 受注 = 1 ロール = 1 行を保証し、
--     UPSERT による割当と再計算を可能にする。
--     staff_id ON DELETE SET NULL でスタッフ削除時に履歴を残す。
--     calculated_amount NUMERIC(14,2) は再計算で書き換えられる。
--
-- 冪等性:
--   - ALTER TABLE / CREATE TABLE / CREATE INDEX 全てに IF NOT EXISTS 付き
--   - DO ブロックでポリシー存在確認
--   - 何度実行しても副作用なし
--
-- 変更履歴:
--   2026-05-11: 初版（ADR-021 Phase 5 / Sprint 5）
-- ============================================================================

-- ----------------------------------------------------------------------------
-- a) staff.is_employee カラム追加
-- ----------------------------------------------------------------------------
-- OrderFlow 現行式は「担当者名 != '谷澤'」というハードコード判定で
-- 社員・役員（報酬対象外）を除外していた。Sales Anchor では staff.is_employee
-- BOOLEAN フラグで一般化する。
ALTER TABLE {schema}.staff
    ADD COLUMN IF NOT EXISTS is_employee BOOLEAN NOT NULL DEFAULT FALSE;


-- ----------------------------------------------------------------------------
-- b) tenant_commission_settings テーブル新設
-- ----------------------------------------------------------------------------
-- 1 テナントにつき 1 行。commission_rates JSONB に 5 ロール分の rate 設定を保持。
-- デフォルト値は OrderFlow 現行式に揃える:
--   営業: 売上 × 10% (rate)
--   受注: 売上 × 10% (rate)
--   発送: 200 円固定 (fixed)
--   仕入: 100 円固定 (fixed)
--   トラブル: 500 円固定 (fixed)
CREATE TABLE IF NOT EXISTS {schema}.tenant_commission_settings (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL DEFAULT {tenant_id},
    commission_rates JSONB NOT NULL DEFAULT '{
        "sales": {"type": "rate", "value": 0.10},
        "order": {"type": "rate", "value": 0.10},
        "ship":  {"type": "fixed", "value": 200},
        "purchase": {"type": "fixed", "value": 100},
        "trouble": {"type": "fixed", "value": 500}
    }'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id)
);

CREATE INDEX IF NOT EXISTS idx_tenant_commission_settings_tenant
    ON {schema}.tenant_commission_settings (tenant_id);

-- updated_at 自動更新トリガー
CREATE OR REPLACE FUNCTION {schema}.set_updated_at_tenant_commission_settings()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_set_updated_at_tenant_commission_settings
    ON {schema}.tenant_commission_settings;

CREATE TRIGGER trigger_set_updated_at_tenant_commission_settings
    BEFORE UPDATE ON {schema}.tenant_commission_settings
    FOR EACH ROW
    EXECUTE FUNCTION {schema}.set_updated_at_tenant_commission_settings();

ALTER TABLE {schema}.tenant_commission_settings ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = '{schema}'
          AND tablename = 'tenant_commission_settings'
          AND policyname = 'tenant_isolation_tenant_commission_settings'
    ) THEN
        EXECUTE format(
            'CREATE POLICY tenant_isolation_tenant_commission_settings ON %I.tenant_commission_settings '
            'USING (tenant_id = public.current_tenant_id())',
            '{schema}'
        );
    END IF;
END
$$;


-- ----------------------------------------------------------------------------
-- c) order_commissions テーブル新設
-- ----------------------------------------------------------------------------
-- 縦持ち（1 受注 × 最大 5 ロール = 最大 5 行）で報酬を保持する。
-- UPSERT による担当者割当 + recalc で calculated_amount を都度書き換える。
-- staff 削除時は SET NULL で履歴を残す（過去の calculated_amount を保護）。
CREATE TABLE IF NOT EXISTS {schema}.order_commissions (
    id SERIAL PRIMARY KEY,
    order_id INTEGER NOT NULL
        REFERENCES {schema}.orders(id) ON DELETE CASCADE,
    tenant_id INTEGER NOT NULL DEFAULT {tenant_id},
    role TEXT NOT NULL
        CHECK (role IN ('sales', 'order', 'ship', 'purchase', 'trouble')),
    staff_id INTEGER
        REFERENCES {schema}.staff(id) ON DELETE SET NULL,
    calculated_amount NUMERIC(14, 2) NOT NULL DEFAULT 0,
    calculated_at TIMESTAMPTZ,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (order_id, role)
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_order_commissions_tenant
    ON {schema}.order_commissions (tenant_id);
CREATE INDEX IF NOT EXISTS idx_order_commissions_order
    ON {schema}.order_commissions (order_id);
CREATE INDEX IF NOT EXISTS idx_order_commissions_staff
    ON {schema}.order_commissions (staff_id);
-- 月次集計用（calculated_at で期間絞り）
CREATE INDEX IF NOT EXISTS idx_order_commissions_tenant_calc
    ON {schema}.order_commissions (tenant_id, calculated_at);

-- updated_at 自動更新トリガー
CREATE OR REPLACE FUNCTION {schema}.set_updated_at_order_commissions()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_set_updated_at_order_commissions
    ON {schema}.order_commissions;

CREATE TRIGGER trigger_set_updated_at_order_commissions
    BEFORE UPDATE ON {schema}.order_commissions
    FOR EACH ROW
    EXECUTE FUNCTION {schema}.set_updated_at_order_commissions();

ALTER TABLE {schema}.order_commissions ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = '{schema}'
          AND tablename = 'order_commissions'
          AND policyname = 'tenant_isolation_order_commissions'
    ) THEN
        EXECUTE format(
            'CREATE POLICY tenant_isolation_order_commissions ON %I.order_commissions '
            'USING (tenant_id = public.current_tenant_id())',
            '{schema}'
        );
    END IF;
END
$$;
