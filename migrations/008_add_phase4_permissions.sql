-- Phase 4: コミュニケーション・運用機能用パーミッション
--
-- 変更履歴:
--   2026-04-17: 初版作成

INSERT INTO public.permissions (key, resource, action, description, category) VALUES
    -- Discord通知
    ('notifications.view', 'notifications', 'view', '通知設定の閲覧', '通知'),
    ('notifications.manage', 'notifications', 'manage', '通知設定の管理', '通知'),
    -- 日報・週報・月報
    ('staff_reports.view_own', 'staff_reports', 'view_own', '自分のレポートの閲覧', 'レポート'),
    ('staff_reports.view_team', 'staff_reports', 'view_team', 'チームのレポートの閲覧', 'レポート'),
    ('staff_reports.create', 'staff_reports', 'create', 'レポートの提出', 'レポート'),
    ('staff_reports.review', 'staff_reports', 'review', 'レポートのレビュー', 'レポート'),
    -- アーカイブ
    ('archive.view', 'archive', 'view', 'アーカイブの閲覧', 'アーカイブ'),
    ('archive.manage', 'archive', 'manage', 'アーカイブ・復元の実行', 'アーカイブ')
ON CONFLICT (key) DO NOTHING;
