-- ============================================================================
-- Migration 062: public.inventory_movements (在庫差分履歴、tenant_id 付き)
--                + public.tenant_llm_budgets (LLM 月次予算管理)
--                + public.products (Sprint 1 では空テーブルのみ作成)
--
-- 経緯:
--   spec.md v1.1 F1 / F4 / F6:
--     - inventory_movements: F6 admin 承認時の append-only 履歴。
--       「どのテナントの操作で動いたか」追跡用に tenant_id を保持（A6 確定）
--     - tenant_llm_budgets: F4 LLM コスト管理（hard_stop=true 既定、A2 確定）
--     - products: Sprint 1 では public.products を **空テーブル新規作成のみ**。
--       既存 {tenant_xxx}.products は Phase C で data migration（Out-of-scope #5）。
--       Sprint 7 以降の在庫検索 / Sprint 8 の PO で参照する受け皿。
--
-- 設計:
--   - inventory_movements.tenant_id INTEGER NOT NULL（A6 例外: 中央配置だが tenant 識別）
--   - products は Phase 1-C M-MVP migration 038 の {tenant_xxx}.products と同型列を
--     初期定義（拡張は Phase C で評価）
--
-- ADR-034 観点: public schema のため 1 回のみ実行。
--
-- 関連:
--   .claude-pipeline/spec.md F1 / F4 / F6 / Out-of-scope #5
--   migrations/038_add_products_phase1c_columns.sql (列互換)
--
-- 作成日: 2026-05-21
-- ============================================================================

