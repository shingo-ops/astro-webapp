-- Migration 20260602_000000: ADR-090 PR1 — public.products に在庫表用の不足列を追加
--
-- 在庫(products)を public 中央へ一本化する前段（ADR-090）。
-- tenant_NNN.products にあり public.products に無い列を additive 追加し、
-- 在庫表(/products)が public.products を読み書きできるようにする（router 切替は PR2）。
-- name↔name_ja / quantity↔stock_quantity は PR2 で router の SELECT alias で吸収するため
-- ここでは列を追加しない（重複列を作らない）。
--
-- 列型は tenant_NNN.products（migration 005 の {schema}.products 定義）に厳密一致させる:
--   mark VARCHAR(100) / status VARCHAR(20) DEFAULT 'active' / condition VARCHAR(50)
--   / weight NUMERIC(10,3) / notes TEXT
--
-- 冪等: ADD COLUMN IF NOT EXISTS で再走可。全列 NULL 許可 + status のみ default のため
-- ゼロダウンタイム（既存 185 行は status='active' 既定、他は NULL で投入）。

ALTER TABLE public.products
    ADD COLUMN IF NOT EXISTS mark      VARCHAR(100),
    ADD COLUMN IF NOT EXISTS status    VARCHAR(20) DEFAULT 'active',
    ADD COLUMN IF NOT EXISTS condition VARCHAR(50),
    ADD COLUMN IF NOT EXISTS weight    NUMERIC(10, 3),
    ADD COLUMN IF NOT EXISTS notes     TEXT;

-- status は tenant 側と同様にフィルタ/索引対象になりうるため index を付与（冪等）。
CREATE INDEX IF NOT EXISTS idx_public_products_status ON public.products (status);
