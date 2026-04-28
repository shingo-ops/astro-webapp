-- Phase 1-C M-MVP / Migration 038:
-- products テーブルに TCG B2B 輸出向け 11 列を追加する。
--
-- 経緯:
--   docs/products_design.md §5-1（M-MVP スコープ）に基づく実装。
--   しんごさんから 2026-04-28 に Q4 / Q5 / Q9 への確定回答を受領。
--     Q4: TCG 命名規則用列追加 OK（card_number, expansion_code, rarity, language）
--     Q5: 画像 URL 単一列で OK（image_url、Phase 2 で副テーブル化）
--     Q9: 削除 API は FK 参照あり時 409 + アーカイブ推奨に変更 OK
--
-- 追加列:
--   1. jan_code             VARCHAR(20)   -- JAN/EAN コード
--   2. card_number          VARCHAR(50)   -- TCG カード番号 (例 SV1a-001/073)
--   3. expansion_code       VARCHAR(20)   -- 拡張パック略号
--   4. rarity               VARCHAR(20)   -- レアリティ (C/U/R/SR/UR/SAR 等)
--   5. language             VARCHAR(10)   -- 言語版 (ja/en/kr 等)
--   6. unit_price_usd       NUMERIC(15,2) -- USD 建て参考価格
--   7. unit_price_eur       NUMERIC(15,2) -- EUR 建て参考価格
--   8. image_url            VARCHAR(500)  -- 商品画像 URL
--   9. is_archived          BOOLEAN       -- 廃番論理削除フラグ
--  10. archived_at          TIMESTAMPTZ   -- 廃番日時
--  11. supplier_default_id  INTEGER       -- 既定仕入先 (FK suppliers)
--
-- 索引:
--   - uq_products_tenant_code: PARTIAL UNIQUE (tenant_id, product_code) WHERE product_code IS NOT NULL
--   - uq_products_tenant_jan:  PARTIAL UNIQUE (tenant_id, jan_code)     WHERE jan_code IS NOT NULL
--   - idx_products_archived:           (is_archived)
--   - idx_products_card_number:        (card_number)    PARTIAL
--   - idx_products_expansion:          (expansion_code) PARTIAL
--
-- 冪等性:
--   - ADD COLUMN IF NOT EXISTS で再実行 no-op
--   - CREATE INDEX IF NOT EXISTS で再実行 no-op
--   - 全列 NULL 許可、is_archived のみ DEFAULT FALSE
--   - 既存データへの影響なし（backfill は別 migration 041 / 042 で M3 以降）
--
-- 副テーブル (product_inventory, product_supplier_mappings) は Q3 / Q6 解消後の
-- M3 / M4 で別 migration として投入する。本 M-MVP のスコープ外。
--
-- 依存: migration 005 (products テーブル本体), suppliers テーブル存在
--
-- 作成日: 2026-04-28 (Phase 1-C M-MVP)

DO $$
DECLARE
    schema_rec RECORD;
    applied_count INTEGER := 0;
    skipped_no_table INTEGER := 0;
