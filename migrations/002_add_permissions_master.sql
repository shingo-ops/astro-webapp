-- Phase 1: パーミッションマスターテーブル作成（public スキーマ・全テナント共有）
--
-- 実行方法:
--   docker compose exec postgres psql -U jarvis -d jarvis_db -f /migrations/002_add_permissions_master.sql
--
-- 変更履歴:
--   2026-04-16: 初版作成（Discord式カスタムロール対応）

CREATE TABLE IF NOT EXISTS public.permissions (
    id SERIAL PRIMARY KEY,
    key VARCHAR(100) NOT NULL UNIQUE,
    resource VARCHAR(50) NOT NULL,
    action VARCHAR(50) NOT NULL,
    description VARCHAR(255) NOT NULL,
    category VARCHAR(50) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_permissions_key ON public.permissions (key);
CREATE INDEX IF NOT EXISTS idx_permissions_category ON public.permissions (category);

COMMENT ON TABLE public.permissions IS 'パーミッション定義マスター（全テナント共有）';

INSERT INTO public.permissions (key, resource, action, description, category) VALUES
    -- システム管理
    ('system.manage', 'system', 'manage', 'システム設定の管理', 'システム'),
    ('system.audit_view', 'system', 'audit_view', '監査ログの閲覧', 'システム'),
    -- ロール管理
    ('roles.view', 'roles', 'view', 'ロール一覧の閲覧', 'ロール'),
    ('roles.create', 'roles', 'create', 'ロールの作成', 'ロール'),
    ('roles.update', 'roles', 'update', 'ロールの編集', 'ロール'),
    ('roles.delete', 'roles', 'delete', 'ロールの削除', 'ロール'),
    ('roles.assign', 'roles', 'assign', 'ユーザーへのロール割り当て', 'ロール'),
    -- 顧客管理
    ('customers.view', 'customers', 'view', '顧客一覧の閲覧', '顧客'),
    ('customers.create', 'customers', 'create', '顧客の登録', '顧客'),
    ('customers.update', 'customers', 'update', '顧客情報の編集', '顧客'),
    ('customers.delete', 'customers', 'delete', '顧客の削除', '顧客'),
    -- リード管理
    ('leads.view', 'leads', 'view', 'リード一覧の閲覧', 'リード'),
    ('leads.create', 'leads', 'create', 'リードの登録', 'リード'),
    ('leads.update', 'leads', 'update', 'リード情報の編集', 'リード'),
    ('leads.delete', 'leads', 'delete', 'リードの削除', 'リード'),
    ('leads.convert', 'leads', 'convert', 'リードの案件化', 'リード'),
    -- 案件管理
    ('deals.view', 'deals', 'view', '案件一覧の閲覧', '案件'),
    ('deals.create', 'deals', 'create', '案件の登録', '案件'),
    ('deals.update', 'deals', 'update', '案件情報の編集', '案件'),
    ('deals.delete', 'deals', 'delete', '案件の削除', '案件'),
    -- 注文管理
    ('orders.view', 'orders', 'view', '注文一覧の閲覧', '注文'),
    ('orders.create', 'orders', 'create', '注文の登録', '注文'),
    ('orders.update', 'orders', 'update', '注文情報の編集', '注文'),
    ('orders.delete', 'orders', 'delete', '注文の削除', '注文'),
    -- チーム管理
    ('teams.view', 'teams', 'view', 'チーム一覧の閲覧', 'チーム'),
    ('teams.create', 'teams', 'create', 'チームの作成', 'チーム'),
    ('teams.update', 'teams', 'update', 'チーム情報の編集', 'チーム'),
    ('teams.delete', 'teams', 'delete', 'チームの削除', 'チーム'),
    ('teams.manage_members', 'teams', 'manage_members', 'チームメンバーの管理', 'チーム'),
    -- ダッシュボード・レポート
    ('dashboard.view', 'dashboard', 'view', 'ダッシュボードの閲覧', 'レポート'),
    ('reports.view', 'reports', 'view', 'レポートの閲覧', 'レポート'),
    ('reports.export', 'reports', 'export', 'レポートのエクスポート', 'レポート')
ON CONFLICT (key) DO NOTHING;
