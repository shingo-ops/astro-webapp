-- 認証イベント記録テーブル（public スキーマ）
-- ミドルウェアが認証成功/失敗を自動記録する
--
-- 使い方: docker compose exec postgres psql -U myapp_user -d myapp_db -f /migrations/001_create_auth_events.sql

CREATE TABLE IF NOT EXISTS public.auth_events (
    id BIGSERIAL PRIMARY KEY,
    event_type VARCHAR(50) NOT NULL,       -- auth_success, auth_failure, auth_request
    path VARCHAR(500) NOT NULL,            -- リクエストパス
    method VARCHAR(10) NOT NULL,           -- HTTP メソッド
    status_code INTEGER NOT NULL,          -- レスポンスステータスコード
    client_ip VARCHAR(45),                 -- クライアントIP（IPv6対応）
    user_agent VARCHAR(500),               -- User-Agent（先頭500文字）
    duration_ms INTEGER,                   -- レスポンス時間（ミリ秒）
    created_at TIMESTAMPTZ DEFAULT NOW()   -- 記録日時
);

-- 検索用インデックス
CREATE INDEX IF NOT EXISTS idx_auth_events_type_created
    ON public.auth_events (event_type, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_auth_events_client_ip
    ON public.auth_events (client_ip, created_at DESC);

-- コメント
COMMENT ON TABLE public.auth_events IS '認証イベント自動記録（ミドルウェアが書き込み）';
