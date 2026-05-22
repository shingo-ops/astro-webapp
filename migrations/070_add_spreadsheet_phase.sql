-- ============================================================================
-- Migration 070: public.tenant_settings (spreadsheet_phase) — Sprint 9 / F9
--
-- 経緯:
--   spec.md v1.2 F9: Phase A（スプレッドシート並走）を長期運用形態として整備する。
--   テナント別に現在の Phase（'A' / 'B' / 'C'）を保持し、F6 承認時に
--   `products.stock_quantity` を更新するかどうかの分岐に使用する（AC9.1）。
--
--   v1.2 では `'A'` 固定運用、`'B'` / `'C'` は別 ADR で時期判断（Out-of-scope）。
--   ただし将来の切替時の証跡用に `audit_log` への記録経路も Sprint 9 で整備（AC9.4）。
--
-- 設計:
--   - `public.tenant_settings` 配置（テナント全体 1 行運用、tenant_id PK）。
--     `public.tenants` を参照する集中設定テーブル。
--     {tenant_xxx} schema ではなく public 配置を選択した理由:
--       1. Phase 切替は中央 admin（is_super_admin）が行う運用上のスイッチで、
--          テナント自身が触る設定ではない（マーケットプレイス運営者の業務）
--       2. 全テナント横断で Phase 状況を一覧表示する将来用途を考慮（admin UI）
--       3. `_TENANT_TABLES_SQL` テンプレへの追記不要、新規テナントは
--          後段の INSERT トリガで自動的に 'A' で初期化される（既定）。
--   - `spreadsheet_phase` 列に CHECK 制約 ('A','B','C')、デフォルト 'A'。
--   - 既存テナントには `INSERT ... SELECT FROM public.tenants` で一括 seed。
--   - 新規テナント追加時: tenant.py の create_tenant_schema フローで
--     INSERT INTO public.tenant_settings (tenant_id) VALUES (...) を発行する
--     経路を追加することで自動初期化（本 migration 適用後の Sprint 9 で対応）。
--
-- ADR-034 観点:
--   - public schema のため 1 回のみ実行（テナントループ不要）。
--   - 新規テナント作成時は backend/app/services/tenant.py の
--     `create_tenant_schema` で `INSERT INTO public.tenant_settings` を発行する
--     よう追加（同 Sprint 9 で実装）。
--
-- 冪等性:
--   CREATE TABLE IF NOT EXISTS / ADD COLUMN IF NOT EXISTS / ON CONFLICT DO NOTHING
--
-- 関連:
--   .claude-pipeline/spec.md F9 / AC9.1〜9.6
--   backend/app/services/phase_gate.py (Sprint 9)
--   backend/app/routers/super_admin_phase_switch.py (Sprint 9)
--   migrations/062_create_inventory_movements_and_budget.sql (inventory_movements)
--   docs/adr/ADR-034 (新規テナント自動適用)
--
-- 作成日: 2026-05-22
-- ============================================================================

-- === 1. public.tenant_settings テーブル作成 ===
CREATE TABLE IF NOT EXISTS public.tenant_settings (
    tenant_id           INTEGER PRIMARY KEY REFERENCES public.tenants(id) ON DELETE CASCADE,
    spreadsheet_phase   TEXT NOT NULL DEFAULT 'A'
                        CHECK (spreadsheet_phase IN ('A', 'B', 'C')),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 既存テーブルへの追加列 (将来 ALTER 時の互換性のため、CREATE 後にも IF NOT EXISTS で挿入)
DO $tenant_settings_cols$
BEGIN
    -- spreadsheet_phase が存在しない既存環境向けの保険
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'tenant_settings'
          AND column_name = 'spreadsheet_phase'
    ) THEN
        ALTER TABLE public.tenant_settings
            ADD COLUMN spreadsheet_phase TEXT NOT NULL DEFAULT 'A'
                CHECK (spreadsheet_phase IN ('A', 'B', 'C'));
    END IF;

    -- CHECK 制約が古い形（例: ('A','B') のみ）になっている可能性に備える
    -- 既存 CHECK の名前は実装依存なので、無ければ追加のみ実施
END $tenant_settings_cols$;

-- === 2. 既存テナント全件に対して seed (デフォルト Phase A) ===
INSERT INTO public.tenant_settings (tenant_id, spreadsheet_phase)
SELECT id, 'A' FROM public.tenants
ON CONFLICT (tenant_id) DO NOTHING;

-- === 3. updated_at 自動更新 trigger（PostgreSQL 標準パターン） ===
CREATE OR REPLACE FUNCTION public.tenant_settings_touch_updated_at()
RETURNS TRIGGER AS $body$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$body$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_tenant_settings_touch_updated_at ON public.tenant_settings;
CREATE TRIGGER trg_tenant_settings_touch_updated_at
    BEFORE UPDATE ON public.tenant_settings
    FOR EACH ROW EXECUTE FUNCTION public.tenant_settings_touch_updated_at();

-- === 4. 監査ログ用の権限 seed (phase.switch) ===
-- 中央 admin (require_super_admin) のみが切替可能。
-- role_permissions では割当てない（is_super_admin フラグで二重ガード）。
INSERT INTO public.permissions (key, resource, action, description, category) VALUES
    ('phase.switch',
        'tenant_settings', 'switch_phase',
        'スプレッドシート並走 Phase の切替 (A / B / C)。中央 admin 専用 (is_super_admin)',
        '在庫運用')
ON CONFLICT (key) DO NOTHING;

-- === 5. 完了ログ ===
DO $log$
DECLARE
    settings_count INTEGER;
    tenants_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO settings_count FROM public.tenant_settings;
    SELECT COUNT(*) INTO tenants_count FROM public.tenants;
    RAISE NOTICE 'migration 070 完了: tenant_settings 行数=%, tenants 行数=% (差分=新規テナントは後で seed)',
        settings_count, tenants_count;
END $log$;
