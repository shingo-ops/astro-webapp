-- Migration 075: テナント Google Calendar 連携設定テーブルを作成
--
-- 変更内容:
--   管理者が Google OAuth で接続した際の認証情報をテナント単位で保持するテーブルを追加。
--   アクセストークン・リフレッシュトークンは Fernet で暗号化して保存する。
--   テナント共通の接続（管理者が1回接続 → 全スタッフが参照可能）を実現する。
--
-- 影響テーブル: public.tenant_google_calendar_config（新規作成）
-- 適用対象: public スキーマ（テナント横断）
-- 不可逆: テーブル削除は DROP TABLE で可
--
-- 冪等チェック: IF NOT EXISTS で安全に再実行可能

CREATE TABLE IF NOT EXISTS tenant_google_calendar_config (
  id                       SERIAL PRIMARY KEY,
  tenant_id                INTEGER NOT NULL UNIQUE REFERENCES tenants(id) ON DELETE CASCADE,
  access_token_encrypted   TEXT    NOT NULL,
  refresh_token_encrypted  TEXT    NOT NULL,
  token_expiry             TIMESTAMP WITH TIME ZONE,
  calendar_id              TEXT    NOT NULL DEFAULT 'primary',
  connected_by_user_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
  connected_at             TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  updated_at               TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
