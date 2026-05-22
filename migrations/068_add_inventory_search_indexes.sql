-- ============================================================================
-- Migration 068: 在庫検索用 pg_trgm + GIN index (Sprint 7 / F7)
--
-- 経緯:
--   spec.md v1.1 F7 / AC7.6: 検索 API レスポンス p95 ≤ 500ms (tenant_004 想定 1000 products)。
--   全 7 種横断検索 (products.name/name_en/expansion_code/card_number/jan_code +
--   pokemon_dex.name_ja/name_en + trainer_dex.name_ja/name_en +
--   tcg_series_master.name_ja/name_en + supplier_aliases.alias_text)
--   に対し部分一致 ILIKE %q% を高速化するため pg_trgm の GIN index を作成。
--
-- 設計:
--   - pg_trgm extension: PostgreSQL 標準拡張、CREATE EXTENSION IF NOT EXISTS。
--   - GIN index: 7 検索キーに対応する gin_trgm_ops index を作成。
--   - フォールバック: CREATE EXTENSION 権限が無い環境では本 migration 全体が
--     skip される (DO ブロック内で例外捕捉)。検索 API 側は ILIKE のみで動作。
--
-- ADR-034 観点: public schema のため 1 回のみ実行。新規テナント作成時は影響なし。
--
-- 関連:
--   migrations/061 (pokemon_dex/trainer_dex/tcg_series_master 列定義)
--   migrations/062 (public.products 列定義 + 既存 btree index)
--   migrations/057 (public.supplier_aliases.alias_text 既存 btree index)
--   backend/app/routers/inventory_search.py (本 index を消費)
--
-- 作成日: 2026-05-22
-- ============================================================================

-- === 1. pg_trgm extension (権限不足時はスキップして警告) ===
DO $$
BEGIN
    BEGIN
        CREATE EXTENSION IF NOT EXISTS pg_trgm;
    EXCEPTION WHEN insufficient_privilege OR feature_not_supported THEN
        RAISE WARNING 'pg_trgm extension の作成権限がありません。検索 API は ILIKE のみで動作 (パフォーマンス劣化の可能性)。';
        RETURN;
    END;
END $$;

-- === 2. pg_trgm が有効な場合のみ GIN index を作成 ===
-- 後続の CREATE INDEX は extension 未導入時 SQLSTATE 42704 (undefined_object) で失敗するため
-- 各文を DO ブロックで保護する。
DO $$
DECLARE
    has_pg_trgm BOOLEAN;
BEGIN
    SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm') INTO has_pg_trgm;
    IF NOT has_pg_trgm THEN
        RAISE WARNING 'pg_trgm 未導入のため GIN index 作成をスキップ。';
        RETURN;
    END IF;

    -- === public.products ===
    EXECUTE 'CREATE INDEX IF NOT EXISTS idx_products_name_trgm
             ON public.products USING gin (name gin_trgm_ops)';
    EXECUTE 'CREATE INDEX IF NOT EXISTS idx_products_name_en_trgm
             ON public.products USING gin (name_en gin_trgm_ops)';
    EXECUTE 'CREATE INDEX IF NOT EXISTS idx_products_expansion_code_trgm
             ON public.products USING gin (expansion_code gin_trgm_ops)';
    EXECUTE 'CREATE INDEX IF NOT EXISTS idx_products_card_number_trgm
             ON public.products USING gin (card_number gin_trgm_ops)';
    EXECUTE 'CREATE INDEX IF NOT EXISTS idx_products_jan_code_trgm
             ON public.products USING gin (jan_code gin_trgm_ops)';

    -- === public.pokemon_dex ===
    EXECUTE 'CREATE INDEX IF NOT EXISTS idx_pokemon_dex_name_ja_trgm
             ON public.pokemon_dex USING gin (name_ja gin_trgm_ops)';
    EXECUTE 'CREATE INDEX IF NOT EXISTS idx_pokemon_dex_name_en_trgm
             ON public.pokemon_dex USING gin (name_en gin_trgm_ops)';

    -- === public.trainer_dex ===
    EXECUTE 'CREATE INDEX IF NOT EXISTS idx_trainer_dex_name_ja_trgm
             ON public.trainer_dex USING gin (name_ja gin_trgm_ops)';
    EXECUTE 'CREATE INDEX IF NOT EXISTS idx_trainer_dex_name_en_trgm
             ON public.trainer_dex USING gin (name_en gin_trgm_ops)';

    -- === public.tcg_series_master ===
    EXECUTE 'CREATE INDEX IF NOT EXISTS idx_tcg_series_name_ja_trgm
             ON public.tcg_series_master USING gin (name_ja gin_trgm_ops)';
    EXECUTE 'CREATE INDEX IF NOT EXISTS idx_tcg_series_name_en_trgm
             ON public.tcg_series_master USING gin (name_en gin_trgm_ops)';

    -- === public.supplier_aliases ===
    EXECUTE 'CREATE INDEX IF NOT EXISTS idx_supplier_aliases_alias_text_trgm
             ON public.supplier_aliases USING gin (alias_text gin_trgm_ops)';
END $$;

-- ============================================================================
-- Rollback (068_add_inventory_search_indexes_down.sql 参照):
--   DROP INDEX IF EXISTS public.idx_supplier_aliases_alias_text_trgm;
--   DROP INDEX IF EXISTS public.idx_tcg_series_name_en_trgm;
--   ... (全 12 index)
--   pg_trgm extension は他用途で使われる可能性があるため自動 DROP しない。
-- ============================================================================
