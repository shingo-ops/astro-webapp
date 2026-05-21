-- ============================================================================
-- Migration 057: public.supplier_aliases (仕入元別の商品エイリアス辞書)
--
-- 経緯:
--   spec.md v1.1 F1 / G2: 「45 仕入元それぞれの言い回しを supplier_aliases で
--   学習し、PO PDF / メール送信時に該当仕入元固有の表記へ自動置換できる」
--
-- 設計:
--   - public schema 中央共有（A6 マーケットプレイス型、tenant_id 列なし）
--   - language CHAR(2) DEFAULT 'ja' で i18n alias 対応（ja/en 別エイリアス保持可）
--   - UNIQUE (supplier_id, alias_text, language) で重複防止
--   - confidence NUMERIC(4,3): F3/F4 解析パイプラインが alias_text の信頼度を記録
--   - source: 'manual' / 'discord_inbound' / 'csv_import' / 'llm_suggested' 等
--   - product_id は public.products への参照（Sprint 1 では public.products は
--     未作成のため FK 制約は付けず、INTEGER で保持。Sprint 7 / Phase C で FK 追加）
--
-- ADR-034 観点:
--   public schema migration のため deploy.yml では 1 回のみ実行。
--
-- 冪等性:
--   CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS
--
-- 関連:
--   .claude-pipeline/spec.md F1 / F8 (alias 置換 PDF)
--   migrations/056 (public.suppliers FK 先)
--
-- 作成日: 2026-05-21
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.supplier_aliases (
    id            SERIAL PRIMARY KEY,
    product_id    INTEGER,                                -- public.products.id (Phase C で FK 化)
    supplier_id   INTEGER NOT NULL REFERENCES public.suppliers(id) ON DELETE CASCADE,
    alias_text    VARCHAR(500) NOT NULL,
    language      CHAR(2) NOT NULL DEFAULT 'ja',
    confidence    NUMERIC(4, 3),                          -- 0.000 〜 1.000、F3/F4 解析の信頼度
    source        VARCHAR(50) NOT NULL DEFAULT 'manual',  -- manual / discord_inbound / csv_import / llm_suggested
    created_by    INTEGER,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (supplier_id, alias_text, language)
);

-- language CHECK 制約
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'supplier_aliases_language_check'
          AND conrelid = 'public.supplier_aliases'::regclass
    ) THEN
        ALTER TABLE public.supplier_aliases
            ADD CONSTRAINT supplier_aliases_language_check
            CHECK (language IN ('ja', 'en', 'ko', 'zh'));
    END IF;
END $$;

-- confidence CHECK 制約（0.000 〜 1.000）
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'supplier_aliases_confidence_check'
          AND conrelid = 'public.supplier_aliases'::regclass
    ) THEN
        ALTER TABLE public.supplier_aliases
            ADD CONSTRAINT supplier_aliases_confidence_check
            CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1));
    END IF;
END $$;

-- source CHECK 制約
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'supplier_aliases_source_check'
          AND conrelid = 'public.supplier_aliases'::regclass
    ) THEN
        ALTER TABLE public.supplier_aliases
            ADD CONSTRAINT supplier_aliases_source_check
            CHECK (source IN ('manual', 'discord_inbound', 'csv_import', 'llm_suggested'));
    END IF;
END $$;

-- 索引: F3 ルール解析の高速 alias 探索（部分一致 / ILIKE 想定）
CREATE INDEX IF NOT EXISTS idx_supplier_aliases_alias_text
    ON public.supplier_aliases (alias_text);
CREATE INDEX IF NOT EXISTS idx_supplier_aliases_supplier_lang
    ON public.supplier_aliases (supplier_id, language);
CREATE INDEX IF NOT EXISTS idx_supplier_aliases_product
    ON public.supplier_aliases (product_id)
    WHERE product_id IS NOT NULL;

-- updated_at 自動更新トリガ
CREATE OR REPLACE FUNCTION public.set_updated_at_supplier_aliases()
RETURNS TRIGGER AS $upd$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$upd$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_set_updated_at_supplier_aliases ON public.supplier_aliases;
CREATE TRIGGER trigger_set_updated_at_supplier_aliases
    BEFORE UPDATE ON public.supplier_aliases
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at_supplier_aliases();

COMMENT ON TABLE  public.supplier_aliases IS 'spec F1: 仕入元固有の商品エイリアス辞書（PO PDF alias 置換、F3/F4 解析の語彙）';
COMMENT ON COLUMN public.supplier_aliases.confidence IS 'F3/F4 解析の信頼度 0.000〜1.000 (NULL = manual で信頼度未評価)';
COMMENT ON COLUMN public.supplier_aliases.source IS 'manual / discord_inbound / csv_import / llm_suggested';
COMMENT ON COLUMN public.supplier_aliases.product_id IS 'public.products.id 参照 (Sprint 7/Phase C で FK 化)';

-- ============================================================================
-- Rollback:
--   DROP TRIGGER IF EXISTS trigger_set_updated_at_supplier_aliases ON public.supplier_aliases;
--   DROP FUNCTION IF EXISTS public.set_updated_at_supplier_aliases();
--   DROP TABLE IF EXISTS public.supplier_aliases;
-- ============================================================================
