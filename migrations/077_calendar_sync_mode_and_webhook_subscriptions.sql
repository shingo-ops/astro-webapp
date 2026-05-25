-- ============================================================================
-- Migration 077: Google Calendar 同期モード + Webhook サブスクリプション管理
--
-- 変更内容:
--   1. tenant_google_calendar_config に sync_mode カラムを追加
--      'bidirectional' | 'read_only' | 'write_only' | 'none' の4択
--      既存テナントはデフォルト 'bidirectional' として扱う
--
--   2. public.google_webhook_subscriptions テーブルを新設
--      テナントごとの Google Calendar Push Notification チャンネル情報を管理
--      有効期限（最大7日）の追跡と自動更新に使用
--
-- 適用対象: public スキーマ（テナント横断）
-- 冪等性: IF NOT EXISTS / ADD COLUMN IF NOT EXISTS で安全に再実行可能
-- 作成日: 2026-05-25
-- ============================================================================

-- 1. sync_mode カラムを追加
ALTER TABLE tenant_google_calendar_config
  ADD COLUMN IF NOT EXISTS sync_mode VARCHAR(20) NOT NULL DEFAULT 'bidirectional'
    CONSTRAINT tenant_google_calendar_config_sync_mode_check
      CHECK (sync_mode IN ('bidirectional', 'read_only', 'write_only', 'none'));

-- 2. google_webhook_subscriptions テーブルを作成
CREATE TABLE IF NOT EXISTS google_webhook_subscriptions (
  id            SERIAL PRIMARY KEY,
  tenant_id     INTEGER NOT NULL UNIQUE REFERENCES tenants(id) ON DELETE CASCADE,
  channel_id    VARCHAR(255) NOT NULL,
  resource_id   VARCHAR(255),
  calendar_id   VARCHAR(255) NOT NULL DEFAULT 'primary',
  expiration    TIMESTAMP WITH TIME ZONE NOT NULL,
  created_at    TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- インデックス（有効期限による定期チェック用）
CREATE INDEX IF NOT EXISTS idx_google_webhook_subscriptions_expiration
  ON google_webhook_subscriptions (expiration);

-- channel_id による高速検索（Webhook受信時のテナント特定用）
CREATE UNIQUE INDEX IF NOT EXISTS idx_google_webhook_subscriptions_channel_id
  ON google_webhook_subscriptions (channel_id);

-- ============================================================================
-- Rollback (緊急時のみ手動実行):
-- DROP TABLE IF EXISTS google_webhook_subscriptions;
-- ALTER TABLE tenant_google_calendar_config DROP COLUMN IF EXISTS sync_mode;
-- ============================================================================
