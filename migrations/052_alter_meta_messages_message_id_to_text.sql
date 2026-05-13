-- ============================================================================
-- !! 警告 !! このSQLファイルは **テンプレート** です。
-- {schema} のプレースホルダを含むため、
-- そのまま psql で実行するとシンタックスエラーになります。
--
-- 必ず scripts/migrate_meta_messages_message_id_to_text.py 経由で実行してください:
--   docker compose exec backend python /app/scripts/migrate_meta_messages_message_id_to_text.py
-- ============================================================================
--
-- ADR-026 / Migration 052: meta_messages.message_id を VARCHAR(100) → TEXT
--
-- 目的:
--   Instagram の Message ID (mid) は base64 多重エンコードで 150〜200 文字を超え、
--   既存定義 `VARCHAR(100)` では `StringDataRightTruncationError` で INSERT が
--   全件失敗していた（2026-05-13 切り分け済）。型を `TEXT` に拡張する。
--
-- 影響範囲:
--   - PostgreSQL の `ALTER COLUMN ... TYPE TEXT` は `VARCHAR(N)` からの lossless
--     変換であり、既存データ・index・部分 UNIQUE 制約に影響を与えない
--     （migration 013 で作成された `idx_meta_messages_message_id_unique` は
--      そのまま有効）。
--   - 既存 Messenger 受信フロー（mid 10〜30 文字）には影響なし。
--   - オンライン ALTER 可能（テーブル全行書き換えは発生しない）。
--
-- 含む処理:
--   1) information_schema.columns で `data_type` を事前確認
--      （Python ランナー側でも事前確認するが、SQL 側にも防御線を入れる）
--   2) data_type='character varying' の場合のみ ALTER COLUMN TYPE TEXT を実行
--   3) data_type='text' （既適用）の場合は RAISE NOTICE で skip ログ
--   4) どちらでもない場合は RAISE EXCEPTION（想定外の型）
--
-- 触らないもの:
--   - 既存 index（`idx_meta_messages_message_id_unique` 等）
--   - 他カラム（`sender_id`, `raw_payload` 等は現状 VARCHAR で十分）
--   - Messenger 側受信フロー（mid は短く影響なし）
--
-- 冪等性:
--   data_type の事前確認により、複数回実行しても 2 回目以降は skip。
--
-- ロールバック:
--   migrations/052_alter_meta_messages_message_id_to_text_down.sql を参照。
--   ただし長さ 100 超の行があれば down は失敗する（安全側）。
--
-- 変更履歴:
--   2026-05-13: 初版（ADR-026 / Hitoshi 即決 Q-026.1〜Q-026.4）
-- ============================================================================

DO $$
DECLARE
    current_type TEXT;
BEGIN
    SELECT data_type
      INTO current_type
      FROM information_schema.columns
     WHERE table_schema = '{schema}'
       AND table_name = 'meta_messages'
       AND column_name = 'message_id';

    IF current_type IS NULL THEN
        RAISE EXCEPTION 'migration 052: {schema}.meta_messages.message_id column not found';
    ELSIF current_type = 'text' THEN
        RAISE NOTICE 'migration 052: {schema}.meta_messages.message_id already TEXT, skipping';
    ELSIF current_type = 'character varying' THEN
        EXECUTE 'ALTER TABLE {schema}.meta_messages ALTER COLUMN message_id TYPE TEXT';
        RAISE NOTICE 'migration 052: {schema}.meta_messages.message_id altered to TEXT';
    ELSE
        RAISE EXCEPTION
            'migration 052: {schema}.meta_messages.message_id has unexpected data_type % (expected character varying or text)',
            current_type;
    END IF;
END
$$;
