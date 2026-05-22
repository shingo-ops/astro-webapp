-- Rollback for migration 068_add_inventory_search_indexes.sql
-- pg_trgm extension は他用途で使われる可能性があるため自動 DROP しない。

DROP INDEX IF EXISTS public.idx_supplier_aliases_alias_text_trgm;
DROP INDEX IF EXISTS public.idx_tcg_series_name_en_trgm;
DROP INDEX IF EXISTS public.idx_tcg_series_name_ja_trgm;
DROP INDEX IF EXISTS public.idx_trainer_dex_name_en_trgm;
DROP INDEX IF EXISTS public.idx_trainer_dex_name_ja_trgm;
DROP INDEX IF EXISTS public.idx_pokemon_dex_name_en_trgm;
DROP INDEX IF EXISTS public.idx_pokemon_dex_name_ja_trgm;
DROP INDEX IF EXISTS public.idx_products_jan_code_trgm;
DROP INDEX IF EXISTS public.idx_products_card_number_trgm;
DROP INDEX IF EXISTS public.idx_products_expansion_code_trgm;
DROP INDEX IF EXISTS public.idx_products_name_en_trgm;
DROP INDEX IF EXISTS public.idx_products_name_trgm;
