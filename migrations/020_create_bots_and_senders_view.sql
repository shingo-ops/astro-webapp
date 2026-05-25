-- ============================================================================
-- !! 警告 !! 警告 !! 警告 !!
--
-- このSQLファイルは **テンプレート** です。`{schema}`, `{schema_raw}`,
-- `{tenant_id}` のプレースホルダを含むため、そのまま psql 等で実行すると
-- シンタックスエラーになります。
--
-- 必ず scripts/migrate_phase1_redesign.py 経由で実行してください。
--
-- ============================================================================
--
-- Phase 1 再設計 / Migration 020: bots テーブル + v_senders ビュー
--
-- 内容:
--   [1] bots テーブル（請求書送付bot・発送通知bot 等の自動化システム）
--   [2] v_senders ビュー（staff と bots を UNION した送信元統一ビュー）
--
-- 前提:
--   - 019 で {schema}.staff 作成済
--
-- 設計書参照:
--   - salesanchor_staff_roles_bots_design.docx §3-5, §4-3
--   - migrate_staff_roles_bots_PATCH.md §5
--
-- 変更履歴:
--   2026-04-23: 初版作成（Phase 1 再設計）

-- === [1] bots テーブル ===

CREATE TABLE {schema}.bots (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL DEFAULT {tenant_id},
    bot_code VARCHAR(20) NOT NULL,                      -- BOT-00001 形式
    display_name VARCHAR(100) NOT NULL,
    purpose VARCHAR(50) NOT NULL
        CHECK (purpose IN ('invoice','shipment','notification','custom')),
    status VARCHAR(20) NOT NULL DEFAULT 'active'
        CHECK (status IN ('active','inactive','maintenance')),
    api_key_hash VARCHAR(128) NOT NULL,                 -- bcryptハッシュ。平文APIキーはDB保存禁止
    discord_user_id VARCHAR(50),
    sender_email VARCHAR(255),
    owner_staff_id INTEGER NOT NULL REFERENCES {schema}.staff(id),
    last_executed_at TIMESTAMPTZ,
    execution_count BIGINT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, bot_code),
    UNIQUE (tenant_id, discord_user_id)
);

CREATE INDEX idx_bots_tenant_id ON {schema}.bots (tenant_id);
CREATE INDEX idx_bots_owner_staff_id ON {schema}.bots (owner_staff_id);
CREATE INDEX idx_bots_purpose ON {schema}.bots (purpose);
CREATE INDEX idx_bots_status ON {schema}.bots (status);

COMMENT ON TABLE {schema}.bots IS
  '自動化botの管理テーブル。人間スタッフ（staff）と別管理';
COMMENT ON COLUMN {schema}.bots.api_key_hash IS
  'bcryptハッシュ。平文APIキーは保存禁止';
COMMENT ON COLUMN {schema}.bots.owner_staff_id IS
  'このbotの管理責任者。監視・更新の一次担当';

-- updated_at トリガ
CREATE TRIGGER trg_bots_updated_at
    BEFORE UPDATE ON {schema}.bots
    FOR EACH ROW EXECUTE FUNCTION {schema}.trg_set_updated_at();

-- === [2] v_senders ビュー（staff と bots の UNION） ===

CREATE OR REPLACE VIEW {schema}.v_senders AS
SELECT
    id,
    tenant_id,
    'staff'::VARCHAR(10) AS sender_type,
    CONCAT(surname_jp, ' ', given_name_jp) AS display_name,
    primary_email AS contact_email
FROM {schema}.staff
UNION ALL
SELECT
    id,
    tenant_id,
    'bot'::VARCHAR(10) AS sender_type,
    display_name,
    sender_email AS contact_email
FROM {schema}.bots;

COMMENT ON VIEW {schema}.v_senders IS
  '送信元統一ビュー。conversations / invoice_logs / shipment_logs 等で sender_type + id を記録する際に参照';
