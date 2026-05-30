-- ============================================================================
-- Migration 086: public.tcg_type_master へ TCG 種別を追加 (ADR-083 拡張 / QA 2026-05-31)
--
-- スプレッドシートの各 TCG (GUNDUM / Weiss Schwarz / Degimon / hololive /
-- LORCANA / Xross Stars) を種別として追加する。データ(シリーズ)の有無に関わらず
-- 種別だけは登録する要望に対応。既存の one_piece/dragon_ball/union_arena/yugioh は
-- migration 085 で登録済み。
--
-- 冪等: ON CONFLICT (code) DO NOTHING。
-- ============================================================================
INSERT INTO public.tcg_type_master (code, name_ja, name_en, sort_order) VALUES
    ('gundam',        'ガンダムカードゲーム', 'Gundam Card Game',           60),
    ('weiss_schwarz', 'ヴァイスシュヴァルツ', 'Weiß Schwarz',               70),
    ('digimon',       'デジモンカードゲーム', 'Digimon Card Game',          80),
    ('hololive',      'ホロライブ',           'hololive Official Card Game', 90),
    ('lorcana',       'ディズニー ロルカナ',  'Disney Lorcana',            100),
    ('xross_stars',   'クロススタァ',         'Xross Stars',               110)
ON CONFLICT (code) DO NOTHING;

-- ============================================================================
-- Rollback:
--   DELETE FROM public.tcg_type_master
--     WHERE code IN ('gundam','weiss_schwarz','digimon','hololive','lorcana','xross_stars');
-- ============================================================================
