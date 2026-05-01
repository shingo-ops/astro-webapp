-- ============================================================================
-- !! テンプレート。scripts/migrate_meta_messages_page_id.py 経由で全テナントに展開。
-- ============================================================================
-- Phase 1-E Follow-up F14-S5 / Migration 045: meta_messages.page_id 列追加
--
-- 目的:
--   1 テナントで複数 Page 接続済のとき、受信メッセージがどの Page 由来か
--   識別できるようにする（Inbox の Page フィルタの前提）。
--
-- 設計:
--   - Messenger: webhook の entry.id（= Facebook Page ID）を保存
--   - Instagram: 当面 NULL（entry.id は Instagram Business Account ID で
--     Page ID とは別物。tenant_meta_config 経由の逆引き対応は follow-up）
--   - 既存行は page_id = NULL（raw_payload に entry.id を記録していなかったため
--     遡及 backfill 不可。新規受信メッセージから順次埋まる）
--   - Index は (tenant_id, page_id) 複合（Inbox フィルタクエリの WHERE で使う）
--
-- 関連:
--   docs/PHASE_1E_FOLLOW_UP_BACKLOG.md F14-S5
--   migrations/012_add_meta_tenant_tables.sql（meta_messages 本体）
--   migrations/041_extend_meta_messages.sql（Sprint 4 で送信側カラム拡張）
--
-- 冪等性:
--   ADD COLUMN IF NOT EXISTS / CREATE INDEX IF NOT EXISTS で再実行可能。
--
-- 変更履歴:
--   2026-05-01: 初版（Phase 1-E Follow-up F14-S5）
-- ============================================================================

ALTER TABLE {schema}.meta_messages
    ADD COLUMN IF NOT EXISTS page_id VARCHAR(50);

CREATE INDEX IF NOT EXISTS idx_meta_messages_tenant_page
    ON {schema}.meta_messages (tenant_id, page_id)
    WHERE page_id IS NOT NULL;

COMMENT ON COLUMN {schema}.meta_messages.page_id IS
    'Facebook Page ID (Messenger 受信時のみ。IG 受信は当面 NULL、F14-S5)';
