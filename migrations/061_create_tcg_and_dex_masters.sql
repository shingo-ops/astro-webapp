-- ============================================================================
-- Migration 061: public.pokemon_dex / public.trainer_dex / public.tcg_series_master
--
-- 経緯:
--   spec.md v1.1 F1: 商品マスタの基礎となる図鑑・シリーズマスタ。
--   - pokemon_dex: 1025 行（最新世代まで、AC1.4）
--   - trainer_dex: トレーナー図鑑
--   - tcg_series_master: Pokemon Booster Box / One Piece / Dragon Ball /
--                        Union Arena / 遊戯王 / その他 6 系列
--
-- 設計:
--   - public schema 中央共有（A6、全テナント共通）
--   - i18n: name_ja / name_en 両方を保持（F7 在庫検索の AND/OR 横断対応）
--   - dex_number は UNIQUE 制約（pokemon は 1〜1025 等の自然順）
--
-- 関連:
--   .claude-pipeline/spec.md F1 / F7 (検索横断対象)
--   scripts/seed_pokemon_dex.py (Sprint 1 で seed)
--   scripts/seed_tcg_series.py (Sprint 1 で seed)
--
-- 作成日: 2026-05-21
-- ============================================================================

-- === 1. public.pokemon_dex ===
CREATE TABLE IF NOT EXISTS public.pokemon_dex (
    id            SERIAL PRIMARY KEY,
    dex_number    INTEGER NOT NULL UNIQUE,
    name_ja       VARCHAR(100) NOT NULL,
    name_en       VARCHAR(100) NOT NULL,
    generation    INTEGER,
    region        VARCHAR(50),
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pokemon_dex_name_ja   ON public.pokemon_dex (name_ja);
CREATE INDEX IF NOT EXISTS idx_pokemon_dex_name_en   ON public.pokemon_dex (name_en);
CREATE INDEX IF NOT EXISTS idx_pokemon_dex_generation ON public.pokemon_dex (generation);

CREATE OR REPLACE FUNCTION public.set_updated_at_pokemon_dex()
RETURNS TRIGGER AS $upd$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$upd$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_set_updated_at_pokemon_dex ON public.pokemon_dex;
CREATE TRIGGER trigger_set_updated_at_pokemon_dex
    BEFORE UPDATE ON public.pokemon_dex
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at_pokemon_dex();

COMMENT ON TABLE public.pokemon_dex IS 'spec F1/F7: ポケモン図鑑（1025 行、全テナント共有、検索横断対象）';

-- === 2. public.trainer_dex ===
CREATE TABLE IF NOT EXISTS public.trainer_dex (
    id            SERIAL PRIMARY KEY,
    dex_number    INTEGER NOT NULL UNIQUE,
    name_ja       VARCHAR(100) NOT NULL,
    name_en       VARCHAR(100) NOT NULL,
    era           VARCHAR(50),
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_trainer_dex_name_ja  ON public.trainer_dex (name_ja);
CREATE INDEX IF NOT EXISTS idx_trainer_dex_name_en  ON public.trainer_dex (name_en);

CREATE OR REPLACE FUNCTION public.set_updated_at_trainer_dex()
RETURNS TRIGGER AS $upd$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$upd$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_set_updated_at_trainer_dex ON public.trainer_dex;
CREATE TRIGGER trigger_set_updated_at_trainer_dex
    BEFORE UPDATE ON public.trainer_dex
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at_trainer_dex();

COMMENT ON TABLE public.trainer_dex IS 'spec F1/F7: トレーナー図鑑（全テナント共有、検索横断対象）';

-- === 3. public.tcg_series_master ===
CREATE TABLE IF NOT EXISTS public.tcg_series_master (
    id              SERIAL PRIMARY KEY,
    tcg_type        VARCHAR(50) NOT NULL,
    series_code     VARCHAR(50) NOT NULL,
    name_ja         VARCHAR(200) NOT NULL,
    name_en         VARCHAR(200) NOT NULL,
    release_date    DATE,
    category        VARCHAR(50),
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tcg_type, series_code)
);

-- tcg_type CHECK 制約（spec F1: 5 系列 + その他）
-- ADR-083 (migration 085) で本 CHECK は撤廃され、種別は public.tcg_type_master で
-- 管理する方式に移行した。tcg_type_master が既に存在する環境（=ADR-083 適用後）では
-- 本 CHECK を再付与しない。再付与すると 085/086 で追加した新種別 (gundam 等) の
-- データが 6 値固定 CHECK に違反し毎デプロイで失敗するため (QA 2026-05-31 hotfix)。
-- ADR-083 未適用の旧環境では従来どおり付与する。
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'tcg_series_master_tcg_type_check'
          AND conrelid = 'public.tcg_series_master'::regclass
    ) AND to_regclass('public.tcg_type_master') IS NULL THEN
        ALTER TABLE public.tcg_series_master
            ADD CONSTRAINT tcg_series_master_tcg_type_check
            CHECK (tcg_type IN (
                'pokemon_booster_box',
                'one_piece',
                'dragon_ball',
                'union_arena',
                'yugioh',
                'other'
            ));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_tcg_series_tcg_type      ON public.tcg_series_master (tcg_type);
CREATE INDEX IF NOT EXISTS idx_tcg_series_release       ON public.tcg_series_master (release_date DESC);
CREATE INDEX IF NOT EXISTS idx_tcg_series_name_ja       ON public.tcg_series_master (name_ja);
CREATE INDEX IF NOT EXISTS idx_tcg_series_name_en       ON public.tcg_series_master (name_en);

CREATE OR REPLACE FUNCTION public.set_updated_at_tcg_series_master()
RETURNS TRIGGER AS $upd$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$upd$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_set_updated_at_tcg_series_master ON public.tcg_series_master;
CREATE TRIGGER trigger_set_updated_at_tcg_series_master
    BEFORE UPDATE ON public.tcg_series_master
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at_tcg_series_master();

COMMENT ON TABLE public.tcg_series_master IS
    'spec F1/F7: TCG シリーズマスタ（Pokemon Booster Box / One Piece / Dragon Ball / Union Arena / Yu-Gi-Oh + その他）';

-- ============================================================================
-- Rollback:
--   DROP TRIGGER IF EXISTS trigger_set_updated_at_tcg_series_master ON public.tcg_series_master;
--   DROP TRIGGER IF EXISTS trigger_set_updated_at_trainer_dex ON public.trainer_dex;
--   DROP TRIGGER IF EXISTS trigger_set_updated_at_pokemon_dex ON public.pokemon_dex;
--   DROP FUNCTION IF EXISTS public.set_updated_at_tcg_series_master();
--   DROP FUNCTION IF EXISTS public.set_updated_at_trainer_dex();
--   DROP FUNCTION IF EXISTS public.set_updated_at_pokemon_dex();
--   DROP TABLE IF EXISTS public.tcg_series_master;
--   DROP TABLE IF EXISTS public.trainer_dex;
--   DROP TABLE IF EXISTS public.pokemon_dex;
-- ============================================================================
