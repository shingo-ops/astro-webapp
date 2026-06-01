-- Migration 093: orders.status を 6 新値に改名
--
-- 旧値 → 新値 マッピング:
--   pending    → awaiting_payment  （支払い待ち）
--   processing → sourcing          （仕入れ中）
--   shipped    → completed         （完了 — 配送済みも完了に統合）
--   delivered  → completed         （完了）
--   returned   → trouble           （トラブル）
--   cancelled  → cancelled         （変更なし）
--   ※ awaiting_shipping（発送待ち）は新設値、既存データへの対応なし
--
-- 冪等: WHERE status = '旧値' により再実行しても影響なし
-- スキーマ対応: pg_namespace 走査で全テナントスキーマを反復
-- orders テーブルが存在しないスキーマは skip（古いテナント対応）

DO $$
DECLARE
  schema_record RECORD;
  cnt INTEGER;
BEGIN
  FOR schema_record IN
    SELECT nspname AS schema_name
    FROM pg_namespace
    WHERE nspname LIKE 'tenant_%'
    ORDER BY nspname
  LOOP
    IF EXISTS (
      SELECT 1 FROM information_schema.tables
      WHERE table_schema = schema_record.schema_name
        AND table_name = 'orders'
    ) THEN
      EXECUTE format(
        'UPDATE %I.orders SET status = ''awaiting_payment'' WHERE status = ''pending''',
        schema_record.schema_name
      );
      GET DIAGNOSTICS cnt = ROW_COUNT;
      RAISE NOTICE '% pending → awaiting_payment: % rows', schema_record.schema_name, cnt;

      EXECUTE format(
        'UPDATE %I.orders SET status = ''sourcing'' WHERE status = ''processing''',
        schema_record.schema_name
      );
      GET DIAGNOSTICS cnt = ROW_COUNT;
      RAISE NOTICE '% processing → sourcing: % rows', schema_record.schema_name, cnt;

      EXECUTE format(
        'UPDATE %I.orders SET status = ''completed'' WHERE status IN (''shipped'', ''delivered'')',
        schema_record.schema_name
      );
      GET DIAGNOSTICS cnt = ROW_COUNT;
      RAISE NOTICE '% shipped/delivered → completed: % rows', schema_record.schema_name, cnt;

      EXECUTE format(
        'UPDATE %I.orders SET status = ''trouble'' WHERE status = ''returned''',
        schema_record.schema_name
      );
      GET DIAGNOSTICS cnt = ROW_COUNT;
      RAISE NOTICE '% returned → trouble: % rows', schema_record.schema_name, cnt;
    ELSE
      RAISE NOTICE '% orders テーブルなし (skip)', schema_record.schema_name;
    END IF;
  END LOOP;
END $$;
