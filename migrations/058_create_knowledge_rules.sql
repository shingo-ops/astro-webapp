-- ============================================================================
-- Migration 058: public.knowledge_rules (正規化辞書 / 解析ルール)
--
-- 経緯:
--   spec.md v1.1 F1 / F3: ルールベース解析エンジンが使う「正規化辞書」。
--   仕入元 Discord メッセージの raw_content を正規化するためのパターンマッチ
--   ルール群（regex / prefix / substring 等の pattern_type を持つ）。
--
-- 設計:
--   - public schema 中央共有（A6、tenant_id 列なし）
--   - category: 'expansion_code' / 'rarity' / 'language' / 'exclude' / 'split' 等
--   - pattern_type: 'regex' / 'prefix' / 'substring' / 'exact'
--   - priority: 数値が大きいほど優先（F3 が DESC で評価）
--   - is_active で論理削除（実 DELETE は避ける、ルール監査のため）
--
-- ADR-034 観点: public schema のため 1 回のみ実行。
--
-- 関連:
--   .claude-pipeline/spec.md F3 (ルールベース解析)
--   migrations/057 (supplier_aliases と組み合わせ)
--
-- 作成日: 2026-05-21
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.knowledge_rules (
    id              SERIAL PRIMARY KEY,
    category        VARCHAR(50) NOT NULL,
    pattern_type    VARCHAR(20) NOT NULL,
    pattern         TEXT NOT NULL,
    normalized_to   TEXT,
    priority        INTEGER NOT NULL DEFAULT 100,
    language        CHAR(2) NOT NULL DEFAULT 'ja',
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    description     TEXT,
    created_by      INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- pattern_type CHECK 制約
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'knowledge_rules_pattern_type_check'
          AND conrelid = 'public.knowledge_rules'::regclass
    ) THEN
        ALTER TABLE public.knowledge_rules
            ADD CONSTRAINT knowledge_rules_pattern_type_check
            CHECK (pattern_type IN ('regex', 'prefix', 'substring', 'exact'));
    END IF;
END $$;

-- language CHECK 制約
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'knowledge_rules_language_check'
          AND conrelid = 'public.knowledge_rules'::regclass
    ) THEN
        ALTER TABLE public.knowledge_rules
            ADD CONSTRAINT knowledge_rules_language_check
            CHECK (language IN ('ja', 'en', 'ko', 'zh'));
    END IF;
END $$;

-- 索引: F3 解析時の高速優先順アクセス
CREATE INDEX IF NOT EXISTS idx_knowledge_rules_active_priority
    ON public.knowledge_rules (priority DESC, category)
    WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_knowledge_rules_category
    ON public.knowledge_rules (category, language)
    WHERE is_active = TRUE;

-- updated_at トリガ
CREATE OR REPLACE FUNCTION public.set_updated_at_knowledge_rules()
RETURNS TRIGGER AS $upd$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$upd$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_set_updated_at_knowledge_rules ON public.knowledge_rules;
CREATE TRIGGER trigger_set_updated_at_knowledge_rules
    BEFORE UPDATE ON public.knowledge_rules
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at_knowledge_rules();

COMMENT ON TABLE  public.knowledge_rules IS 'spec F1/F3: ルールベース解析エンジンの正規化辞書（全テナント共有）';
COMMENT ON COLUMN public.knowledge_rules.category IS '例: expansion_code / rarity / language / exclude / split';
COMMENT ON COLUMN public.knowledge_rules.pattern_type IS 'regex / prefix / substring / exact';
COMMENT ON COLUMN public.knowledge_rules.priority IS '降順評価。数値が大きいほど F3 で先に試行';

-- ============================================================================
-- Rollback:
--   DROP TRIGGER IF EXISTS trigger_set_updated_at_knowledge_rules ON public.knowledge_rules;
--   DROP FUNCTION IF EXISTS public.set_updated_at_knowledge_rules();
--   DROP TABLE IF EXISTS public.knowledge_rules;
-- ============================================================================
