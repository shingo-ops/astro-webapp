-- ============================================================================
-- Migration 082: public.products に Box 商品属性 9 列追加 (F1 拡張 / F11 連携)
--
-- spec.md v1.3 F1 / F11:
--   商品マスタ.csv (Pokemon / Union Arena 等) の Box 商品属性を投入するために、
--   既存 products テーブルに Boxes per Case / Box重量 / Release Date 等の列を追加する。
--
-- 既存 Phase 1-C migration 038 はシングルカード用列 (card_number / expansion_code /
-- rarity 等) を追加済。本 migration は Box 商品用の補完列を追加し、両商品種を
-- 同一テーブルで扱う。
--
-- 追加列:
--   - category          VARCHAR(50)  -- Pokemon / Union Arena / Yu-Gi-Oh! 等 (TCG シリーズ識別)
--   - boxes_per_case    INTEGER      -- 1 ケースあたりの Box 数
--   - packs_per_box     INTEGER      -- 1 Box あたりのパック数
--   - box_weight_kg     NUMERIC(8,3) -- Box 単体重量
--   - case_weight_kg    NUMERIC(8,3) -- Case 重量
--   - release_date      DATE         -- 発売日
--   - moq               INTEGER      -- 最小発注数
--   - hs_code           VARCHAR(20)  -- HS コード (輸出向け)
--   - material          VARCHAR(50)  -- 素材 (paper 等)
--
-- 適用対象: public スキーマ (1 回のみ)
-- 冪等: ADD COLUMN IF NOT EXISTS で再走可
--
-- 関連:
--   docs/specs/inventory-management/spec.md v1.3 F1 / F11
--   sheets/raw/商品マスタ.csv (投入元データ)
--   scripts/seed_products_from_master.py (本 migration 適用後に実行)
-- ============================================================================

ALTER TABLE public.products
    ADD COLUMN IF NOT EXISTS category        VARCHAR(50),
    ADD COLUMN IF NOT EXISTS boxes_per_case  INTEGER,
    ADD COLUMN IF NOT EXISTS packs_per_box   INTEGER,
    ADD COLUMN IF NOT EXISTS box_weight_kg   NUMERIC(8,3),
    ADD COLUMN IF NOT EXISTS case_weight_kg  NUMERIC(8,3),
    ADD COLUMN IF NOT EXISTS release_date    DATE,
    ADD COLUMN IF NOT EXISTS moq             INTEGER,
    ADD COLUMN IF NOT EXISTS hs_code         VARCHAR(20),
    ADD COLUMN IF NOT EXISTS material        VARCHAR(50);

-- category による作品別フィルタ (F2 AC2.9 作品ごとマスタ管理 UI, F7 検索)
CREATE INDEX IF NOT EXISTS idx_products_category
    ON public.products (category) WHERE category IS NOT NULL;

-- release_date によるソート (新着順表示)
CREATE INDEX IF NOT EXISTS idx_products_release_date
    ON public.products (release_date DESC) WHERE release_date IS NOT NULL;
