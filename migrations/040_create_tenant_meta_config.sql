-- ============================================================================
-- !! テンプレート。scripts/migrate_meta_inbox_phase1d.py 経由で全テナントに展開。
-- ============================================================================
-- Phase 1-D Sprint 1 / Migration 040: tenant_meta_config テーブル新設
--
-- 目的:
--   Meta（Facebook Page / Instagram Business Account）の OAuth 接続情報を
--   per-tenant スキーマに保存する。Page Access Token は Fernet で暗号化済みの
--   バイト列のみ保存し、生トークンは DB に置かない。
--
-- 関連:
--   spec.md §4-1（データモデル）
--   backend/app/services/encryption.py（Fernet 暗号化レイヤ）
--
-- 冪等性:
--   - CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS / DO ブロックで
--     ポリシー存在チェック → 重複エラーなし。再実行可能。
--
-- 変更履歴:
--   2026-04-30: 初版（しんごさん依頼、Phase 1-D Sprint 1）

-- === tenant_meta_config 本体 ===
CREATE TABLE IF NOT EXISTS {schema}.tenant_meta_config (
    id                              SERIAL PRIMARY KEY,
    tenant_id                       INTEGER NOT NULL DEFAULT {tenant_id},
    page_id                         VARCHAR(50) NOT NULL,
    page_name                       VARCHAR(200) NOT NULL,
    page_access_token_encrypted     BYTEA NOT NULL,           -- Fernet ciphertext (urlsafe base64 を BYTEA で保存)
    page_token_expires_at           TIMESTAMPTZ,              -- 長期 Page Access Token の有効期限（約 60 日）
    instagram_business_account_id   VARCHAR(50),
    instagram_username              VARCHAR(100),
    subscribed_fields               JSONB,                    -- subscribed_apps で渡した fields 配列
    connected_by_staff_id           INTEGER REFERENCES {schema}.staff(id),
    connected_at                    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_token_refreshed_at         TIMESTAMPTZ,
    is_active                       BOOLEAN NOT NULL DEFAULT TRUE,
    deactivated_at                  TIMESTAMPTZ,
    notes                           TEXT,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- === インデックス ===
-- アクティブな (tenant_id, page_id) ペアは 1 つだけ（再接続時は古い行を is_active=FALSE に倒す運用）
CREATE UNIQUE INDEX IF NOT EXISTS uq_tenant_meta_config_active_page
    ON {schema}.tenant_meta_config (tenant_id, page_id)
    WHERE is_active = TRUE;

-- Webhook で Instagram の entry[].id から逆引きする用
CREATE INDEX IF NOT EXISTS idx_tenant_meta_config_ig_id
    ON {schema}.tenant_meta_config (instagram_business_account_id)
    WHERE instagram_business_account_id IS NOT NULL;

-- === RLS（Row Level Security） ===
ALTER TABLE {schema}.tenant_meta_config ENABLE ROW LEVEL SECURITY;

DO $tmc_rls$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE policyname = 'tenant_isolation_tenant_meta_config'
          AND schemaname = '{schema_raw}'
    ) THEN
        CREATE POLICY tenant_isolation_tenant_meta_config ON {schema}.tenant_meta_config
            USING (tenant_id = current_setting('app.tenant_id', true)::INTEGER);
    END IF;
END $tmc_rls$;

-- === updated_at 自動更新トリガ ===
CREATE OR REPLACE FUNCTION {schema}.set_updated_at_tenant_meta_config()
RETURNS TRIGGER AS $tmc_upd$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$tmc_upd$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_set_updated_at_tenant_meta_config ON {schema}.tenant_meta_config;
CREATE TRIGGER trigger_set_updated_at_tenant_meta_config
    BEFORE UPDATE ON {schema}.tenant_meta_config
    FOR EACH ROW EXECUTE FUNCTION {schema}.set_updated_at_tenant_meta_config();
