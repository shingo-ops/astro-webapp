-- ============================================================================
-- Migration 078: calendar_events テーブル（テナント別スキーマ）
--
-- 概要:
--   アプリ内カレンダー機能のイベントストレージ。
--   Google Calendar は SSOT を脱し、アプリ DB にもイベントを保持する。
--   Google Calendar との双方向同期に使用する。
--
-- 設計:
--   - {tenant_NNN} スキーマ配置（テナント別）
--   - calendar_type: 'shared' = テナント共有 / 'personal' = 個人（Phase 2 対応）
--   - source: 'app' = アプリで作成 / 'google' = Google Calendar から同期
--   - sync_origin_id: 無限ループ防止用。アプリ起源イベントの識別子を保持。
--     形式: "app:<tenant_id>:<calendar_event_id>"
--     Webhook受信時にこの値が存在すれば自分起源として無視する。
--   - google_event_id: Google Calendar 側のイベント ID（同期済みの場合）
--
-- 権限: 既存の channels.manage 権限を流用（新規権限定義なし）
-- 冪等性: CREATE TABLE IF NOT EXISTS で安全に再実行可能
-- 作成日: 2026-05-25
-- ============================================================================

DO $calendar_events_create$
DECLARE
  schema_rec    RECORD;
  created_count INTEGER := 0;
BEGIN
  FOR schema_rec IN
    SELECT nspname
    FROM pg_namespace
    WHERE nspname ~ '^tenant_\d+$'
    ORDER BY nspname
  LOOP
    -- role_permissions が存在するテナントのみ対象
    IF NOT EXISTS (
      SELECT 1 FROM pg_tables
      WHERE schemaname = schema_rec.nspname AND tablename = 'role_permissions'
    ) THEN
      CONTINUE;
    END IF;

    -- テーブル作成
    EXECUTE format($create$
      CREATE TABLE IF NOT EXISTS %I.calendar_events (
        id                  SERIAL PRIMARY KEY,
        user_id             INTEGER REFERENCES public.users(id) ON DELETE SET NULL,
        calendar_type       VARCHAR(10)   NOT NULL DEFAULT 'shared'
                              CHECK (calendar_type IN ('shared', 'personal')),
        title               VARCHAR(500)  NOT NULL,
        description         TEXT,
        location            TEXT,
        start_datetime      TIMESTAMPTZ   NOT NULL,
        end_datetime        TIMESTAMPTZ   NOT NULL,
        is_all_day          BOOLEAN       NOT NULL DEFAULT FALSE,
        google_event_id     VARCHAR(255),
        google_calendar_id  VARCHAR(255),
        source              VARCHAR(10)   NOT NULL DEFAULT 'app'
                              CHECK (source IN ('app', 'google')),
        sync_status         VARCHAR(10)   DEFAULT 'synced'
                              CHECK (sync_status IN ('synced', 'pending', 'failed')),
        sync_origin_id      VARCHAR(500),
        last_synced_at      TIMESTAMPTZ,
        created_by_user_id  INTEGER REFERENCES public.users(id) ON DELETE SET NULL,
        created_at          TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
        updated_at          TIMESTAMPTZ   NOT NULL DEFAULT NOW()
      )
    $create$, schema_rec.nspname);

    -- インデックス: 期間検索（カレンダー表示用）
    EXECUTE format(
      'CREATE INDEX IF NOT EXISTS idx_calendar_events_range '
      'ON %I.calendar_events (start_datetime, end_datetime)',
      schema_rec.nspname
    );

    -- インデックス: Google Event ID による同期（Webhook受信・重複チェック用）
    EXECUTE format(
      'CREATE INDEX IF NOT EXISTS idx_calendar_events_google_id '
      'ON %I.calendar_events (google_event_id) WHERE google_event_id IS NOT NULL',
      schema_rec.nspname
    );

    -- インデックス: 無限ループ防止チェック
    EXECUTE format(
      'CREATE INDEX IF NOT EXISTS idx_calendar_events_sync_origin '
      'ON %I.calendar_events (sync_origin_id) WHERE sync_origin_id IS NOT NULL',
      schema_rec.nspname
    );

    -- インデックス: ユーザー別 + 個人カレンダー取得
    EXECUTE format(
      'CREATE INDEX IF NOT EXISTS idx_calendar_events_user_type '
      'ON %I.calendar_events (user_id, calendar_type)',
      schema_rec.nspname
    );

    -- updated_at 自動更新トリガー
    EXECUTE format($fn$
      CREATE OR REPLACE FUNCTION %I.set_updated_at_calendar_events()
      RETURNS TRIGGER AS $upd$
      BEGIN
        NEW.updated_at = NOW();
        RETURN NEW;
      END;
      $upd$ LANGUAGE plpgsql
    $fn$, schema_rec.nspname);

    EXECUTE format(
      'DROP TRIGGER IF EXISTS trg_calendar_events_updated_at ON %I.calendar_events',
      schema_rec.nspname
    );
    EXECUTE format(
      'CREATE TRIGGER trg_calendar_events_updated_at '
      'BEFORE UPDATE ON %I.calendar_events '
      'FOR EACH ROW EXECUTE FUNCTION %I.set_updated_at_calendar_events()',
      schema_rec.nspname, schema_rec.nspname
    );

    created_count := created_count + 1;
    RAISE NOTICE 'migration 078: %: calendar_events テーブル作成OK', schema_rec.nspname;
  END LOOP;

  RAISE NOTICE 'migration 078: 全 % テナントに calendar_events を導入', created_count;
END $calendar_events_create$;

-- ============================================================================
-- Rollback (緊急時のみ手動実行):
-- DO $rb$
-- DECLARE r RECORD;
-- BEGIN
--   FOR r IN SELECT nspname FROM pg_namespace WHERE nspname ~ '^tenant_\d+$' LOOP
--     EXECUTE format('DROP TABLE IF EXISTS %I.calendar_events CASCADE', r.nspname);
--     EXECUTE format('DROP FUNCTION IF EXISTS %I.set_updated_at_calendar_events() CASCADE', r.nspname);
--   END LOOP;
-- END $rb$;
-- ============================================================================
