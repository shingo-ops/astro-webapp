-- ============================================================================
-- !! 警告 !! このSQLファイルは **テンプレート** です。
-- {schema}, {tenant_id} のプレースホルダを含むため、
-- そのまま psql で実行するとシンタックスエラーになります。
--
-- 必ず scripts/migrate_adr021_sprint4_purchase.py 経由で実行してください:
--   docker compose exec backend python /app/scripts/migrate_adr021_sprint4_purchase.py
-- ============================================================================
--
-- ADR-021 Phase 4 / Sprint 4 / Migration 049: order_purchase_details テーブル新設
--
-- 目的:
--   ADR-021 第 2 節「仕入れ情報の登録と進捗管理」AC-002 を最小実装する。
--   OrderFlow Manager の「仕入れ情報」（Config.gs col 86-99）を本テーブルへ
--   分解し、受注ごとに紐付ける。既存 purchase_orders テーブル（migration 007）
--   とは別系統（purchase_orders は Phase 3 の仕入伝票、本テーブルは受注 1 件
--   = 仕入情報 1 件で OrderFlow 互換）。統合は別 ADR で扱う。
--
-- 設計:
--   - 1 受注 = 1 仕入情報（order_id UNIQUE / ON DELETE CASCADE）
--   - 全カラム NULL 可（最低限 order_id のみ必須）。仕入ワークフローの段階入力に対応。
--   - 金額は NUMERIC(14,2) JPY 換算前提（多通貨は本 Sprint スコープ外）
--   - tenant_id 列は RLS 用（既存の per-tenant スキーマ分離との二重防御）
--   - purchase_status は OrderFlow Config.gs PURCHASE_STATUS と同じ「""(確認中) /
--     'confirmed'(確定済み)」の 2 値（拡張余地は将来 enum 化で吸収）
--   - purchase_staff は本 Sprint では文字列保存（Phase 5 で staff_id FK 化）
--   - supplier_name は本 Sprint では文字列保存（仕入元マスタ連携は次 Sprint）
--
-- 冪等性:
--   - CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS で再実行 no-op
--
-- 変更履歴:
--   2026-05-11: 初版（ADR-021 Phase 4 / Sprint 4）
-- ============================================================================

CREATE TABLE IF NOT EXISTS {schema}.order_purchase_details (
    id SERIAL PRIMARY KEY,
    order_id INTEGER NOT NULL UNIQUE
        REFERENCES {schema}.orders(id) ON DELETE CASCADE,
    tenant_id INTEGER NOT NULL DEFAULT {tenant_id},

    -- 仕入担当・取引情報
    purchase_staff   TEXT,           -- 仕入担当（後続 Phase 5 で staff_id FK 化）
    purchase_date    DATE,           -- 注文日
    transaction_no   TEXT,           -- 取引番号

    -- 仕入元
    supplier_name    TEXT,           -- 仕入元名（既存 suppliers テーブル参照は次 Sprint）
    supplier_url     TEXT,           -- 仕入元 URL

    -- 金額・数量
    purchase_amount   NUMERIC(14, 2) DEFAULT 0,  -- 単価
    purchase_quantity INTEGER        DEFAULT 0,  -- 数量
    purchase_total    NUMERIC(14, 2) DEFAULT 0,  -- 総額
    purchase_shipping NUMERIC(14, 2) DEFAULT 0,  -- 送料/代行費

    -- 配送
    carrier_name     TEXT,           -- 運送会社
    waybill_no       TEXT,           -- 送り状番号

    -- メモ
    purchase_note    TEXT,           -- 仕入備考

    -- ステータス（"" = 確認中 / "confirmed" = 確定済み）
    purchase_status  TEXT NOT NULL DEFAULT ''
        CHECK (purchase_status IN ('', 'confirmed')),

    -- 標準
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 索引
-- order_id は UNIQUE 制約で自動 index されるが、tenant_id との複合 UNIQUE で
-- マルチテナント防御を二重化する（migration 047/048 と同じパターン）。
CREATE UNIQUE INDEX IF NOT EXISTS uq_order_purchase_details_tenant_order
    ON {schema}.order_purchase_details (tenant_id, order_id);
CREATE INDEX IF NOT EXISTS idx_order_purchase_details_tenant
    ON {schema}.order_purchase_details (tenant_id);
CREATE INDEX IF NOT EXISTS idx_order_purchase_details_order
    ON {schema}.order_purchase_details (order_id);
CREATE INDEX IF NOT EXISTS idx_order_purchase_details_status
    ON {schema}.order_purchase_details (purchase_status);
-- supplier 検索（テナント単位 partial match）の想定で複合 index を貼る
CREATE INDEX IF NOT EXISTS idx_order_purchase_details_tenant_supplier
    ON {schema}.order_purchase_details (tenant_id, supplier_name);

-- updated_at 自動更新トリガー（既存パターンに倣う）
CREATE OR REPLACE FUNCTION {schema}.set_updated_at_order_purchase_details()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_set_updated_at_order_purchase_details
    ON {schema}.order_purchase_details;

CREATE TRIGGER trigger_set_updated_at_order_purchase_details
    BEFORE UPDATE ON {schema}.order_purchase_details
    FOR EACH ROW
    EXECUTE FUNCTION {schema}.set_updated_at_order_purchase_details();

-- RLS 有効化（既存テナントテーブル群と同じ tenant_id ベース ポリシー）
ALTER TABLE {schema}.order_purchase_details ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = '{schema}'
          AND tablename = 'order_purchase_details'
          AND policyname = 'tenant_isolation_order_purchase_details'
    ) THEN
        EXECUTE format(
            'CREATE POLICY tenant_isolation_order_purchase_details ON %I.order_purchase_details '
            'USING (tenant_id = public.current_tenant_id())',
            '{schema}'
        );
    END IF;
END
$$;
