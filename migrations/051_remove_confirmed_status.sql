-- ============================================================================
-- !! 警告 !! このSQLファイルは **テンプレート** です。
-- {schema}, {tenant_id} のプレースホルダを含むため、
-- そのまま psql で実行するとシンタックスエラーになります。
--
-- 必ず scripts/migrate_adr021_remove_confirmed_status.py 経由で実行してください:
--   docker compose exec backend python /app/scripts/migrate_adr021_remove_confirmed_status.py
-- ============================================================================
--
-- ADR-021 J1 fix / Migration 051: OrderStatus から `confirmed` を撤去
--
-- 目的:
--   ADR-021 第 1 節「ステータスフィルタ（未処理/仕入中/配送中/完了/トラブル/
--   キャンセル）」の正本 6 値に揃えるため、Sprint 1 で互換性のために残っていた
--   `orders.status = 'confirmed'` を `'pending'`（未処理）に統合する。
--
-- 含む処理:
--   1) UPDATE {schema}.orders SET status='pending' WHERE status='confirmed'
--   2) 移行件数を RAISE NOTICE で出力（運用ログ用）
--
-- 触らないもの:
--   - {schema}.order_purchase_details.purchase_status='confirmed'（仕入確定フラグ。
--     別ドメインの値）
--   - orders.status の CHECK 制約は **存在しない**（VARCHAR(50) DEFAULT 'pending'）
--     ため、本 migration では CHECK 操作を行わない。将来 CHECK を導入する場合は
--     別 migration とする（本 fix の Non-goal）。
--   - RLS / インデックス / トリガーへの影響なし。
--
-- 冪等性:
--   WHERE status='confirmed' で自然に保証。2 回目以降は 0 行更新となる。
--
-- ロールバック:
--   どの行が元 `confirmed` だったか追跡できないため、自動ロールバックは不可。
--   migrations/051_remove_confirmed_status_down.sql に方針のみ記載。
--   復旧が必要な場合は適用前バックアップから手動で当該行の status を戻すこと。
--
-- 変更履歴:
--   2026-05-13: 初版（ADR-021 J1 fix）
-- ============================================================================

DO $$
DECLARE
    affected_rows INTEGER;
BEGIN
    UPDATE {schema}.orders
       SET status = 'pending',
           updated_at = NOW()
     WHERE status = 'confirmed';
    GET DIAGNOSTICS affected_rows = ROW_COUNT;
    RAISE NOTICE 'migration 051: {schema}.orders confirmed -> pending: % rows', affected_rows;
END
$$;
