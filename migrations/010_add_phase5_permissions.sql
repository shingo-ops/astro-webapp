-- Phase 5: 拡張機能用パーミッション
-- 変更履歴: 2026-04-17 初版

INSERT INTO public.permissions (key, resource, action, description, category) VALUES
    -- シフト管理
    ('shifts.view', 'shifts', 'view', 'シフトの閲覧', 'シフト'),
    ('shifts.manage', 'shifts', 'manage', 'シフトの登録・編集', 'シフト'),
    -- Buddyシステム
    ('buddy.view_own', 'buddy', 'view_own', '自分のBuddy情報の閲覧', 'Buddy'),
    ('buddy.review', 'buddy', 'review', 'Buddyフィードバックのレビュー', 'Buddy'),
    ('buddy.manage', 'buddy', 'manage', 'Buddyペアリングの管理', 'Buddy'),
    -- バッジ
    ('badges.view', 'badges', 'view', 'バッジ・実績の閲覧', 'バッジ'),
    ('badges.manage', 'badges', 'manage', 'バッジ定義の管理', 'バッジ'),
    -- ERP連携
    ('erp.view', 'erp', 'view', 'ERP連携状況の閲覧', 'ERP'),
    ('erp.sync', 'erp', 'sync', 'ERPデータ同期の実行', 'ERP')
ON CONFLICT (key) DO NOTHING;
