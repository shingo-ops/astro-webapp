-- Phase 5: 拡張機能用パーミッション
-- 変更履歴: 2026-04-17 初版

INSERT INTO public.permissions (key, resource, action, description, category) VALUES
    -- シフト管理
    ('shifts.view', 'shifts', 'view', 'シフトの閲覧', 'シフト'),
    ('shifts.manage', 'shifts', 'manage', 'シフトの登録・編集', 'シフト'),
    -- ERP連携
    ('erp.view', 'erp', 'view', 'ERP連携状況の閲覧', 'ERP'),
    ('erp.sync', 'erp', 'sync', 'ERPデータ同期の実行', 'ERP')
ON CONFLICT (key) DO NOTHING;
