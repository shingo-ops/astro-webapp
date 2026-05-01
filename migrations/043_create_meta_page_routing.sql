-- ============================================================================
-- Phase 1-E Follow-up F16-S6 / Migration 043: meta_page_routing 公開ルーティング表
--
-- 目的:
--   Webhook 受信時に page_id / instagram_business_account_id から tenant_id を
--   1 クエリで逆引きするための public schema テーブル。Phase 1-D Sprint 6 までは
--   active 全テナントの schema を順次切替して検索していた（N+1）が、テナント数が
--   増えると線形に遅くなる + PostgreSQL 例外発生時の aborted state リスクが残る。
--
-- 設計:
--   - 各 tenant_NNN.tenant_meta_config への INSERT/UPDATE/DELETE トリガで
--     public.meta_page_routing を同期する（migration 044 で per-tenant 適用）
--   - public schema にあるため search_path 切替不要、RLS なし（routing 情報のみ）
--   - 主キーは (tenant_id, config_id) で tenant_meta_config.id を保持し冪等同期
--
-- 関連:
--   docs/PHASE_1E_FOLLOW_UP_BACKLOG.md F16-S6
--   migrations/040_create_tenant_meta_config.sql
--   backend/app/routers/webhook.py:_search_tenant_meta_config
--
-- 冪等性:
--   CREATE TABLE / CREATE INDEX いずれも IF NOT EXISTS。再実行可能。
--
-- 変更履歴:
--   2026-05-01: 初版（Phase 1-E Follow-up F16-S6）
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.meta_page_routing (
    tenant_id                       INTEGER     NOT NULL,
    config_id                       INTEGER     NOT NULL,
    schema_name                     TEXT        NOT NULL,
    page_id                         VARCHAR(50),
    instagram_business_account_id   VARCHAR(50),
    is_active                       BOOLEAN     NOT NULL DEFAULT TRUE,
    updated_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (tenant_id, config_id)
);

-- page_id 逆引き用（Messenger）
CREATE INDEX IF NOT EXISTS idx_meta_page_routing_page_id
    ON public.meta_page_routing (page_id)
    WHERE is_active = TRUE AND page_id IS NOT NULL;

-- instagram_business_account_id 逆引き用（Instagram）
CREATE INDEX IF NOT EXISTS idx_meta_page_routing_ig_id
    ON public.meta_page_routing (instagram_business_account_id)
    WHERE is_active = TRUE AND instagram_business_account_id IS NOT NULL;

COMMENT ON TABLE public.meta_page_routing IS
    'Webhook 受信時の page_id / IG account → tenant_id 1-shot 逆引き表 (F16-S6, 2026-05-01)';
