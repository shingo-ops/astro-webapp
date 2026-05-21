-- ============================================================================
-- Migration 056: 仕入元(suppliers)を public schema にプロモートし、
--                supplier_type / default_language 列を追加（マーケットプレイス型）
--
-- 経緯:
--   spec.md v1.1 (2026-05-21) Sprint 1 / F1 / A4+A6 確定:
--     - A4: suppliers.supplier_type ENUM('individual','corporate')
--     - A6: 在庫・商品マスタ・仕入元・正規化辞書は public schema 中央共有
--   既存 spec の migration 番号 047〜054 を計画していたが、develop 着手時に
--   047〜055 が既に他 ADR で使用済みのため 056 から付番し直し（spec.md 注記参照）。
--
-- 変更内容:
--   1. public.suppliers テーブル新規作成（{tenant_xxx}.suppliers と並存、Phase C で
--      旧テーブルは VIEW 化または DROP の判断。Sprint 1 では並存のみ）
--   2. supplier_type CHECK 制約: ('individual','corporate')
--   3. default_language CHAR(2) DEFAULT 'ja'
--   4. 既存 tenant_004.suppliers のデータを public.suppliers へ INITIAL コピー
--      （冪等: ON CONFLICT DO NOTHING で重複行は skip）
--   5. supplier_type 初期値は 'corporate' 仮置き（admin が UI で個別修正、A4 確定）
--
-- マーケットプレイス型の含意:
--   - public.suppliers には tenant_id 列を **持たない**（中央共有マスタ）
--   - 既存 {tenant_xxx}.suppliers は Sprint 1 では **温存**（destructive 操作禁止）
--   - F8 (Sprint 8) で PO PDF が public.suppliers を参照するように切替時に旧テーブル評価
--
-- ADR-034 観点:
--   public schema migration のため deploy.yml では **1 回のみ実行**。
--   テナント別ループの中ではない。
--
-- 冪等性:
--   - CREATE TABLE IF NOT EXISTS / ADD COLUMN IF NOT EXISTS / CREATE INDEX IF NOT EXISTS
--   - INSERT INTO ... ON CONFLICT (id) DO NOTHING で再投入安全
--
-- 関連:
--   migrations/007_add_phase3_tenant_tables.sql (旧 {tenant_xxx}.suppliers 定義)
--   docs/adr/ADR-034 (新規テナント migration 自動適用)
--   .claude-pipeline/spec.md F1
--
-- 作成日: 2026-05-21
-- ============================================================================

-- === 1. public.suppliers テーブル新規作成 ===
CREATE TABLE IF NOT EXISTS public.suppliers (
    id                  SERIAL PRIMARY KEY,
    supplier_code       VARCHAR(20) UNIQUE,
    name                VARCHAR(255) NOT NULL,
    supplier_type       VARCHAR(20) NOT NULL DEFAULT 'corporate',
    default_language    CHAR(2)     NOT NULL DEFAULT 'ja',
    contact_name        VARCHAR(255),
    email               VARCHAR(255),
    phone               VARCHAR(50),
    address             TEXT,
    notes               TEXT,
    is_active           BOOLEAN     NOT NULL DEFAULT TRUE,
    created_by          INTEGER,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- supplier_type CHECK 制約（A4 確定: individual / corporate のみ）
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'suppliers_supplier_type_check'
          AND conrelid = 'public.suppliers'::regclass
    ) THEN
        ALTER TABLE public.suppliers
            ADD CONSTRAINT suppliers_supplier_type_check
            CHECK (supplier_type IN ('individual', 'corporate'));
    END IF;
END $$;

-- default_language CHECK 制約（ISO 639-1: ja / en 等の 2 文字）
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'suppliers_default_language_check'
          AND conrelid = 'public.suppliers'::regclass
    ) THEN
        ALTER TABLE public.suppliers
            ADD CONSTRAINT suppliers_default_language_check
            CHECK (default_language IN ('ja', 'en', 'ko', 'zh'));
    END IF;
END $$;

