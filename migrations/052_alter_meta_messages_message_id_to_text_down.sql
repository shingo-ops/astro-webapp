-- ============================================================================
-- !! 警告 !! このSQLファイルは **テンプレート** です。
-- {schema} のプレースホルダを含むため、
-- そのまま psql で実行するとシンタックスエラーになります。
--
-- 必ず scripts/migrate_meta_messages_message_id_to_text.py の rollback 経路、
-- または手動で {schema} を置換した上で psql に流してください。
-- ============================================================================
--
-- ADR-026 / Migration 052 DOWN: meta_messages.message_id を TEXT → VARCHAR(100)
--
-- 前提条件（Hitoshi 即決 Q-026.2: 失敗させる / truncate しない）:
--   既存データに長さ 100 を超える `message_id` が **1 行も存在しない** ことが
--   保証されない限り、本 down 適用は失敗する。長さ超過行を truncate するのは
--   過去メッセージ ID の整合性を破壊する破壊的操作であり、自動 rollback では
--   絶対に行わない。
--
-- 実施手順:
--   1) information_schema.columns で `data_type` を事前確認
--      - 'character varying' なら既に VARCHAR、skip ログ
--      - 'text' のみ down 対象
--   2) MAX(length(message_id)) を計算し、100 超があれば RAISE EXCEPTION
--   3) ALTER TABLE ... TYPE VARCHAR(100) を実行
--
-- 100 超の行があった場合の対応:
--   a) IG webhook の長 mid が既に DB に書き込まれている → down 不可、運用判断
--   b) どうしても元に戻す必要があれば、当該行を別テーブルに退避してから
--      手動で削除し、再度 down を試す（本 down 内では一切自動削除しない）
--
-- 含む処理:
--   1) data_type 事前確認
--   2) MAX(length(message_id)) <= 100 を assert
--   3) ALTER COLUMN TYPE VARCHAR(100)
--
-- 冪等性:
--   data_type の事前確認により skip 可能。
--
-- 変更履歴:
--   2026-05-13: 初版（ADR-026 / Hitoshi 即決 Q-026.2）
-- ============================================================================

DO $$
DECLARE
    current_type TEXT;
    max_len INTEGER;
BEGIN
    SELECT data_type
      INTO current_type
      FROM information_schema.columns
     WHERE table_schema = '{schema}'
       AND table_name = 'meta_messages'
       AND column_name = 'message_id';

    IF current_type IS NULL THEN
        RAISE EXCEPTION 'migration 052 down: {schema}.meta_messages.message_id column not found';
    ELSIF current_type = 'character varying' THEN
        RAISE NOTICE 'migration 052 down: {schema}.meta_messages.message_id already character varying, skipping';
        RETURN;
    ELSIF current_type <> 'text' THEN
        RAISE EXCEPTION
            'migration 052 down: {schema}.meta_messages.message_id has unexpected data_type % (expected text)',
            current_type;
    END IF;

    -- 安全側: 100 超の値があれば down を失敗させる
    EXECUTE 'SELECT COALESCE(MAX(length(message_id)), 0) FROM {schema}.meta_messages'
       INTO max_len;

    IF max_len > 100 THEN
        RAISE EXCEPTION
            'migration 052 down: {schema}.meta_messages contains message_id of length % (> 100). Refusing to truncate. Inspect and manually remove offending rows before retrying.',
            max_len;
    END IF;

    EXECUTE 'ALTER TABLE {schema}.meta_messages ALTER COLUMN message_id TYPE VARCHAR(100)';
    RAISE NOTICE 'migration 052 down: {schema}.meta_messages.message_id altered back to VARCHAR(100) (max observed length=%)', max_len;
END
$$;
