-- Migration 100: meta_messages に画像添付カラムを追加
--
-- 目的:
--   受信箱からの画像送信機能（Sprint 2）に対応するため、
--   meta_messages テーブルに添付情報カラムを additive に追加する。
--
--   - attachment_url:  添付ファイルの URL（受信時は Meta CDN URL、送信時は NULL）
--   - attachment_type: 添付の種類（'image' | 'video' | 'audio' | 'file' 等）
--
-- 関連: ADR-089（画像送信 Sprint 2）
--
-- 冪等性: ADD COLUMN IF NOT EXISTS で再実行可能。
--
-- 変更履歴:
--   2026-06-01: 初版（しんごさん依頼、受信箱画像送信 Sprint 2）

ALTER TABLE {schema}.meta_messages
    ADD COLUMN IF NOT EXISTS attachment_url  TEXT,
    ADD COLUMN IF NOT EXISTS attachment_type VARCHAR(20);
