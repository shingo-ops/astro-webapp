-- Migration 20260602_020000: ADR-090 PR5a — public.products に tcg_type 列追加 + category から backfill
--
-- 在庫表の「タイプ」を自由文 category（"Pokemon" / "GUNDUM" 等）から TCG 種別マスタ
-- (public.tcg_type_master.code) に統一する。tcg_type 列を追加し、確定済みマッピングで backfill。
-- 冪等: ADD COLUMN IF NOT EXISTS + UPDATE は tcg_type IS NULL のみ対象（再走で上書きしない）。

ALTER TABLE public.products ADD COLUMN IF NOT EXISTS tcg_type VARCHAR(50);

-- 確定マッピング（ひとしさん承認 2026-06-02、全190件が明確対応）
UPDATE public.products SET tcg_type = 'pokemon_booster_box'
    WHERE tcg_type IS NULL AND category IN ('Pokemon', 'Pokemon TCG');
UPDATE public.products SET tcg_type = 'one_piece'
    WHERE tcg_type IS NULL AND category IN ('One Piece', 'One Piece TCG');
UPDATE public.products SET tcg_type = 'dragon_ball'
    WHERE tcg_type IS NULL AND category IN ('Dragon Ball', 'Dragon Ball TCG');
UPDATE public.products SET tcg_type = 'weiss_schwarz'
    WHERE tcg_type IS NULL AND category = 'Weiss Shwarz Rose';
UPDATE public.products SET tcg_type = 'gundam'
    WHERE tcg_type IS NULL AND category = 'GUNDUM';
UPDATE public.products SET tcg_type = 'union_arena'
    WHERE tcg_type IS NULL AND category = 'Union Arena';
UPDATE public.products SET tcg_type = 'yugioh'
    WHERE tcg_type IS NULL AND category = 'Yu-Gi-Oh OCG';

CREATE INDEX IF NOT EXISTS idx_public_products_tcg_type ON public.products (tcg_type);
