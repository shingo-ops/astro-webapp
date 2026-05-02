-- ============================================================================
-- !! テンプレート。scripts/migrate_meta_page_routing.py 経由で全テナントに展開。
-- ============================================================================
-- Phase 1-E Follow-up F16-S6 / Migration 044: tenant_meta_config → meta_page_routing 同期トリガ
--
-- 目的:
--   各 tenant_NNN.tenant_meta_config への INSERT / UPDATE / DELETE を
--   public.meta_page_routing にミラーする。Webhook で 1 クエリ逆引きするため。
--
-- 設計:
--   - SECURITY DEFINER 関数: tenant schema の row 変更を public へ反映
--   - INSERT / UPDATE → ON CONFLICT (tenant_id, config_id) DO UPDATE で冪等
--   - DELETE → 該当行を public から削除
--   - 末尾で既存行を backfill（再適用時は ON CONFLICT で no-op）
--
-- セキュリティ (F16-FU1, 2026-05-03):
--   SECURITY DEFINER 関数は `SET search_path = pg_catalog, public` を明示し、
--   呼び出し側 search_path に依存せず常に決まったスキーマを参照する。
--   これにより、呼び出し側が search_path を細工した場合の権限昇格 / hijacking を遮断する
--   （PostgreSQL 公式推奨パターン: defense-in-depth）。
--
-- 関連:
--   migrations/043_create_meta_page_routing.sql
--   migrations/040_create_tenant_meta_config.sql
--   backend/app/routers/webhook.py
--
-- 冪等性:
--   CREATE OR REPLACE FUNCTION / DROP TRIGGER IF EXISTS / ON CONFLICT DO UPDATE
--   いずれも再実行可能。
--
-- 変更履歴:
--   2026-05-01: 初版（Phase 1-E Follow-up F16-S6）
--   2026-05-03: F16-FU1 — SECURITY DEFINER 関数に SET search_path 追加（defense-in-depth）
-- ============================================================================

-- === 同期トリガ関数 ===
CREATE OR REPLACE FUNCTION {schema}.sync_meta_page_routing()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $sync_mpr$
BEGIN
    IF (TG_OP = 'DELETE') THEN
        DELETE FROM public.meta_page_routing
        WHERE tenant_id = OLD.tenant_id
          AND config_id = OLD.id;
        RETURN OLD;
    END IF;

    INSERT INTO public.meta_page_routing (
        tenant_id, config_id, schema_name,
        page_id, instagram_business_account_id, is_active, updated_at
    )
    VALUES (
        NEW.tenant_id,
        NEW.id,
        '{schema_raw}',
        NEW.page_id,
        NEW.instagram_business_account_id,
        NEW.is_active,
        NOW()
    )
    ON CONFLICT (tenant_id, config_id) DO UPDATE SET
        schema_name                     = EXCLUDED.schema_name,
        page_id                         = EXCLUDED.page_id,
        instagram_business_account_id   = EXCLUDED.instagram_business_account_id,
        is_active                       = EXCLUDED.is_active,
        updated_at                      = NOW();

    RETURN NEW;
END;
$sync_mpr$;

-- === トリガ ===
DROP TRIGGER IF EXISTS trg_sync_meta_page_routing ON {schema}.tenant_meta_config;
CREATE TRIGGER trg_sync_meta_page_routing
    AFTER INSERT OR UPDATE OR DELETE ON {schema}.tenant_meta_config
    FOR EACH ROW EXECUTE FUNCTION {schema}.sync_meta_page_routing();

-- === 既存行の backfill（再適用時は ON CONFLICT で no-op） ===
INSERT INTO public.meta_page_routing (
    tenant_id, config_id, schema_name,
    page_id, instagram_business_account_id, is_active, updated_at
)
SELECT
    tenant_id, id, '{schema_raw}',
    page_id, instagram_business_account_id, is_active, NOW()
FROM {schema}.tenant_meta_config
ON CONFLICT (tenant_id, config_id) DO UPDATE SET
    schema_name                     = EXCLUDED.schema_name,
    page_id                         = EXCLUDED.page_id,
    instagram_business_account_id   = EXCLUDED.instagram_business_account_id,
    is_active                       = EXCLUDED.is_active,
    updated_at                      = NOW();