-- === 1. public.products (Sprint 1 では空テーブル定義のみ、Phase C で data migration) ===
CREATE TABLE IF NOT EXISTS public.products (
    id                  SERIAL PRIMARY KEY,
    tenant_id           INTEGER,                            -- マーケットプレイス: NULL = 中央在庫、非 NULL = テナント所有
    product_code        VARCHAR(50),
    name                VARCHAR(255) NOT NULL,
    name_en             VARCHAR(255),
    description         TEXT,
    unit_price          NUMERIC(15, 2),
    unit_price_usd      NUMERIC(15, 2),
    unit_price_eur      NUMERIC(15, 2),
    stock_quantity      INTEGER NOT NULL DEFAULT 0,
    -- Phase 1-C M-MVP (migration 038) 互換の TCG B2B 列
    jan_code            VARCHAR(20),
    card_number         VARCHAR(50),
    expansion_code      VARCHAR(20),
    rarity              VARCHAR(20),
    language            VARCHAR(10),
    image_url           VARCHAR(500),
    is_archived         BOOLEAN NOT NULL DEFAULT FALSE,
    archived_at         TIMESTAMPTZ,
    supplier_default_id INTEGER REFERENCES public.suppliers(id) ON DELETE SET NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- PARTIAL UNIQUE (product_code) WHERE product_code IS NOT NULL（同じ migration 038 パターン）
CREATE UNIQUE INDEX IF NOT EXISTS uq_public_products_code
    ON public.products (product_code) WHERE product_code IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_public_products_jan
    ON public.products (jan_code) WHERE jan_code IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_public_products_archived
    ON public.products (is_archived);
CREATE INDEX IF NOT EXISTS idx_public_products_name
    ON public.products (name);
CREATE INDEX IF NOT EXISTS idx_public_products_name_en
    ON public.products (name_en);
CREATE INDEX IF NOT EXISTS idx_public_products_card_number
    ON public.products (card_number) WHERE card_number IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_public_products_expansion
    ON public.products (expansion_code) WHERE expansion_code IS NOT NULL;

CREATE OR REPLACE FUNCTION public.set_updated_at_products()
RETURNS TRIGGER AS $upd$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$upd$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_set_updated_at_public_products ON public.products;
CREATE TRIGGER trigger_set_updated_at_public_products
    BEFORE UPDATE ON public.products
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at_products();

COMMENT ON TABLE public.products IS
    'spec F1/Out-of-scope #5: マーケットプレイス商品マスタ（Sprint 1 では空、Phase C で {tenant_xxx}.products 移行）';

-- === 2. public.inventory_movements (append-only 履歴、tenant_id 付き) ===
CREATE TABLE IF NOT EXISTS public.inventory_movements (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       INTEGER NOT NULL,
    product_id      INTEGER NOT NULL REFERENCES public.products(id) ON DELETE RESTRICT,
    delta_qty       INTEGER NOT NULL,
    before_qty      INTEGER NOT NULL,
    after_qty       INTEGER NOT NULL,
    source_type     VARCHAR(50) NOT NULL,    -- 'discord_inbound_review' / 'manual_adjust' / 'po_received' / 'order_shipped'
    source_id       INTEGER,                  -- discord_inbound_messages.id 等の参照
    supplier_id     INTEGER REFERENCES public.suppliers(id) ON DELETE SET NULL,
    operator_id     INTEGER NOT NULL,
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- source_type CHECK 制約
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'inventory_movements_source_type_check'
          AND conrelid = 'public.inventory_movements'::regclass
    ) THEN
        ALTER TABLE public.inventory_movements
            ADD CONSTRAINT inventory_movements_source_type_check
            CHECK (source_type IN (
                'discord_inbound_review',
                'manual_adjust',
                'po_received',
                'order_shipped',
                'csv_import',
                'phase_c_migration'
            ));
    END IF;
END $$;

-- after_qty = before_qty + delta_qty を assertion で軽く保証（DB トリガで）
CREATE OR REPLACE FUNCTION public.assert_inventory_movement_arithmetic()
RETURNS TRIGGER AS $arith$
BEGIN
    IF NEW.after_qty IS DISTINCT FROM (NEW.before_qty + NEW.delta_qty) THEN
        RAISE EXCEPTION 'inventory_movements arithmetic violated: before=% delta=% after=%',
            NEW.before_qty, NEW.delta_qty, NEW.after_qty;
    END IF;
    RETURN NEW;
END;
$arith$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_assert_inventory_movement_arithmetic ON public.inventory_movements;
CREATE TRIGGER trigger_assert_inventory_movement_arithmetic
    BEFORE INSERT OR UPDATE ON public.inventory_movements
    FOR EACH ROW EXECUTE FUNCTION public.assert_inventory_movement_arithmetic();

CREATE INDEX IF NOT EXISTS idx_im_tenant       ON public.inventory_movements (tenant_id);
CREATE INDEX IF NOT EXISTS idx_im_product      ON public.inventory_movements (product_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_im_occurred     ON public.inventory_movements (occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_im_source       ON public.inventory_movements (source_type, source_id);

COMMENT ON TABLE public.inventory_movements IS
    'spec F1/F6: 在庫差分の append-only 履歴。tenant_id 付き（A6 例外: 中央配置だが操作テナント識別）';

-- === 3. public.tenant_llm_budgets ===
CREATE TABLE IF NOT EXISTS public.tenant_llm_budgets (
    tenant_id            INTEGER PRIMARY KEY,
    monthly_budget_usd   NUMERIC(10, 2) NOT NULL DEFAULT 0,
    current_month_usd    NUMERIC(10, 4) NOT NULL DEFAULT 0,
    last_reset_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    hard_stop            BOOLEAN NOT NULL DEFAULT TRUE,
    notify_admin         BOOLEAN NOT NULL DEFAULT TRUE,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE OR REPLACE FUNCTION public.set_updated_at_tenant_llm_budgets()
RETURNS TRIGGER AS $upd$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$upd$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_set_updated_at_tenant_llm_budgets ON public.tenant_llm_budgets;
CREATE TRIGGER trigger_set_updated_at_tenant_llm_budgets
    BEFORE UPDATE ON public.tenant_llm_budgets
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at_tenant_llm_budgets();

COMMENT ON TABLE public.tenant_llm_budgets IS
    'spec F1/F4 A2 確定: テナント月次 LLM 予算、hard_stop=true 既定、超過時 Discord 通知';

-- ============================================================================
-- Rollback:
--   DROP TRIGGER IF EXISTS trigger_set_updated_at_tenant_llm_budgets ON public.tenant_llm_budgets;
--   DROP FUNCTION IF EXISTS public.set_updated_at_tenant_llm_budgets();
--   DROP TRIGGER IF EXISTS trigger_assert_inventory_movement_arithmetic ON public.inventory_movements;
--   DROP FUNCTION IF EXISTS public.assert_inventory_movement_arithmetic();
--   DROP TRIGGER IF EXISTS trigger_set_updated_at_public_products ON public.products;
--   DROP FUNCTION IF EXISTS public.set_updated_at_products();
--   DROP TABLE IF EXISTS public.tenant_llm_budgets;
--   DROP TABLE IF EXISTS public.inventory_movements;
--   DROP TABLE IF EXISTS public.products;
-- ============================================================================
