-- ============================================================================
-- !! 警告 !! このSQLファイルは **テンプレート** です。
-- {schema}, {tenant_id} のプレースホルダを含むため、
-- そのまま psql で実行するとシンタックスエラーになります。
--
-- 必ず scripts/migrate_adr021_sprint2_financials.py 経由で実行してください:
--   docker compose exec backend python /app/scripts/migrate_adr021_sprint2_financials.py
-- ============================================================================
--
-- ADR-021 Phase 2 / Sprint 2 / Migration 047: order_financials テーブル新設
--
-- 目的:
--   ADR-021 第 4 節「売上計算とレポート」AC-004 を最小実装する。
--   受注ごとに売上情報（売上高 / 仕入原価 / 各種手数料 / 利益率）を構造化テーブルに記録し、
--   Phase 5（報酬計算）で必要となる commission_base_amount フィールドも本 Sprint で先取り。
--   OrderFlow Manager の「売上情報」27 列を本テーブルへ分解する。
--
-- 設計:
--   - 1 受注 = 1 売上情報（order_id UNIQUE / ON DELETE CASCADE）
--   - 全金額カラムは NUMERIC(14,2) JPY 換算前提（多通貨は本 Sprint スコープ外）
--   - 導出列（cost_total / gross_profit / gross_profit_rate /
--     operating_profit_with_tax_refund）は DB ではなく Python 側で計算
--   - tenant_id 列は RLS 用（既存の per-tenant スキーマ分離との二重防御）
--
-- 冪等性:
--   - CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS で再実行 no-op
--
-- 変更履歴:
--   2026-05-11: 初版（ADR-021 Phase 2 / Sprint 2）
-- ============================================================================

CREATE TABLE IF NOT EXISTS {schema}.order_financials (
    id SERIAL PRIMARY KEY,
    order_id INTEGER NOT NULL UNIQUE
        REFERENCES {schema}.orders(id) ON DELETE CASCADE,
    tenant_id INTEGER NOT NULL DEFAULT {tenant_id},

    -- 売上 / 仕入 / 各種手数料（OrderFlow EP 列ベース、JPY 換算済前提）
    revenue_amount         NUMERIC(14, 2) DEFAULT 0,  -- 売上高
    purchase_cost          NUMERIC(14, 2) DEFAULT 0,  -- 仕入原価
    purchase_shipping      NUMERIC(14, 2) DEFAULT 0,  -- 仕入送料
    paypal_fee             NUMERIC(14, 2) DEFAULT 0,
    wise_fee               NUMERIC(14, 2) DEFAULT 0,
    exchange_fee           NUMERIC(14, 2) DEFAULT 0,  -- 為替手数料
    outsource_fee          NUMERIC(14, 2) DEFAULT 0,  -- 外注費
    packing_fee            NUMERIC(14, 2) DEFAULT 0,  -- 荷造運賃
    ad_cost                NUMERIC(14, 2) DEFAULT 0,  -- 広告費
    return_fee             NUMERIC(14, 2) DEFAULT 0,  -- 返送料
    refund_amount          NUMERIC(14, 2) DEFAULT 0,  -- 返金額
    commission_base_amount NUMERIC(14, 2) DEFAULT 0,  -- Phase 5 報酬計算ベース額（OrderFlow EP 列 = SALES_INCENTIVE 相当）
    tax_refund             NUMERIC(14, 2) DEFAULT 0,  -- 消費税還付

    notes TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 索引
-- order_id は UNIQUE 制約で自動 index されるが、明示的に貼って named index にする
CREATE UNIQUE INDEX IF NOT EXISTS uq_order_financials_tenant_order
    ON {schema}.order_financials (tenant_id, order_id);
CREATE INDEX IF NOT EXISTS idx_order_financials_tenant
    ON {schema}.order_financials (tenant_id);
CREATE INDEX IF NOT EXISTS idx_order_financials_order
    ON {schema}.order_financials (order_id);

-- 月次集計用に created_at で範囲索引（将来 receipts テーブルが受注 → 月次の集計を担うが、
-- 本 Sprint では financials.created_at で代替）
CREATE INDEX IF NOT EXISTS idx_order_financials_created_at
    ON {schema}.order_financials (created_at);

-- updated_at 自動更新トリガー（既存パターンに倣う）
CREATE OR REPLACE FUNCTION {schema}.set_updated_at_order_financials()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_set_updated_at_order_financials
    ON {schema}.order_financials;

CREATE TRIGGER trigger_set_updated_at_order_financials
    BEFORE UPDATE ON {schema}.order_financials
    FOR EACH ROW
    EXECUTE FUNCTION {schema}.set_updated_at_order_financials();

-- RLS 有効化（既存テナントテーブル群と同じ tenant_id ベース ポリシー）
ALTER TABLE {schema}.order_financials ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = '{schema}'
          AND tablename = 'order_financials'
          AND policyname = 'tenant_isolation_order_financials'
    ) THEN
        EXECUTE format(
            'CREATE POLICY tenant_isolation_order_financials ON %I.order_financials '
            'USING (tenant_id = public.current_tenant_id())',
            '{schema}'
        );
    END IF;
END
$$;
