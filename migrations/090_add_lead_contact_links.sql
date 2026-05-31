-- ============================================================================
-- !! テンプレート。scripts/migrate_090_lead_contact_links.py 経由で全テナントに展開。
-- ============================================================================
-- Migration 090: leads テーブルに messenger_link / discord_id を追加
--
-- 目的:
--   受信箱の連絡先タブから Meta 系メッセージリンクおよび Discord ID を
--   顧客ごとに保存できるようにする。
--
-- 影響テーブル: {schema}.leads
-- 適用対象: 全テナント
-- 冪等: ADD COLUMN IF NOT EXISTS

ALTER TABLE {schema}.leads
    ADD COLUMN IF NOT EXISTS messenger_link VARCHAR(1000),
    ADD COLUMN IF NOT EXISTS discord_id     VARCHAR(255);
