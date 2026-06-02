-- ============================================================================
-- Migration 20260602_190000: ADR-093 Phase 4 — public.user_inventory_filters 作成
--
-- 在庫表(/inventory)のユーザー別フィルタ設定を永続化する（再ログイン後も保持）。
--   - enabled: フィルタ ON/OFF トグル
--   - filters JSONB: { "hidden_supplier_ids": [int...], "hidden_columns": ["unit"|"condition"|...] }
--     仕入元の表示/非表示（複数選択）と列の取捨をユーザーごとに保存。
--
-- 適用対象: public スキーマ (1 回のみ)。public.users は migration-test ベースラインにも
--           存在するため to_regclass ガード不要。
-- 冪等: CREATE TABLE IF NOT EXISTS。additive-only（新規テーブル）。
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.user_inventory_filters (
    user_id    INTEGER PRIMARY KEY REFERENCES public.users(id) ON DELETE CASCADE,
    enabled    BOOLEAN     NOT NULL DEFAULT FALSE,
    filters    JSONB       NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
