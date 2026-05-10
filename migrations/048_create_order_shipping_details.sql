-- ============================================================================
-- !! 警告 !! このSQLファイルは **テンプレート** です。
-- {schema}, {tenant_id} のプレースホルダを含むため、
-- そのまま psql で実行するとシンタックスエラーになります。
--
-- 必ず scripts/migrate_adr021_sprint3_shipping.py 経由で実行してください:
--   docker compose exec backend python /app/scripts/migrate_adr021_sprint3_shipping.py
-- ============================================================================
--
-- ADR-021 Phase 3 / Sprint 3 / Migration 048: order_shipping_details テーブル新設
--
-- 目的:
--   ADR-021 第 3 節「発送情報の登録と外部システム連携」AC-003 を最小実装する。
--   OrderFlow Manager の「発送情報」27-85 列 + 「elogi連携」56-76 列を本テーブルへ
--   分解し、eLogi CSV 出力を eLogi 既存フォーマット互換で実現する。
--   後続キャリア追加（DHL / FedEx / ヤマト）に拡張できる adapter 層と組み合わせる。
--
-- 設計:
--   - 1 受注 = 1 発送情報（order_id UNIQUE / ON DELETE CASCADE）
--   - 全カラム NULL 可（最低限 order_id のみ必須）。発送ワークフローの段階入力に対応。
--   - 寸法・重量・金額は NUMERIC（cm / kg / USD）。為替換算は本 Sprint 範囲外。
--   - tenant_id 列は RLS 用（既存の per-tenant スキーマ分離との二重防御）
--   - carrier は CHECK 制約付き enum（'elogi' / 'fedex' / 'dhl' / 'yamato' / 'other'）。
--     adapter 層は subclass で簡単に拡張できる構造（実装は本 Sprint では eLogi のみ）
--
-- 冪等性:
--   - CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS で再実行 no-op
--
-- 変更履歴:
--   2026-05-11: 初版（ADR-021 Phase 3 / Sprint 3）
-- ============================================================================

CREATE TABLE IF NOT EXISTS {schema}.order_shipping_details (
    id SERIAL PRIMARY KEY,
    order_id INTEGER NOT NULL UNIQUE
        REFERENCES {schema}.orders(id) ON DELETE CASCADE,
    tenant_id INTEGER NOT NULL DEFAULT {tenant_id},

    -- 受取人
    recipient_name VARCHAR(255),
    phone          VARCHAR(50),
    email          VARCHAR(255),
    tax_number     VARCHAR(100),

    -- 住所
    address1     VARCHAR(255),
    address2     VARCHAR(255),
    address3     VARCHAR(255),
    city         VARCHAR(100),
    state_code   VARCHAR(20),
    zip_code     VARCHAR(50),
    country_code VARCHAR(10),

    -- 寸法・重量
    length_cm  NUMERIC(8, 2),
    width_cm   NUMERIC(8, 2),
    height_cm  NUMERIC(8, 2),
    weight_kg  NUMERIC(8, 3),
    volume_g   NUMERIC(10, 2),
    box_count  INTEGER,

    -- 梱包
    packing_memo      TEXT,
    packing_type      VARCHAR(50),
    inspection_status VARCHAR(50),

    -- 品目
    item_description VARCHAR(500),
    item_price_usd   NUMERIC(12, 2),
    exchange_rate    NUMERIC(12, 6),
    hs_code          VARCHAR(50),
    tax_id           VARCHAR(100),
    fedex_id         VARCHAR(100),

    -- 配送
    carrier           VARCHAR(20)
        CHECK (carrier IS NULL OR carrier IN ('elogi', 'fedex', 'dhl', 'yamato', 'other')),
    ship_method       VARCHAR(50),
    ship_date         DATE,
    tracking_number   VARCHAR(200),
    est_shipping_fee  NUMERIC(12, 2),

    -- ステータス
    label_issued_at     TIMESTAMPTZ,
    pickup_requested_at TIMESTAMPTZ,
    shipped_at          TIMESTAMPTZ,
    notified_at         TIMESTAMPTZ,

    -- メモ
    ship_memo TEXT,

    -- 標準
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 索引
-- order_id は UNIQUE 制約で自動 index されるが、tenant_id との複合 UNIQUE で
-- マルチテナント防御を二重化する（migration 047 と同じパターン）。
CREATE UNIQUE INDEX IF NOT EXISTS uq_order_shipping_details_tenant_order
    ON {schema}.order_shipping_details (tenant_id, order_id);
CREATE INDEX IF NOT EXISTS idx_order_shipping_details_tenant
    ON {schema}.order_shipping_details (tenant_id);
CREATE INDEX IF NOT EXISTS idx_order_shipping_details_order
    ON {schema}.order_shipping_details (order_id);
CREATE INDEX IF NOT EXISTS idx_order_shipping_details_carrier
    ON {schema}.order_shipping_details (carrier);
CREATE INDEX IF NOT EXISTS idx_order_shipping_details_tracking
    ON {schema}.order_shipping_details (tracking_number);

-- updated_at 自動更新トリガー（既存パターンに倣う）
CREATE OR REPLACE FUNCTION {schema}.set_updated_at_order_shipping_details()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_set_updated_at_order_shipping_details
    ON {schema}.order_shipping_details;

CREATE TRIGGER trigger_set_updated_at_order_shipping_details
    BEFORE UPDATE ON {schema}.order_shipping_details
    FOR EACH ROW
    EXECUTE FUNCTION {schema}.set_updated_at_order_shipping_details();

-- RLS 有効化（既存テナントテーブル群と同じ tenant_id ベース ポリシー）
ALTER TABLE {schema}.order_shipping_details ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = '{schema}'
          AND tablename = 'order_shipping_details'
          AND policyname = 'tenant_isolation_order_shipping_details'
    ) THEN
        EXECUTE format(
            'CREATE POLICY tenant_isolation_order_shipping_details ON %I.order_shipping_details '
            'USING (tenant_id = public.current_tenant_id())',
            '{schema}'
        );
    END IF;
END
$$;
