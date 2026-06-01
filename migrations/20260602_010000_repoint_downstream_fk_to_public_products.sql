-- Migration 20260602_010000: ADR-090 PR2 — 下流 product_id FK を public.products へ張替え
--                                          + tenant 固有 products の public 中央への移行
--
-- 在庫表(/products)を public.products へ一本化（PR2 router 変更）するのに伴い、
-- 見積/請求/発注の明細 product_id 参照先を tenant_NNN.products → public.products へ張替える。
-- 全テナントの quote_items / invoice_items / purchase_order_items が **0 行**であることを
-- 移行前に確認済み（本番 tenant_004 含む）。よって参照データの再マップは不要、FK の定義変更のみ。
--
-- 冪等: 既に public FK があれば skip。pg_namespace 走査で全 tenant schema に適用
-- （テンプレートのプレースホルダは使わず、psql 直実行可能な DO ブロック形式）。

DO $$
DECLARE
    sch text;
    tbl text;
    fk_name text;
BEGIN
    FOR sch IN
        SELECT nspname FROM pg_namespace WHERE nspname ~ '^tenant_[0-9]+$'
    LOOP
        FOREACH tbl IN ARRAY ARRAY['quote_items', 'invoice_items', 'purchase_order_items']
        LOOP
            -- テーブル / product_id 列が無いテナントは skip
            IF to_regclass(sch || '.' || tbl) IS NULL THEN
                CONTINUE;
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = sch AND table_name = tbl AND column_name = 'product_id'
            ) THEN
                CONTINUE;
            END IF;

            -- 既存の product_id 外部キー（参照先が tenant products）を全て drop
            FOR fk_name IN
                SELECT conname FROM pg_constraint
                WHERE conrelid = (sch || '.' || tbl)::regclass
                  AND contype = 'f'
                  AND pg_get_constraintdef(oid) LIKE 'FOREIGN KEY (product_id)%'
            LOOP
                EXECUTE format('ALTER TABLE %I.%I DROP CONSTRAINT %I', sch, tbl, fk_name);
            END LOOP;

            -- public.products への FK を付与（冪等）。ON DELETE RESTRICT（router は事前に
            -- _check_product_references で 409 を返すため、FK はバックストップ）。
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = (sch || '.' || tbl)::regclass
                  AND contype = 'f'
                  AND conname = tbl || '_product_id_public_fkey'
            ) THEN
                EXECUTE format(
                    'ALTER TABLE %I.%I ADD CONSTRAINT %I FOREIGN KEY (product_id) '
                    'REFERENCES public.products(id) ON DELETE RESTRICT',
                    sch, tbl, tbl || '_product_id_public_fkey'
                );
            END IF;
        END LOOP;
    END LOOP;
END $$;

-- tenant_006（撮影/デモ）の products のうち public.products に名前一致が無いもの（5 件想定）を
-- public 中央へ移行する。冪等: name 完全一致が既にあれば skip。tenant_006 が無い環境（CI 等）は skip。
DO $$
BEGIN
    IF to_regclass('tenant_006.products') IS NOT NULL THEN
        INSERT INTO public.products (
            name, name_en, category, mark, status, condition,
            unit_price, stock_quantity, weight, notes, release_date,
            jan_code, card_number, expansion_code, rarity, language,
            unit_price_usd, unit_price_eur, image_url
        )
        SELECT
            tp.name_ja, tp.name_en, tp.category, tp.mark, tp.status, tp.condition,
            tp.unit_price, tp.quantity, tp.weight, tp.notes, tp.release_date,
            tp.jan_code, tp.card_number, tp.expansion_code, tp.rarity, tp.language,
            tp.unit_price_usd, tp.unit_price_eur, tp.image_url
        FROM tenant_006.products tp
        WHERE NOT EXISTS (
            SELECT 1 FROM public.products pp WHERE pp.name = tp.name_ja
        );
    END IF;
END $$;
