-- 保持ポリシー削除ジョブ用インデックス（P2-1保持ポリシー）
-- created_at 単独インデックスを追加。
-- 既存の複合インデックス (event_type, created_at DESC) は
-- WHERE created_at < ... の単独条件では使われない可能性があるため別途追加。
-- CONCURRENTLY で本番稼働中のロックを回避。

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_data_access_events_created_at
    ON public.data_access_events (created_at);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_auth_events_created_at
    ON public.auth_events (created_at);

-- ロールバック用:
-- DROP INDEX CONCURRENTLY IF EXISTS idx_data_access_events_created_at;
-- DROP INDEX CONCURRENTLY IF EXISTS idx_auth_events_created_at;
