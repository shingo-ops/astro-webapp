-- ============================================================================
-- !! 警告 !! 警告 !! 警告 !!
--
-- このSQLファイルは **テンプレート** です。`{schema}`, `{schema_raw}`,
-- `{tenant_id}` のプレースホルダを含むため、そのまま psql 等で実行すると
-- シンタックスエラーになります。
--
-- 必ず scripts/migrate_phase1_redesign.py 経由で実行してください。
-- （同ランナーは本 Phase 1 再設計専用。既存 migrate_phase1.py とは別）
--
-- ============================================================================
--
-- Phase 1 再設計 / Migration 015: customers 系スキーマの完全置換
--
-- 内容:
--   [前段] 既存 customers を参照しているテーブル（quotes / invoices）の
--          サンプルデータを TRUNCATE し、FK 制約を一時的に DROP する
--   [1] 既存 customers を customers_legacy_{tenant_id} へリネーム退避
--   [2] 新 customers 本体テーブル作成（設計書 4-2 / migrate_customers.md §3-1）
--   [3] customer_addresses 副テーブル作成（billing/delivery の2行）
--   [4] customer_sales_channels 副テーブル作成（複数チャネル対応）
--   [5] customer_discord 副テーブル作成（任意の1対1）
--   [6] updated_at トリガ関数 + 各テーブルへのトリガ登録
--
-- 既存参照テーブルへの FK 再付与は migration 017 で実施。
-- RLS ポリシー設定は migration 016 で実施。
--
-- 前提:
--   - 014 で public.current_tenant_id() 関数が作成済み
--   - 内部テスト中止決定済、VPS 本番 DB の customers/quotes/invoices は
--     サンプル扱いで TRUNCATE OK（2026-04-23 しんごさん確認）
--   - customer_id 採番は原本 CSV 投入時の新ID。既存 quotes/invoices 参照
--     データとの紐付けは成り立たないため TRUNCATE する
--
-- 変更履歴:
--   2026-04-23: 初版作成（Phase 1 再設計）

-- === [前段] 既存 FK を一時的に DROP + 依存テーブルのサンプルデータ TRUNCATE ===

-- quotes.customer_id が customers(id) を参照している FK を特定して DROP
DO $$
DECLARE
    fk_name TEXT;
BEGIN
    SELECT conname INTO fk_name
    FROM pg_constraint
    WHERE contype = 'f'
      AND conrelid = '{schema}.quotes'::regclass
      AND confrelid = '{schema}.customers'::regclass;
    IF fk_name IS NOT NULL THEN
        EXECUTE format('ALTER TABLE {schema}.quotes DROP CONSTRAINT %I', fk_name);
    END IF;
END $$;

-- invoices.customer_id が customers(id) を参照している FK を特定して DROP
DO $$
DECLARE
    fk_name TEXT;
BEGIN
    SELECT conname INTO fk_name
    FROM pg_constraint
    WHERE contype = 'f'
      AND conrelid = '{schema}.invoices'::regclass
      AND confrelid = '{schema}.customers'::regclass;
    IF fk_name IS NOT NULL THEN
        EXECUTE format('ALTER TABLE {schema}.invoices DROP CONSTRAINT %I', fk_name);
    END IF;
END $$;

-- サンプルデータの TRUNCATE（CASCADE で quote_items / invoice_items も消える）
-- 内部テスト中止済・本番データはサンプル扱いのため問題なし
TRUNCATE TABLE {schema}.quotes CASCADE;
TRUNCATE TABLE {schema}.invoices CASCADE;

-- === [1] 既存 customers を退避 ===

ALTER TABLE IF EXISTS {schema}.customers RENAME TO customers_legacy_{tenant_id};

COMMENT ON TABLE {schema}.customers_legacy_{tenant_id} IS
  'Phase 1 再設計（2026-04-23）で退避した旧 customers。サンプル扱いだが万一の復旧用に保持。新customers安定稼働後に DROP する予定';

-- === [2] 新 customers 本体テーブル ===

CREATE TABLE {schema}.customers (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL DEFAULT {tenant_id},
    customer_code VARCHAR(20) NOT NULL,                -- CT-00001 形式。原本CSV値を保持
    lead_id INTEGER REFERENCES {schema}.leads(id),     -- 出自リード（nullable、直接契約は NULL）
    sales_rep_id INTEGER,                              -- {schema}.staff(id) への参照（staff テーブルは 019 で作成のため FK は後付け）
    company_name VARCHAR(255),
    trust_level SMALLINT CHECK (trust_level IS NULL OR trust_level BETWEEN 1 AND 5),
    priority_focus VARCHAR(50),                        -- 価格重視／信頼重視／品質重視 等
    per_order_amount NUMERIC(15,2),                    -- 1回発注額（営業見込み、手入力）
    monthly_frequency SMALLINT,                        -- 月間頻度（営業見込み、手入力）
    monthly_forecast NUMERIC(15,2),                    -- 月間売上見込額。新規=営業見込み、既存=AI分析上書き
    monthly_forecast_source VARCHAR(20)
        CHECK (monthly_forecast_source IS NULL OR monthly_forecast_source IN ('manual','ai_analysis')),
    monthly_forecast_updated_at TIMESTAMPTZ,           -- 最終更新日時
    meeting_requested BOOLEAN NOT NULL DEFAULT FALSE,
    billing_display_name VARCHAR(255),                 -- 請求書の宛名（B Name由来）
    payment_recipient_name VARCHAR(255),               -- 支払い名義（WISE/PayPal 送金時の名義）
    fedex_account VARCHAR(100),
    shipping_note TEXT,
    primary_contact_channel VARCHAR(30),               -- 主連絡ツール（whatsapp/discord/messenger/line/instagram/facebook/referral 等）
    status VARCHAR(20) NOT NULL DEFAULT 'active'
        CHECK (status IN ('active','inactive','archived','pending_dedup_review')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, customer_code)
);