BEGIN
    FOR schema_rec IN
        SELECT nspname FROM pg_namespace
        WHERE nspname ~ '^tenant_\d+$'
        ORDER BY nspname
    LOOP
        -- 前提: products と suppliers テーブルが存在すること
        IF NOT EXISTS (
            SELECT 1 FROM pg_tables
            WHERE schemaname = schema_rec.nspname
              AND tablename = 'products'
        ) THEN
            skipped_no_table := skipped_no_table + 1;
            CONTINUE;
        END IF;

        -- 11 列 ADD COLUMN（IF NOT EXISTS で冪等）
        EXECUTE format('ALTER TABLE %I.products ADD COLUMN IF NOT EXISTS jan_code VARCHAR(20)', schema_rec.nspname);
        EXECUTE format('ALTER TABLE %I.products ADD COLUMN IF NOT EXISTS card_number VARCHAR(50)', schema_rec.nspname);
        EXECUTE format('ALTER TABLE %I.products ADD COLUMN IF NOT EXISTS expansion_code VARCHAR(20)', schema_rec.nspname);
        EXECUTE format('ALTER TABLE %I.products ADD COLUMN IF NOT EXISTS rarity VARCHAR(20)', schema_rec.nspname);
        EXECUTE format('ALTER TABLE %I.products ADD COLUMN IF NOT EXISTS language VARCHAR(10)', schema_rec.nspname);
        EXECUTE format('ALTER TABLE %I.products ADD COLUMN IF NOT EXISTS unit_price_usd NUMERIC(15, 2)', schema_rec.nspname);
        EXECUTE format('ALTER TABLE %I.products ADD COLUMN IF NOT EXISTS unit_price_eur NUMERIC(15, 2)', schema_rec.nspname);
        EXECUTE format('ALTER TABLE %I.products ADD COLUMN IF NOT EXISTS image_url VARCHAR(500)', schema_rec.nspname);
        EXECUTE format('ALTER TABLE %I.products ADD COLUMN IF NOT EXISTS is_archived BOOLEAN DEFAULT FALSE', schema_rec.nspname);
        EXECUTE format('ALTER TABLE %I.products ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ', schema_rec.nspname);

        -- supplier_default_id は suppliers が存在する場合のみ FK 付きで追加
        IF EXISTS (
            SELECT 1 FROM pg_tables
            WHERE schemaname = schema_rec.nspname AND tablename = 'suppliers'
        ) THEN
            EXECUTE format(
                'ALTER TABLE %I.products ADD COLUMN IF NOT EXISTS supplier_default_id INTEGER REFERENCES %I.suppliers(id)',
                schema_rec.nspname, schema_rec.nspname
            );
        ELSE
            EXECUTE format(
                'ALTER TABLE %I.products ADD COLUMN IF NOT EXISTS supplier_default_id INTEGER',
                schema_rec.nspname
            );
            RAISE NOTICE 'migration 038: %: suppliers が無いため supplier_default_id は FK 無しで追加', schema_rec.nspname;
        END IF;

        -- UNIQUE INDEX（PARTIAL、NULL は重複検出から除外）
        EXECUTE format(
            'CREATE UNIQUE INDEX IF NOT EXISTS uq_products_tenant_code ON %I.products (tenant_id, product_code) WHERE product_code IS NOT NULL',
            schema_rec.nspname
        );
        EXECUTE format(
            'CREATE UNIQUE INDEX IF NOT EXISTS uq_products_tenant_jan ON %I.products (tenant_id, jan_code) WHERE jan_code IS NOT NULL',
            schema_rec.nspname
        );

        -- 検索用 INDEX
        EXECUTE format(
            'CREATE INDEX IF NOT EXISTS idx_products_archived ON %I.products (is_archived)',
            schema_rec.nspname
        );
        EXECUTE format(
            'CREATE INDEX IF NOT EXISTS idx_products_card_number ON %I.products (card_number) WHERE card_number IS NOT NULL',
            schema_rec.nspname
        );
        EXECUTE format(
            'CREATE INDEX IF NOT EXISTS idx_products_expansion ON %I.products (expansion_code) WHERE expansion_code IS NOT NULL',
            schema_rec.nspname
        );

        applied_count := applied_count + 1;
        RAISE NOTICE 'migration 038: %: products に Phase 1-C 11 列 + 5 索引を追加', schema_rec.nspname;
    END LOOP;

    RAISE NOTICE
        'migration 038: 完了。適用 % テナント、products 未存在 % テナント',
        applied_count, skipped_no_table;
END $$;

-- =====================================================================
-- Rollback 手順（緊急時のみ手動実行）:
--
-- DO $$
-- DECLARE r RECORD;
-- BEGIN
--     FOR r IN SELECT nspname FROM pg_namespace WHERE nspname ~ '^tenant_\d+$'
--     LOOP
--         IF NOT EXISTS (SELECT 1 FROM pg_tables WHERE schemaname = r.nspname AND tablename = 'products') THEN
--             CONTINUE;
--         END IF;
--         EXECUTE format('DROP INDEX IF EXISTS %I.idx_products_expansion', r.nspname);
--         EXECUTE format('DROP INDEX IF EXISTS %I.idx_products_card_number', r.nspname);
--         EXECUTE format('DROP INDEX IF EXISTS %I.idx_products_archived', r.nspname);
--         EXECUTE format('DROP INDEX IF EXISTS %I.uq_products_tenant_jan', r.nspname);
--         EXECUTE format('DROP INDEX IF EXISTS %I.uq_products_tenant_code', r.nspname);
--         EXECUTE format('ALTER TABLE %I.products DROP COLUMN IF EXISTS supplier_default_id', r.nspname);
--         EXECUTE format('ALTER TABLE %I.products DROP COLUMN IF EXISTS archived_at', r.nspname);
--         EXECUTE format('ALTER TABLE %I.products DROP COLUMN IF EXISTS is_archived', r.nspname);
--         EXECUTE format('ALTER TABLE %I.products DROP COLUMN IF EXISTS image_url', r.nspname);
--         EXECUTE format('ALTER TABLE %I.products DROP COLUMN IF EXISTS unit_price_eur', r.nspname);
--         EXECUTE format('ALTER TABLE %I.products DROP COLUMN IF EXISTS unit_price_usd', r.nspname);
--         EXECUTE format('ALTER TABLE %I.products DROP COLUMN IF EXISTS language', r.nspname);
--         EXECUTE format('ALTER TABLE %I.products DROP COLUMN IF EXISTS rarity', r.nspname);
--         EXECUTE format('ALTER TABLE %I.products DROP COLUMN IF EXISTS expansion_code', r.nspname);
--         EXECUTE format('ALTER TABLE %I.products DROP COLUMN IF EXISTS card_number', r.nspname);
--         EXECUTE format('ALTER TABLE %I.products DROP COLUMN IF EXISTS jan_code', r.nspname);
--     END LOOP;
-- END $$;
-- =====================================================================
