-- ============================================================================
-- !! テンプレート。scripts/migrate_adr015_lead_foundation.py 経由で全テナントに展開。
-- ============================================================================
-- ADR-015 / Migration 046: リード管理モジュール DB 基盤（段階分割 Phase 1）
--
-- 目的:
--   ADR-015 §1〜§7 の DB 基盤のみを先行整備する。AI 連携・ダッシュボード UI・
--   ステータス移行スクリプトは続く ADR / PR で扱う（questions/Q01 §A の
--   Option A: 段階分割方針）。
--
-- 対応する ADR セクション:
--   §1/§2 AI 自動収集（Q1=国 / Q2=タイトル）   → leads.country / target_titles / ai_collection_state
--   §3   返信速度トラッキング                 → leads.first_inquiry_at / first_response_at / first_response_seconds
--   §4   カルテ AI 補助設計                  → leads.{sales_form, competitor_check, cs_memo,
--                                              per_order_amount, monthly_frequency, monthly_forecast_source,
--                                              challenge, english_name, meeting_impression, meeting_memo}
--   §5   ダッシュボード「次回アクション」      → leads.next_action / next_action_date + index
--   §6   ステータス拡張                       → 既存 LeadStatus enum を拡張（コード側で対応、DB は VARCHAR(50) のまま）
--   §7   テナントプレイブック                  → lead_playbook テーブル新設
--   §3   既存顧客 dedup（SNS ID 検索）         → customer_contact_channels.external_id 追加
--
-- 設計判断（パートナー Claude Code が ADR-012 §How 委任に基づき判断したもの）:
--   - questions/Q01 で Shingo は「customer_channels テーブル新規作成」と回答したが、
--     既存 customer_contact_channels (migration 026) が既に全チャンネル対応の
--     スキーマであり、機能重複を避けるため external_id 列を追加する形で実装する。
--     ADR-012「How はパートナー判断」に基づく決定で、機能的には Shingo の意図
--     （SNS 全チャンネルでの dedup 可能化）を満たす。
--   - lead_playbook はテナントあたり複数設定持てる構造（name で識別）。Foundation
--     段階では UI/API は未実装。続く PR で is_active=TRUE の 1 レコードを取得する
--     運用想定。
--   - ステータスは VARCHAR(50) のまま enum 化しない（既存実装踏襲、Q01-B「既存
--     LeadStatus は置き換えではなく拡張」「移行スクリプト不要」と整合）。
--
-- 関連:
--   docs/adr/ADR-015.md
--   questions/Q01-adr-015-scope-and-status-collision.md
--   migrations/003_add_phase1_tenant_tables.sql（leads 本体）
--   migrations/026_create_customer_contact_channels.sql（customer_contact_channels 本体）
--
-- 冪等性:
--   - ADD COLUMN IF NOT EXISTS / CREATE INDEX IF NOT EXISTS / CREATE TABLE IF NOT EXISTS
--   - DO ブロックでポリシー / トリガ存在確認
--   - 何度実行しても副作用なし
--
-- 変更履歴:
--   2026-05-07: 初版（ADR-015 段階分割 Phase 1 / Foundation）
-- ============================================================================

-- === §1/§2/§3/§4/§5: leads テーブルにカルテ・AI 収集・返信速度・次回アクション列を追加 ===

-- §1/§2 AI 収集データ（Qwen3 8B が会話から抽出して保存）
ALTER TABLE {schema}.leads ADD COLUMN IF NOT EXISTS country VARCHAR(100);
ALTER TABLE {schema}.leads ADD COLUMN IF NOT EXISTS target_titles VARCHAR(500);

-- §3 返信速度トラッキング（システム計算、AI 不要）
ALTER TABLE {schema}.leads ADD COLUMN IF NOT EXISTS first_inquiry_at TIMESTAMPTZ;
ALTER TABLE {schema}.leads ADD COLUMN IF NOT EXISTS first_response_at TIMESTAMPTZ;
ALTER TABLE {schema}.leads ADD COLUMN IF NOT EXISTS first_response_seconds INTEGER;