CREATE INDEX idx_customers_tenant_id ON {schema}.customers (tenant_id);
CREATE INDEX idx_customers_lead_id ON {schema}.customers (lead_id);
CREATE INDEX idx_customers_sales_rep_id ON {schema}.customers (sales_rep_id);
CREATE INDEX idx_customers_status ON {schema}.customers (status);

COMMENT ON TABLE {schema}.customers IS
  'Phase 1 再設計で正規化された顧客本体。billing/delivery 住所・販売チャネル・Discord連携は副テーブルに分離';
COMMENT ON COLUMN {schema}.customers.billing_display_name IS
  '請求書の宛名。B Name列由来。会社名と別にする場合のみ入力';
COMMENT ON COLUMN {schema}.customers.payment_recipient_name IS
  'WISE/PayPal送金時の名義。billing_display_name と異なる場合のみ入力';
COMMENT ON COLUMN {schema}.customers.monthly_forecast IS
  '月間売上見込額。新規商談時は営業が per_order_amount×monthly_frequency の見込みを手入力、既存顧客はAIが sales_orders 履歴から定期分析して上書き';
COMMENT ON COLUMN {schema}.customers.monthly_forecast_source IS
  'manual=営業手入力／ai_analysis=AI履歴分析';
COMMENT ON COLUMN {schema}.customers.primary_contact_channel IS
  '主連絡ツール。併用運用が顕在化したら customer_contact_channels 副テーブル追加を検討';
COMMENT ON COLUMN {schema}.customers.status IS
  'active/inactive/archived/pending_dedup_review。pending_dedup_review は CT-00030/00032 のような重複候補を先行投入する際のタグ';

-- === [3] customer_addresses（請求先・配送先） ===

CREATE TABLE {schema}.customer_addresses (
    id SERIAL PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES {schema}.customers(id) ON DELETE CASCADE,
    address_type VARCHAR(20) NOT NULL
        CHECK (address_type IN ('billing','delivery')),
    name VARCHAR(255),
    email VARCHAR(255),
    telephone VARCHAR(50),
    tax_id VARCHAR(100),
    address_line_1 VARCHAR(255),
    address_line_2 VARCHAR(255),
    address_line_3 VARCHAR(255),
    city VARCHAR(100),
    state VARCHAR(100),
    zip VARCHAR(50),
    country_code CHAR(2),                              -- ISO 3166-1 alpha-2
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_customer_addresses_customer_id ON {schema}.customer_addresses (customer_id);
CREATE INDEX idx_customer_addresses_type ON {schema}.customer_addresses (customer_id, address_type);

COMMENT ON COLUMN {schema}.customer_addresses.country_code IS
  'ISO 3166-1 alpha-2（JP, US, GB 等）。表記揺れは移行スクリプトで正規化';

-- === [4] customer_sales_channels（販売先チャネル） ===

CREATE TABLE {schema}.customer_sales_channels (
    customer_id INTEGER NOT NULL REFERENCES {schema}.customers(id) ON DELETE CASCADE,
    channel VARCHAR(30) NOT NULL,                      -- 実店舗/EC/配信/PF/自販機 等
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (customer_id, channel)
);

COMMENT ON TABLE {schema}.customer_sales_channels IS
  '顧客が運営する販売チャネル（1顧客に複数行）。連絡手段の customer.primary_contact_channel とは別概念';

-- === [5] customer_discord（Discord連携・任意） ===

CREATE TABLE {schema}.customer_discord (
    customer_id INTEGER PRIMARY KEY REFERENCES {schema}.customers(id) ON DELETE CASCADE,
    is_joined BOOLEAN NOT NULL DEFAULT FALSE,
    channel_id VARCHAR(50),
    user_id VARCHAR(50),
    invoice_webhook TEXT,
    shipment_webhook TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE {schema}.customer_discord IS
  'Discord を使う顧客のみ1行（スカスカ列を本体に入れないため副テーブル化）';

-- === [6] updated_at トリガ ===

CREATE OR REPLACE FUNCTION {schema}.trg_set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_customers_updated_at
    BEFORE UPDATE ON {schema}.customers
    FOR EACH ROW EXECUTE FUNCTION {schema}.trg_set_updated_at();

CREATE TRIGGER trg_customer_addresses_updated_at
    BEFORE UPDATE ON {schema}.customer_addresses
    FOR EACH ROW EXECUTE FUNCTION {schema}.trg_set_updated_at();

CREATE TRIGGER trg_customer_discord_updated_at
    BEFORE UPDATE ON {schema}.customer_discord
    FOR EACH ROW EXECUTE FUNCTION {schema}.trg_set_updated_at();
