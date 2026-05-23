-- データアクセス監査ログテーブル（public スキーマ）
-- P2-1: 全CRUD操作の記録（auth_events は認証専用のため分離）
-- P2-3: 大量エクスポート検知の基盤
--
-- 使い方: docker compose exec postgres psql -U myapp_user -d myapp_db -f /migrations/071_create_data_access_events.sql

CREATE TABLE IF NOT EXISTS public.data_access_events (
    id BIGSERIAL PRIMARY KEY,
    event_type VARCHAR(50) NOT NULL,        -- data_write, bulk_export_alert
    method VARCHAR(10) NOT NULL,            -- HTTP メソッド
    path VARCHAR(500) NOT NULL,             -- リクエストパス
    status_code INTEGER NOT NULL,           -- レスポンスステータスコード
    user_email VARCHAR(255),                -- JWT ペイロードから抽出（無検証、ログ用）
    client_ip VARCHAR(45),                  -- クライアントIP（IPv6対応）
    user_agent VARCHAR(500),                -- User-Agent
    duration_ms INTEGER,                    -- レスポンス時間（ミリ秒）
    created_at TIMESTAMPTZ DEFAULT NOW()    -- 記録日時
);

-- 検索用インデックス
CREATE INDEX IF NOT EXISTS idx_data_access_type_created
    ON public.data_access_events (event_type, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_data_access_user_email_created
    ON public.data_access_events (user_email, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_data_access_ip_created
    ON public.data_access_events (client_ip, created_at DESC);

COMMENT ON TABLE public.data_access_events IS 'CRUD操作・大量アクセス監査ログ（P2-1/P2-3）';

-- ロールバック用: DROP TABLE IF EXISTS public.data_access_events;
