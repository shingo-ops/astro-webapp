-- ============================================================================
-- Migration 059: public.discord_inbound_messages (Discord 受信メッセージ保存)
--                + public.discord_webhook_idempotency (冪等性 / AC1.6 連携)
--
-- 経緯:
--   spec.md v1.1 F1 / F5: Discord Bot で受信したメッセージを 1 メッセージ＝1 行で
--   保存。F3 (ルール解析) → F4 (LLM フォールバック) → F6 (admin レビュー) の
--   一次データソース。
--
-- 設計:
--   - public schema 中央共有（A6、tenant_id 列なし。受信は中央経由）
--   - parse_status:
--       pending             受信直後（F3 未走査）
--       parsing             F3 走査中
--       parsed              F3 で完全に解決
--       parsed_rule_only    F3 のみで完了（F4 LLM 使用なし）
--       parsed_llm          F3+F4 LLM フォールバックで完了
--       unparsed            F3 で残り＋ F4 不可（API key 欠落等）
--       budget_exhausted    F4 LLM 月次予算超過で skip
--       ignored_routing     supplier_discord_routing 未登録 guild からのメッセージ
--       approved            F6 admin 承認済（inventory_movements 反映）
--       rejected            F6 admin 差戻し
--   - parse_engine: 'rule_v1' / 'rule_v1_llm_v1' / 'rule_v1_fallback_blocked' 等
--   - parse_result_json JSONB: F3/F4 の解析結果（items[], excludes[], unparsed[]）
--   - discord_message_id UNIQUE (AC5.2 idempotency)
--   - llm_cost_usd NUMERIC(8,4): F4 で記録（AC4.2）
--
-- ADR-034 観点: public schema のため 1 回のみ実行。
--
-- 関連:
--   .claude-pipeline/spec.md F1 / F5 / F6
--   migrations/013_add_meta_webhook_idempotency.sql (idempotency パターン、AC1.6 参照)
--   migrations/056 (suppliers FK 先)
--
-- 作成日: 2026-05-21
-- ============================================================================

-- === 1. public.discord_inbound_messages ===
CREATE TABLE IF NOT EXISTS public.discord_inbound_messages (
    id                    SERIAL PRIMARY KEY,
    supplier_id           INTEGER REFERENCES public.suppliers(id) ON DELETE SET NULL,
    discord_channel_id    VARCHAR(50) NOT NULL,
    discord_message_id    VARCHAR(50) NOT NULL,
    raw_content           TEXT NOT NULL,
    received_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    parse_status          VARCHAR(30) NOT NULL DEFAULT 'pending',
    parse_engine          VARCHAR(50),
    parse_result_json     JSONB,
    exclude_reason        TEXT,
    operator_comment      TEXT,
    operator_id           INTEGER,
    approved_at           TIMESTAMPTZ,
    llm_cost_usd          NUMERIC(8, 4),
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (discord_message_id)
);

-- parse_status CHECK 制約
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'discord_inbound_messages_parse_status_check'
          AND conrelid = 'public.discord_inbound_messages'::regclass
    ) THEN
        ALTER TABLE public.discord_inbound_messages
            ADD CONSTRAINT discord_inbound_messages_parse_status_check
            CHECK (parse_status IN (
                'pending', 'parsing', 'parsed',
                'parsed_rule_only', 'parsed_llm',
                'unparsed', 'budget_exhausted', 'ignored_routing',
                'approved', 'rejected'
            ));
    END IF;
END $$;

-- 索引
CREATE INDEX IF NOT EXISTS idx_dim_supplier         ON public.discord_inbound_messages (supplier_id);
CREATE INDEX IF NOT EXISTS idx_dim_parse_status     ON public.discord_inbound_messages (parse_status);
CREATE INDEX IF NOT EXISTS idx_dim_received_at      ON public.discord_inbound_messages (received_at DESC);
CREATE INDEX IF NOT EXISTS idx_dim_channel          ON public.discord_inbound_messages (discord_channel_id);
-- JSONB GIN 索引（F6 レビュー UI が parse_result_json 内検索する場合）
CREATE INDEX IF NOT EXISTS idx_dim_parse_result_gin ON public.discord_inbound_messages
    USING GIN (parse_result_json);

-- updated_at トリガ
CREATE OR REPLACE FUNCTION public.set_updated_at_dim()
RETURNS TRIGGER AS $upd$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$upd$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_set_updated_at_dim ON public.discord_inbound_messages;
CREATE TRIGGER trigger_set_updated_at_dim
    BEFORE UPDATE ON public.discord_inbound_messages
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at_dim();

COMMENT ON TABLE public.discord_inbound_messages IS 'spec F1/F5: Discord 仕入元メッセージ受信ログ（全テナント共有）';

-- === 2. public.discord_webhook_idempotency ===
-- AC1.6: meta_webhook_idempotency (migrations/013) と同型構造で Reviewer が
--        diff 確認できるよう、列構成を意図的に一致させる。
-- Meta は {tenant_xxx} schema 配置、Discord は public schema 配置という違いはあるが、
-- (id, message_id, received_at) の主要列は同型。
CREATE TABLE IF NOT EXISTS public.discord_webhook_idempotency (
    id              SERIAL PRIMARY KEY,
    message_id      VARCHAR(100) NOT NULL UNIQUE,
    payload_hash    VARCHAR(64),                       -- SHA256(payload) 任意記録
    received_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_at    TIMESTAMPTZ,
    result_status   VARCHAR(20)
);

CREATE INDEX IF NOT EXISTS idx_discord_idemp_received
    ON public.discord_webhook_idempotency (received_at DESC);

COMMENT ON TABLE public.discord_webhook_idempotency IS
    'spec F5 AC5.2: Discord webhook 重複配信防止。{tenant_xxx}.meta_webhook_idempotency と同型構造（AC1.6）';

-- ============================================================================
-- Rollback:
--   DROP TRIGGER IF EXISTS trigger_set_updated_at_dim ON public.discord_inbound_messages;
--   DROP FUNCTION IF EXISTS public.set_updated_at_dim();
--   DROP TABLE IF EXISTS public.discord_webhook_idempotency;
--   DROP TABLE IF EXISTS public.discord_inbound_messages;
-- ============================================================================
