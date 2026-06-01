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
-- 影響テーブル: {tenant_NNN}.meta_messages
-- 適用対象: 全テナント（pg_namespace 走査で冪等適用）
-- 冪等性: ADD COLUMN IF NOT EXISTS で再実行可能。
--
-- 変更履歴:
--   2026-06-01: 初版（しんごさん依頼、受信箱画像送信 Sprint 2）
--   2026-06-01: {schema} テンプレートを DO $$ pg_namespace 走査形式に修正（本番デプロイ障害対応）

DO $$
DECLARE
    schema_record RECORD;
BEGIN
    FOR schema_record IN
        SELECT nspname AS schema_name
        FROM pg_namespace
        WHERE nspname LIKE 'tenant_%'
        ORDER BY nspname
    LOOP
        RAISE NOTICE 'Processing schema: %', schema_record.schema_name;

        EXECUTE format(
            'ALTER TABLE %I.meta_messages
             ADD COLUMN IF NOT EXISTS attachment_url  TEXT,
             ADD COLUMN IF NOT EXISTS attachment_type VARCHAR(20)',
            schema_record.schema_name
        );
    END LOOP;
END
$$;