-- §4 カルテ AI 補助対象列
ALTER TABLE {schema}.leads ADD COLUMN IF NOT EXISTS sales_form VARCHAR(50);
ALTER TABLE {schema}.leads ADD COLUMN IF NOT EXISTS competitor_check BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE {schema}.leads ADD COLUMN IF NOT EXISTS cs_memo TEXT;
ALTER TABLE {schema}.leads ADD COLUMN IF NOT EXISTS per_order_amount NUMERIC(15, 2);
ALTER TABLE {schema}.leads ADD COLUMN IF NOT EXISTS monthly_frequency NUMERIC(10, 2);
-- monthly_forecast は migration 003 で既に存在。算出ソース（'estimate'/'sales_db'/'manual'）を追加
ALTER TABLE {schema}.leads ADD COLUMN IF NOT EXISTS monthly_forecast_source VARCHAR(50);

-- §4 営業担当が記入する列（AI は介在しない、単に格納先のみ用意）
ALTER TABLE {schema}.leads ADD COLUMN IF NOT EXISTS challenge TEXT;
ALTER TABLE {schema}.leads ADD COLUMN IF NOT EXISTS english_name VARCHAR(255);
ALTER TABLE {schema}.leads ADD COLUMN IF NOT EXISTS meeting_impression VARCHAR(50);
ALTER TABLE {schema}.leads ADD COLUMN IF NOT EXISTS meeting_memo TEXT;

-- §5 次回アクション（Q1-C で leads テーブルへの追加が承認）
ALTER TABLE {schema}.leads ADD COLUMN IF NOT EXISTS next_action VARCHAR(500);
ALTER TABLE {schema}.leads ADD COLUMN IF NOT EXISTS next_action_date DATE;

-- §1/§2/§3 AI 収集ステート
--   waiting_q1     : Q1（国）の回答待ち
--   waiting_q2     : Q2（タイトル）の回答待ち
--   completed      : 収集完了 → アサイン済み
--   escalated      : 要人間確認（理解不能・スパム判定）
--   not_applicable : 既存顧客等で AI 介入なし
ALTER TABLE {schema}.leads ADD COLUMN IF NOT EXISTS ai_collection_state VARCHAR(20);
ALTER TABLE {schema}.leads ADD COLUMN IF NOT EXISTS escalation_flag BOOLEAN NOT NULL DEFAULT FALSE;

-- §5 ダッシュボードの OVERDUE / TODAY / TOMORROW / UPCOMING フィルタ用
CREATE INDEX IF NOT EXISTS idx_leads_next_action_date
    ON {schema}.leads (next_action_date)
    WHERE next_action_date IS NOT NULL;

-- §1/§2 AI 対応中リードの抽出用（バッチ処理 / 監視）
CREATE INDEX IF NOT EXISTS idx_leads_ai_collection_state
    ON {schema}.leads (ai_collection_state)
    WHERE ai_collection_state IS NOT NULL;

-- §3 要人間確認フラグの抽出用（Discord 通知バッチ）
CREATE INDEX IF NOT EXISTS idx_leads_escalation_flag
    ON {schema}.leads (escalation_flag)
    WHERE escalation_flag = TRUE;

COMMENT ON COLUMN {schema}.leads.country IS 'ADR-015 §2 Q1: 配送先の国（AI が会話から抽出）';
COMMENT ON COLUMN {schema}.leads.target_titles IS 'ADR-015 §2 Q2: 興味のあるタイトル（AI が会話から抽出）';
COMMENT ON COLUMN {schema}.leads.first_inquiry_at IS 'ADR-015 §3 初回問い合わせ受信時刻（返信速度算出のベース）';
COMMENT ON COLUMN {schema}.leads.first_response_at IS 'ADR-015 §3 初回返信時刻（システム自動記録）';
COMMENT ON COLUMN {schema}.leads.first_response_seconds IS 'ADR-015 §3 返信速度（秒）= first_response_at - first_inquiry_at';
COMMENT ON COLUMN {schema}.leads.ai_collection_state IS 'ADR-015 §1/§2 AI 収集ステート: waiting_q1 / waiting_q2 / completed / escalated / not_applicable';
COMMENT ON COLUMN {schema}.leads.escalation_flag IS 'ADR-015 §3 AI が理解不能・要人間確認フラグ';
COMMENT ON COLUMN {schema}.leads.next_action_date IS 'ADR-015 §5 ダッシュボードのリマインド日（OVERDUE/TODAY/TOMORROW/UPCOMING 分類のキー）';
COMMENT ON COLUMN {schema}.leads.monthly_forecast_source IS 'ADR-015 §4 月間見込みの算出ソース: estimate / sales_db / manual';

