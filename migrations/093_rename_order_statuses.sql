-- Migration 090: orders.status を 6 新値に改名
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

DO $$
DECLARE
  cnt INTEGER;
BEGIN
  UPDATE orders SET status = 'awaiting_payment' WHERE status = 'pending';
  GET DIAGNOSTICS cnt = ROW_COUNT;
  RAISE NOTICE 'pending → awaiting_payment: % rows', cnt;

  UPDATE orders SET status = 'sourcing' WHERE status = 'processing';
  GET DIAGNOSTICS cnt = ROW_COUNT;
  RAISE NOTICE 'processing → sourcing: % rows', cnt;

  UPDATE orders SET status = 'completed' WHERE status IN ('shipped', 'delivered');
  GET DIAGNOSTICS cnt = ROW_COUNT;
  RAISE NOTICE 'shipped/delivered → completed: % rows', cnt;

  UPDATE orders SET status = 'trouble' WHERE status = 'returned';
  GET DIAGNOSTICS cnt = ROW_COUNT;
  RAISE NOTICE 'returned → trouble: % rows', cnt;
END $$;
