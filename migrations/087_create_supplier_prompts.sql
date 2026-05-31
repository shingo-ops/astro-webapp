-- ============================================================================
-- Migration 087: public.supplier_prompts 新設 (ADR-085 / QA 2026-05-31)
--
-- 仕入先(supplier)ごとに Gemini 解析用プロンプトを管理する。値はスプレッドシート
-- 「API解析」6行目 ♻️[Knowledge] から取り込む（別途 seed）。
--   - 1 supplier = 1 prompt（UNIQUE(supplier_id)）
--   - public 中央マスタ（tenant_id を持たない。public.suppliers と同様）
--
-- 冪等: CREATE TABLE / INDEX IF NOT EXISTS。
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.supplier_prompts (
    id          SERIAL PRIMARY KEY,
    supplier_id INTEGER NOT NULL UNIQUE
                REFERENCES public.suppliers(id) ON DELETE CASCADE,
    prompt      TEXT NOT NULL DEFAULT '',
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    updated_by  INTEGER,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_supplier_prompts_supplier
    ON public.supplier_prompts (supplier_id);

CREATE OR REPLACE FUNCTION public.set_updated_at_supplier_prompts()
RETURNS TRIGGER AS $upd$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$upd$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_set_updated_at_supplier_prompts ON public.supplier_prompts;
CREATE TRIGGER trigger_set_updated_at_supplier_prompts
    BEFORE UPDATE ON public.supplier_prompts
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at_supplier_prompts();

COMMENT ON TABLE public.supplier_prompts IS
    'ADR-085: 仕入先別 Gemini 解析プロンプト。API解析シート 6行目(Knowledge)由来。';

-- ============================================================================
-- Rollback:
--   DROP TRIGGER IF EXISTS trigger_set_updated_at_supplier_prompts ON public.supplier_prompts;
--   DROP FUNCTION IF EXISTS public.set_updated_at_supplier_prompts();
--   DROP TABLE IF EXISTS public.supplier_prompts;
-- ============================================================================