-- 索引
CREATE INDEX IF NOT EXISTS idx_public_suppliers_active     ON public.suppliers (is_active);
CREATE INDEX IF NOT EXISTS idx_public_suppliers_type       ON public.suppliers (supplier_type);
CREATE INDEX IF NOT EXISTS idx_public_suppliers_name       ON public.suppliers (name);

COMMENT ON TABLE  public.suppliers IS 'spec F1 / A6 マーケットプレイス型: 仕入元マスタ（全テナント共有、Jarvis 運用 admin のみ書込）';
COMMENT ON COLUMN public.suppliers.supplier_type    IS 'A4 確定: individual / corporate。PO PDF 敬称分岐に使用（F8）';
COMMENT ON COLUMN public.suppliers.default_language IS 'PO PDF / メール送信時の既定言語。alias 解決の言語選択にも使用（F8 AC8.4）';

-- === 2. 既存 {tenant_xxx}.suppliers から public.suppliers へ INITIAL コピー ===
-- 既存 tenant_004 / tenant_006 等の suppliers 行を public.suppliers にプロモート。
-- 重複なし: public.suppliers.id は SERIAL なので衝突しない（id は再採番）。
-- 衝突回避: supplier_code がある場合のみ UNIQUE 制約で重複検出、ON CONFLICT で skip。
-- supplier_type は spec A4 で 'corporate' を仮置き（admin が後で UI 修正）。
DO $promote$
DECLARE
    schema_rec RECORD;
    insert_count INTEGER;
    total_inserted INTEGER := 0;
BEGIN
    FOR schema_rec IN
        SELECT nspname FROM pg_namespace
        WHERE nspname ~ '^tenant_\d+$'
        ORDER BY nspname
    LOOP
        -- {tenant_xxx}.suppliers が存在しない schema は skip
        IF NOT EXISTS (
            SELECT 1 FROM pg_tables
            WHERE schemaname = schema_rec.nspname AND tablename = 'suppliers'
        ) THEN
            CONTINUE;
        END IF;

        -- supplier_code が重複しないものだけ insert（idempotent）
        EXECUTE format($f$
            INSERT INTO public.suppliers
                (supplier_code, name, supplier_type, default_language,
                 contact_name, email, phone, address, notes, is_active,
                 created_at, updated_at)
            SELECT
                src.supplier_code,
                src.name,
                'corporate' AS supplier_type,   -- A4 初期値、admin UI で個別修正
                'ja'        AS default_language,
                src.contact_name,
                src.email,
                src.phone,
                src.address,
                src.notes,
                COALESCE(src.is_active, TRUE),
                COALESCE(src.created_at, NOW()),
                COALESCE(src.updated_at, NOW())
            FROM %I.suppliers src
            WHERE src.supplier_code IS NOT NULL
            ON CONFLICT (supplier_code) DO NOTHING
        $f$, schema_rec.nspname);

        GET DIAGNOSTICS insert_count = ROW_COUNT;
        total_inserted := total_inserted + insert_count;
        RAISE NOTICE 'migration 056: %: % 仕入元行を public.suppliers にプロモート',
            schema_rec.nspname, insert_count;
    END LOOP;
    RAISE NOTICE 'migration 056: 全体で % 仕入元行をプロモート (supplier_type=corporate 初期値)',
        total_inserted;
END $promote$;

-- === 3. updated_at 自動更新トリガ ===
CREATE OR REPLACE FUNCTION public.set_updated_at_suppliers()
RETURNS TRIGGER AS $upd$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$upd$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_set_updated_at_public_suppliers ON public.suppliers;
CREATE TRIGGER trigger_set_updated_at_public_suppliers
    BEFORE UPDATE ON public.suppliers
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at_suppliers();

-- ============================================================================
-- Rollback 手順（緊急時のみ手動実行、注意: 既存 {tenant_xxx}.suppliers のデータ
--   は **温存** されているため、public.suppliers を drop しても本番影響なし）:
--
-- DROP TRIGGER IF EXISTS trigger_set_updated_at_public_suppliers ON public.suppliers;
-- DROP FUNCTION IF EXISTS public.set_updated_at_suppliers();
-- DROP TABLE IF EXISTS public.suppliers;
-- ============================================================================
