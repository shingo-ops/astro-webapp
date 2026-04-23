-- Phase 1 再設計: テナントID取得のヘルパ関数
--
-- 内容:
--   - 新仕様 SQL で使用する public.current_tenant_id() 関数を定義
--   - 既存ポリシーの current_setting('app.tenant_id', true)::INTEGER と等価のラッパ
--   - 既存ポリシー（migration 003, 005, 007, 009, 011 等）は従来の書き方を維持
--   - 本関数は 015 以降の新テーブル（customers系、staff系、bots）のRLSから呼ばれる
--
-- 実行方法:
--   docker compose exec postgres psql -U jarvis -d jarvis_db -f /migrations/014_create_current_tenant_id_function.sql
--
-- 変更履歴:
--   2026-04-23: 初版作成（Phase 1 再設計スプリント）

CREATE OR REPLACE FUNCTION public.current_tenant_id()
RETURNS INTEGER
LANGUAGE SQL
STABLE
AS $$
    SELECT current_setting('app.tenant_id', true)::INTEGER
$$;

COMMENT ON FUNCTION public.current_tenant_id() IS
  '現在のセッションの tenant_id を INTEGER で返す。新仕様SQL用のラッパ。既存ポリシーの current_setting(''app.tenant_id'', true)::INTEGER と完全等価';
