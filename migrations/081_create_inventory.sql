-- ============================================================================
-- Migration 081: public.inventory (仕入元現在オファー、F11 新規)
--
-- spec.md v1.3 F11 / AC11.1:
--   現スプレッドシート「出力」シート (102 行) が表す
--   「仕入元 × 商品 × 状態 × Quantity × Unit Price」のデータ構造を CRM 上に追加。
--   営業フローで「仕入先 X が今 Y 個 Z 円で出してくれる」を直接参照する。
--
-- 既存 entity との関係:
--   - public.products: 商品マスタ (静的属性、SSoT)
--   - public.inventory_movements: 増減履歴 (append-only)
--   - public.inventory (本 migration): 仕入元別現在オファー (UPSERT)
--
-- 設計:
--   - public schema 中央共有 (A6 マーケットプレイス型)
--   - UNIQUE (supplier_id, product_id, condition) で同条件 1 行に集約
--   - quantity / unit_price は仕入元の現在オファー値、F6 承認時に UPSERT
--   - condition は出力.csv 由来 ('Sealed box' / 'Damaged box' / 'No shrink box' / 'Case' 等)
--   - source は投入経路 ('manual' / 'discord_parsed' / 'csv_import')
--
-- 冪等性: CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS
--
-- 関連:
--   docs/specs/inventory-management/spec.md v1.3 F11 / Sprint 11
--   migrations/056_add_suppliers_type_and_promote_public.sql (suppliers)
--   migrations/062_create_inventory_movements_and_budget.sql (inventory_movements)
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.inventory (
    id              SERIAL PRIMARY KEY,
    supplier_id     INTEGER NOT NULL REFERENCES public.suppliers(id) ON DELETE CASCADE,
    product_id      INTEGER NOT NULL,  -- public.products.id (FK は Phase C で追加、現状 INTEGER)
    condition       VARCHAR(50) NOT NULL,
    quantity        INTEGER NOT NULL DEFAULT 0,
    unit_price      INTEGER NOT NULL DEFAULT 0,
    status          VARCHAR(20) NOT NULL DEFAULT 'in_stock',
    notes_ja        TEXT,
    notes_en        TEXT,
    offered_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMPTZ,
    source          VARCHAR(50) NOT NULL DEFAULT 'manual',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (supplier_id, product_id, condition)
);

-- インデックス: 商品単位の在庫検索 (F7 連携)
CREATE INDEX IF NOT EXISTS idx_inventory_product
    ON public.inventory (product_id);

-- インデックス: 仕入元別オファー一覧 (admin UI)
CREATE INDEX IF NOT EXISTS idx_inventory_supplier
    ON public.inventory (supplier_id);

-- インデックス: status による in_stock フィルタ (営業向け検索高速化)
CREATE INDEX IF NOT EXISTS idx_inventory_status
    ON public.inventory (status) WHERE status = 'in_stock';

-- status CHECK 制約
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'inventory_status_check'
          AND conrelid = 'public.inventory'::regclass
    ) THEN
        ALTER TABLE public.inventory
          ADD CONSTRAINT inventory_status_check
          CHECK (status IN ('in_stock', 'out_of_stock', 'reserved', 'archived'));
    END IF;
END $$;

-- updated_at 自動更新トリガー
CREATE OR REPLACE FUNCTION public.set_inventory_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_inventory_updated_at ON public.inventory;
CREATE TRIGGER trg_inventory_updated_at
    BEFORE UPDATE ON public.inventory
    FOR EACH ROW EXECUTE FUNCTION public.set_inventory_updated_at();
