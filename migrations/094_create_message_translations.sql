-- Migration 094: message_translations テーブルを全テナントスキーマに追加
--
-- 目的:
--   受信箱メッセージの AI 翻訳結果をキャッシュする。
--   同一メッセージ × 同一ターゲット言語の組み合わせでユニーク制約を設け、
--   2回目以降はキャッシュから即座に返す（API コスト削減）。
--
-- 影響テーブル: {tenant_NNN}.message_translations（新規作成）
-- 適用対象: 全テナント（pg_namespace 走査で冪等適用）
-- 冪等: CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS

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
            'CREATE TABLE IF NOT EXISTS %I.message_translations (
                id SERIAL PRIMARY KEY,
                message_id TEXT NOT NULL,
                target_language VARCHAR(10) NOT NULL,
                translated_text TEXT NOT NULL,
                engine VARCHAR(50) NOT NULL DEFAULT ''gemini-2.5-flash'',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_message_translations UNIQUE (message_id, target_language)
            )',
            schema_record.schema_name
        );

        EXECUTE format(
            'CREATE INDEX IF NOT EXISTS idx_message_translations_message_id
             ON %I.message_translations (message_id)',
            schema_record.schema_name
        );
    END LOOP;
END
$$;
