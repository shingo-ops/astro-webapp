-- ============================================================================
-- Migration 070 (down): public.tenant_settings 撤去 — Sprint 9 / F9
--
-- 用途: 緊急ロールバック専用。本番では原則使用しない（履歴データ消失のため）。
--
-- 関連:
--   migrations/070_add_spreadsheet_phase.sql (up)
-- ============================================================================

DROP TRIGGER IF EXISTS trg_tenant_settings_touch_updated_at ON public.tenant_settings;
DROP FUNCTION IF EXISTS public.tenant_settings_touch_updated_at();

DROP TABLE IF EXISTS public.tenant_settings;

-- phase.switch 権限 seed は念のため残す（他 sprint で参照される可能性を考慮）
-- 不要であれば手動で:
--   DELETE FROM public.permissions WHERE key = 'phase.switch';
