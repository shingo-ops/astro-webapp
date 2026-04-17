-- Phase 3: 営業支援・分析用パーミッション追加（public スキーマ）
--
-- 実行方法:
--   docker compose exec postgres psql -U jarvis -d jarvis_db -f /migrations/006_add_phase3_permissions.sql
--
-- 変更履歴:
--   2026-04-17: 初版作成（仕入先/仕入注文の権限8件）

INSERT INTO public.permissions (key, resource, action, description, category) VALUES
    -- 仕入先管理
    ('suppliers.view', 'suppliers', 'view', '仕入先一覧の閲覧', '仕入'),
    ('suppliers.create', 'suppliers', 'create', '仕入先の登録', '仕入'),
    ('suppliers.update', 'suppliers', 'update', '仕入先情報の編集', '仕入'),
    ('suppliers.delete', 'suppliers', 'delete', '仕入先の削除', '仕入'),
    -- 仕入注文管理
    ('purchase_orders.view', 'purchase_orders', 'view', '仕入注文一覧の閲覧', '仕入'),
    ('purchase_orders.create', 'purchase_orders', 'create', '仕入注文の作成', '仕入'),
    ('purchase_orders.update', 'purchase_orders', 'update', '仕入注文の編集', '仕入'),
    ('purchase_orders.receive', 'purchase_orders', 'receive', '仕入注文の入荷処理', '仕入')
ON CONFLICT (key) DO NOTHING;
