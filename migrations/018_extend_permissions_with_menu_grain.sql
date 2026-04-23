-- Phase 1 再設計 / Migration 018: public.permissions にメニュー粒度の権限を追加
--
-- 内容:
--   [1] 既存 public.permissions テーブルにメニュー粒度用の列を追加（NULL 許容）
--       - permission_group（chat / sales / settings / buddy / admin）
--       - display_name_jp / display_name_en（UI表示名）
--       - display_order（UI並び順）
--   [2] 新仕様（設計書第2弾 3-3）の19件をシード
--
-- 共存方針（2026-04-23 Q3 確定）:
--   - 既存 65件（key='customers.view' 等の CRUD 粒度）は**そのまま残す**
--   - 新 19件は key='menu.dashboard' 等のプレフィックス付きで追加
--   - 既存の role_permissions・アプリ層 API 認可は従来通り動作
--   - 新 19件はメニュー表示制御（サイドバー）用に別途使用
--
-- 実行方法:
--   docker compose exec postgres psql -U jarvis -d jarvis_db -f /migrations/018_extend_permissions_with_menu_grain.sql
--
-- 変更履歴:
--   2026-04-23: 初版作成

-- === [1] 既存 public.permissions に列追加 ===

ALTER TABLE public.permissions ADD COLUMN IF NOT EXISTS permission_group VARCHAR(50);
ALTER TABLE public.permissions ADD COLUMN IF NOT EXISTS display_name_jp VARCHAR(100);
ALTER TABLE public.permissions ADD COLUMN IF NOT EXISTS display_name_en VARCHAR(100);
ALTER TABLE public.permissions ADD COLUMN IF NOT EXISTS display_order INTEGER;

CREATE INDEX IF NOT EXISTS idx_permissions_group ON public.permissions (permission_group);
CREATE INDEX IF NOT EXISTS idx_permissions_display_order ON public.permissions (display_order);

COMMENT ON COLUMN public.permissions.permission_group IS
  'メニュー粒度権限のグループ（chat / sales / settings / buddy / admin）。CRUD粒度権限は NULL';
COMMENT ON COLUMN public.permissions.display_name_jp IS
  'UI表示用の日本語名。メニュー権限のみ入力、CRUD権限は NULL（description を流用）';
COMMENT ON COLUMN public.permissions.display_order IS
  'サイドバー表示順。メニュー権限のみ設定';

-- === [2] 新仕様 19件のシード（chat: 6件 / sales: 5件 / buddy: 2件 / admin: 5件 / settings: 1件）===

INSERT INTO public.permissions
    (key,                        resource, action,   description,                     category,     permission_group, display_name_jp,           display_order)
VALUES
    -- chat 配下（6件）
    ('menu.dashboard',           'menu',   'access', 'ダッシュボードへのアクセス',       'メニュー',   'chat',           'ダッシュボード',           1),
    ('menu.lead_chat',           'menu',   'access', 'リードチャットへのアクセス',       'メニュー',   'chat',           'リードチャット',           2),
    ('menu.new_customer_chat',   'menu',   'access', '新規顧客チャットへのアクセス',     'メニュー',   'chat',           '新規顧客チャット',         3),
    ('menu.route_customer_chat', 'menu',   'access', 'ルート顧客チャットへのアクセス',   'メニュー',   'chat',           'ルート顧客チャット',       4),
    ('menu.archive_chat',        'menu',   'access', 'アーカイブチャットへのアクセス',   'メニュー',   'chat',           'アーカイブチャット',       5),
    ('menu.faq',                 'menu',   'access', 'FAQへのアクセス',                 'メニュー',   'chat',           'FAQ',                     6),
    -- sales 配下（5件）
    ('menu.inventory',           'menu',   'access', '在庫メニューへのアクセス',         'メニュー',   'sales',          '在庫',                    7),
    ('menu.quote_create',        'menu',   'access', '見積もり作成へのアクセス',         'メニュー',   'sales',          '見積もり作成',             8),
    ('menu.quote_history',       'menu',   'access', '見積もり履歴へのアクセス',         'メニュー',   'sales',          '見積もり履歴',             9),
    ('menu.invoice_create',      'menu',   'access', '請求書作成へのアクセス',           'メニュー',   'sales',          '請求書作成',              10),
    ('menu.report',              'menu',   'access', 'レポートへのアクセス',             'メニュー',   'sales',          'レポート',                11),
    -- buddy 配下（2件）
    ('menu.product_knowledge',   'menu',   'access', '商材ナレッジへのアクセス',         'メニュー',   'buddy',          '商材ナレッジ',            12),
    ('menu.translation_prompt',  'menu',   'access', '翻訳プロンプトへのアクセス',       'メニュー',   'buddy',          '翻訳プロンプト',          13),
    -- admin 配下（5件）
    ('menu.deal_management',     'menu',   'access', '商談管理へのアクセス',             'メニュー',   'admin',          '商談管理',                14),
    ('menu.template_management', 'menu',   'access', 'テンプレート管理へのアクセス',     'メニュー',   'admin',          'テンプレート管理',        15),
    ('menu.staff_management',    'menu',   'access', 'スタッフ管理へのアクセス',         'メニュー',   'admin',          'スタッフ管理',            16),
    ('menu.role_management',     'menu',   'access', '権限管理へのアクセス',             'メニュー',   'admin',          '権限管理',                17),
    ('menu.data_management',     'menu',   'access', 'データ管理へのアクセス',           'メニュー',   'admin',          'データ管理',              18),
    -- settings 配下（1件）
    ('menu.display_settings',    'menu',   'access', '表示設定へのアクセス',             'メニュー',   'settings',       '表示設定',                19)
ON CONFLICT (key) DO NOTHING;
