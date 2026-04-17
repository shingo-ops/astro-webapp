-- Phase 2: 販売・財務プロセス用パーミッション追加（public スキーマ）
--
-- 実行方法:
--   docker compose exec postgres psql -U jarvis -d jarvis_db -f /migrations/004_add_phase2_permissions.sql
--
-- 変更履歴:
--   2026-04-17: 初版作成（在庫/見積/請求/配送の権限16件）

INSERT INTO public.permissions (key, resource, action, description, category) VALUES
    -- 在庫（商品）管理
    ('products.view', 'products', 'view', '商品一覧の閲覧', '在庫'),
    ('products.create', 'products', 'create', '商品の登録', '在庫'),
    ('products.update', 'products', 'update', '商品情報の編集', '在庫'),
    ('products.delete', 'products', 'delete', '商品の削除', '在庫'),
    -- 見積管理
    ('quotes.view', 'quotes', 'view', '見積一覧の閲覧', '見積'),
    ('quotes.create', 'quotes', 'create', '見積書の作成', '見積'),
    ('quotes.update', 'quotes', 'update', '見積書の編集', '見積'),
    ('quotes.delete', 'quotes', 'delete', '見積書の削除', '見積'),
    ('quotes.approve', 'quotes', 'approve', '見積書の承認・却下', '見積'),
    -- 請求管理
    ('invoices.view', 'invoices', 'view', '請求書一覧の閲覧', '請求'),
    ('invoices.create', 'invoices', 'create', '請求書の発行', '請求'),
    ('invoices.update', 'invoices', 'update', '請求書の編集', '請求'),
    ('invoices.void', 'invoices', 'void', '請求書の無効化', '請求'),
    -- 配送管理
    ('shipping.view', 'shipping', 'view', '配送情報の閲覧', '配送'),
    ('shipping.manage', 'shipping', 'manage', '配送マスターの管理', '配送'),
    ('shipping.calculate', 'shipping', 'calculate', '配送料の自動計算', '配送')
ON CONFLICT (key) DO NOTHING;
