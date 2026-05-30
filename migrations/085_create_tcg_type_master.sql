-- ============================================================================
-- Migration 085: public.tcg_type_master 新設 + tcg_series_master の tcg_type CHECK 撤廃
--
-- ADR-083: TCG シリーズの「種別」(ポケモンカード / ワンピース 等) を、固定 CHECK 制約から
--   マスタ表 + UI 管理へ移行し、種別自体を増減可能にする。
--
-- 冪等性:
--   - CREATE TABLE / CREATE INDEX IF NOT EXISTS
--   - 種別 seed は ON CONFLICT (code) DO NOTHING
--   - CHECK 制約 DROP は DROP CONSTRAINT IF EXISTS + to_regclass ガード
-- ============================================================================

-- === 1. 種別マスタ ===
CREATE TABLE IF NOT EXISTS public.tcg_type_master (
    id          SERIAL PRIMARY KEY,
    code        VARCHAR(50)  NOT NULL UNIQUE,
    name_ja     VARCHAR(100) NOT NULL,
    name_en     VARCHAR(100),
    sort_order  INTEGER      NOT NULL DEFAULT 100,
    is_active   BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tcg_type_master_sort ON public.tcg_type_master (sort_order, id);

-- 既存 tcg_series_master.tcg_type と一致する 6 種別を seed（旧 CHECK の許可値）。
-- name_ja は旧 i18n ラベル (superAdmin.tcg.types.*) を踏襲。
INSERT INTO public.tcg_type_master (code, name_ja, name_en, sort_order) VALUES
    ('pokemon_booster_box', 'ポケモンカード',   'Pokémon Card',    10),
    ('one_piece',           'ワンピース',       'One Piece TCG',   20),
    ('dragon_ball',         'ドラゴンボール',   'Dragon Ball TCG', 30),
    ('union_arena',         'ユニオンアリーナ', 'Union Arena',     40),
    ('yugioh',              '遊戯王',           'Yu-Gi-Oh!',       50),
    ('other',               'その他',           'Other',           900)
ON CONFLICT (code) DO NOTHING;

-- updated_at トリガ（migration 061 と同パターン）
CREATE OR REPLACE FUNCTION public.set_updated_at_tcg_type_master()
RETURNS TRIGGER AS $upd$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$upd$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_set_updated_at_tcg_type_master ON public.tcg_type_master;
CREATE TRIGGER trigger_set_updated_at_tcg_type_master
    BEFORE UPDATE ON public.tcg_type_master
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at_tcg_type_master();

COMMENT ON TABLE public.tcg_type_master IS
    'ADR-083: TCG 種別マスタ。UI から増減可能。tcg_series_master.tcg_type の値集合の正本。';

-- === 2. tcg_series_master の固定 CHECK 制約を撤廃 ===
-- 種別を自由に増減可能にするため。tcg_series_master が存在する環境でのみ実行
-- (migration-test の最小ベースラインでは未作成のことがあるため to_regclass ガード)。
DO $$
BEGIN
    IF to_regclass('public.tcg_series_master') IS NOT NULL THEN
        ALTER TABLE public.tcg_series_master
            DROP CONSTRAINT IF EXISTS tcg_series_master_tcg_type_check;
        RAISE NOTICE 'tcg_series_master_tcg_type_check dropped (or already absent)';
    ELSE
        RAISE NOTICE 'public.tcg_series_master not present; skipping CHECK drop';
    END IF;
END $$;

-- ============================================================================
-- Rollback:
--   ALTER TABLE public.tcg_series_master ADD CONSTRAINT tcg_series_master_tcg_type_check
--     CHECK (tcg_type IN ('pokemon_booster_box','one_piece','dragon_ball','union_arena','yugioh','other'));
--   DROP TRIGGER IF EXISTS trigger_set_updated_at_tcg_type_master ON public.tcg_type_master;
--   DROP FUNCTION IF EXISTS public.set_updated_at_tcg_type_master();
--   DROP TABLE IF EXISTS public.tcg_type_master;
-- ============================================================================