-- === §7: lead_playbook テーブル新設 ===

CREATE TABLE IF NOT EXISTS {schema}.lead_playbook (
    id                          SERIAL PRIMARY KEY,
    tenant_id                   INTEGER NOT NULL DEFAULT {tenant_id},
    name                        VARCHAR(100) NOT NULL DEFAULT 'default',
    greeting_message            TEXT,
    -- 質問定義: [{"key":"country","prompt":"Which country are you shipping to?","required":true,"order":1}, ...]
    questions                   JSONB NOT NULL DEFAULT '[]'::jsonb,
    -- アサイン条件: 'all_required' / 'first_reply' / 'after_n_turns'
    assignment_condition        VARCHAR(50) NOT NULL DEFAULT 'all_required',
    -- assignment_condition='after_n_turns' のときの N
    assignment_after_n_turns    INTEGER,
    assignment_message          TEXT,
    -- 担当者割り当て方法: 'manual' / 'round_robin' / 'country'
    assignment_method           VARCHAR(50) NOT NULL DEFAULT 'manual',
    -- 'country' の場合のマッピング: {"JP": 12, "US": 7, "default": 1}
    country_assignment_map      JSONB,
    is_active                   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, name)
);

CREATE INDEX IF NOT EXISTS idx_lead_playbook_active
    ON {schema}.lead_playbook (tenant_id)
    WHERE is_active = TRUE;

ALTER TABLE {schema}.lead_playbook ENABLE ROW LEVEL SECURITY;

DO $playbook_rls$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE policyname = 'tenant_isolation_lead_playbook'
          AND schemaname = '{schema_raw}'
    ) THEN
        CREATE POLICY tenant_isolation_lead_playbook ON {schema}.lead_playbook
            USING (tenant_id = current_setting('app.tenant_id', true)::INTEGER);
    END IF;
END $playbook_rls$;

CREATE OR REPLACE FUNCTION {schema}.set_updated_at_lead_playbook()
RETURNS TRIGGER AS $playbook_upd$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$playbook_upd$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_set_updated_at_lead_playbook ON {schema}.lead_playbook;
CREATE TRIGGER trigger_set_updated_at_lead_playbook
    BEFORE UPDATE ON {schema}.lead_playbook
    FOR EACH ROW EXECUTE FUNCTION {schema}.set_updated_at_lead_playbook();

COMMENT ON TABLE {schema}.lead_playbook IS 'ADR-015 §7 テナント別 AI 対応プレイブック（挨拶・質問・アサイン条件のカスタマイズ）';

-- === §3: customer_contact_channels に SNS dedup 用 external_id を追加 ===

ALTER TABLE {schema}.customer_contact_channels
    ADD COLUMN IF NOT EXISTS external_id VARCHAR(100);

-- (channel, external_id) で既存顧客検索（同一 SNS ユーザーからの再問い合わせ判定）
CREATE INDEX IF NOT EXISTS idx_ccc_channel_external_id
    ON {schema}.customer_contact_channels (channel, external_id)
    WHERE external_id IS NOT NULL;

COMMENT ON COLUMN {schema}.customer_contact_channels.external_id IS
    'ADR-015 §3 SNS プラットフォーム上のユーザー ID（Discord user_id / Messenger PSID / Instagram IGSID 等）。新規問い合わせ時の既存顧客 dedup に使用';
