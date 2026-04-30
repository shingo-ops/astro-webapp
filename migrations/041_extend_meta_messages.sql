-- ============================================================================
-- !! テンプレート。scripts/migrate_meta_inbox_phase1d_sprint4.py 経由で
-- !! 全テナントスキーマに展開する（migration 040 と同じ運用）。
-- ============================================================================
-- Phase 1-D Sprint 4 / Migration 041: meta_messages 拡張
--
-- 目的:
--   既存 `meta_messages` テーブル（migration 012 で作成）に、Inbox 機能で
--   必要となる列を additive に追加する。
--
--   - 送信側 (Sprint 5 で利用): recipient_id / messaging_type / message_tag
--                                / sent_by_staff_id / error_code / error_message
--                                / message_id（Meta の mid）
--   - 既読管理 (Sprint 4 で利用): seen_at / seen_by_staff_id
--
-- 関連:
--   spec.md §4-2（データモデル）
--   spec.md §5-3, §5-4, §5-6（会話一覧 / メッセージ取得 / 既読マーク）
--   migrations/012_add_meta_tenant_tables.sql（既存スキーマ）
--
-- 設計判断:
--   - 全列とも NULLABLE。既存 inbound 行に backfill 不要。
--   - `direction='outbound'` 行で recipient_id / messaging_type / message_tag /
--     sent_by_staff_id が埋まる。`direction='inbound'` 行ではこれらは NULL。
--   - `seen_at` / `seen_by_staff_id` は `direction='inbound'` 行のみ使用。
--   - `message_id` は Meta から返る mid（idempotency / dedup 用）。受信時は
--     既存 webhook.py の payload から取り、送信時は Send API レスポンスから取る。
--   - `idx_meta_messages_lead_created` は会話メッセージ取得 (`WHERE lead_id=...
--     ORDER BY created_at`) のホットパス用。
--
-- 冪等性:
--   - ADD COLUMN IF NOT EXISTS / CREATE INDEX IF NOT EXISTS で再実行可能。
--
-- 変更履歴:
--   2026-04-30: 初版（しんごさん依頼、Phase 1-D Sprint 4）

-- === meta_messages に列追加 ===
ALTER TABLE {schema}.meta_messages
    ADD COLUMN IF NOT EXISTS recipient_id      VARCHAR(100),
    ADD COLUMN IF NOT EXISTS messaging_type    VARCHAR(20),
    ADD COLUMN IF NOT EXISTS message_tag       VARCHAR(50),
    ADD COLUMN IF NOT EXISTS sent_by_staff_id  INTEGER REFERENCES {schema}.staff(id),
    ADD COLUMN IF NOT EXISTS error_code        VARCHAR(50),
    ADD COLUMN IF NOT EXISTS error_message     TEXT,
    ADD COLUMN IF NOT EXISTS message_id        VARCHAR(100),
    ADD COLUMN IF NOT EXISTS seen_at           TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS seen_by_staff_id  INTEGER REFERENCES {schema}.staff(id);

-- === インデックス ===
-- 会話別メッセージ取得（GET /leads/<id>/messages）のホットパス
CREATE INDEX IF NOT EXISTS idx_meta_messages_lead_created
    ON {schema}.meta_messages (lead_id, created_at DESC);

-- 受信側未読集計（GET /conversations の unread_count）のホットパス
CREATE INDEX IF NOT EXISTS idx_meta_messages_lead_unread
    ON {schema}.meta_messages (lead_id)
    WHERE direction = 'inbound' AND seen_at IS NULL;
