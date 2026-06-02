-- ============================================================================
-- Migration 20260602_180000: ADR-093 Phase 3a — public.inventory に
--   予約商品(offer_type) / 発送日(ship_timing) を追加し UNIQUE キーを粒度拡張
--
-- 在庫表/オファーの 1 行を「商品×仕入元×状態(condition)×形態(unit)×区分(offer_type)
-- ×発送日(ship_timing)」の組合せで一意化する（ADR-093 Phase 3 確定設計）。これにより
-- 同一 商品×仕入元×状態 でも、在庫品(in_stock)と予約品(pre_order)・発送日違いを別行で扱える。
--
-- 変更:
--   - offer_type  VARCHAR(20) NOT NULL DEFAULT 'in_stock'
--       CHECK: in_stock(在庫) / pre_order(予約)
--   - ship_timing VARCHAR(20) NULL
--       CHECK: on_release(発売日発送) / 1day_before / 2day_before / other。在庫品は NULL。
--   - UNIQUE 制約を旧 (supplier_id, product_id, condition) から
--       (supplier_id, product_id, condition, COALESCE(unit,''), offer_type, COALESCE(ship_timing,''))
--     の UNIQUE INDEX へ置換（NULL を含む unit/ship_timing は COALESCE で正規化し NULL 同士も同一視）。
--
-- 適用対象: public スキーマ (1 回のみ)
-- 冪等: ADD COLUMN IF NOT EXISTS / DROP CONSTRAINT IF EXISTS / CREATE UNIQUE INDEX IF NOT EXISTS。
--
-- 注（非 additive を含む / backend/CLAUDE.md）:
--   旧 UNIQUE 制約の DROP→粒度拡張を伴う。新キーは旧キーより細かいため既存行は必ず
--   一意（duplicate は発生しない）。public.inventory は 18h 失効の一時オファーデータで
--   uniqueness 拡大によるデータ損失はない。ADR-093（承認済み）の確定設計。
-- ============================================================================

ALTER TABLE public.inventory
    ADD COLUMN IF NOT EXISTS offer_type  VARCHAR(20) NOT NULL DEFAULT 'in_stock',
    ADD COLUMN IF NOT EXISTS ship_timing VARCHAR(20);

-- CHECK 制約（冪等。status CHECK と同じ DO ブロック方式）
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'inventory_offer_type_check') THEN
        ALTER TABLE public.inventory
            ADD CONSTRAINT inventory_offer_type_check
            CHECK (offer_type IN ('in_stock', 'pre_order'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'inventory_ship_timing_check') THEN
        ALTER TABLE public.inventory
            ADD CONSTRAINT inventory_ship_timing_check
            CHECK (ship_timing IS NULL OR ship_timing IN ('on_release', '1day_before', '2day_before', 'other'));
    END IF;
END $$;

-- UNIQUE キー粒度拡張: 旧 inline UNIQUE 制約（自動名）を落として
-- COALESCE ベースの UNIQUE INDEX へ置換。
ALTER TABLE public.inventory
    DROP CONSTRAINT IF EXISTS inventory_supplier_id_product_id_condition_key;
CREATE UNIQUE INDEX IF NOT EXISTS uq_inventory_offer_key
    ON public.inventory (
        supplier_id, product_id, condition,
        COALESCE(unit, ''), offer_type, COALESCE(ship_timing, '')
    );

-- 予約品の発送日フィルタ/ソート補助（任意・冪等）
CREATE INDEX IF NOT EXISTS idx_inventory_offer_type
    ON public.inventory (offer_type);
