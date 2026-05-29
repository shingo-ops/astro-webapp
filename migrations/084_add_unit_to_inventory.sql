-- ============================================================================
-- Migration 084: public.inventory に unit (数量の単位) 列を追加
--
-- QA 2026-05-30 (ひとしさん):
--   解析レビュー画面に「単位」列 (Box / Case / Pack / Set / Peace) を追加し、
--   F6 承認時に仕入元オファーの単位を public.inventory へ保存できるようにする。
--   既存の quantity / unit_price は「在庫数」「単価」、本列はその数量単位。
--
-- 適用対象: public スキーマ (1 回のみ)
-- 冪等: ADD COLUMN IF NOT EXISTS で再走可。
--
-- 注: migration-test.yml の最小ベースラインには public.inventory (081) が無いため、
--     to_regclass で存在チェックしてから ALTER する（不在環境では no-op）。
--     本番は 081 適用済みなので deploy では確実に列が追加される。
--
-- 関連:
--   migrations/081_create_inventory.sql (public.inventory 本体)
--   backend/app/services/inventory_movements.py (_upsert_inventory_offer が書込)
--   docs/specs/inventory-management/spec.md (F11 仕入元オファー)
-- ============================================================================

DO $$
BEGIN
    IF to_regclass('public.inventory') IS NOT NULL THEN
        ALTER TABLE public.inventory ADD COLUMN IF NOT EXISTS unit VARCHAR(20);
        COMMENT ON COLUMN public.inventory.unit IS
            '数量の単位 (Box / Case / Pack / Set / Peace)。F6 承認時に記録。QA 2026-05-30';
    ELSE
        RAISE NOTICE 'public.inventory not present; skipping unit column add';
    END IF;
END $$;
