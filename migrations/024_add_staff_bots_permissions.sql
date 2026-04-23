-- Phase 1 再設計 / Migration 024: staff / bots 用 CRUD 権限を追加
--
-- 内容:
--   public.permissions に staff.*（4件）と bots.*（4件）の CRUD 粒度権限を追加。
--   既存 permissions（CRUD粒度 73件 + menu.* 19件）と共存する。
--
-- 冪等性:
--   INSERT ... ON CONFLICT (key) DO NOTHING で再実行しても副作用なし。
--
-- 実行方法:
--   docker exec -i astro-webapp-postgres-1 psql -U jarvis -d jarvis_db \
--     -v ON_ERROR_STOP=1 < migrations/024_add_staff_bots_permissions.sql
--
-- 変更履歴:
--   2026-04-23: 初版作成

INSERT INTO public.permissions (key, resource, action, description, category) VALUES
    ('staff.view',    'staff', 'view',   'スタッフ一覧の閲覧',   'スタッフ'),
    ('staff.create',  'staff', 'create', 'スタッフの登録',       'スタッフ'),
    ('staff.update',  'staff', 'update', 'スタッフ情報の編集',   'スタッフ'),
    ('staff.delete',  'staff', 'delete', 'スタッフの削除',       'スタッフ'),
    ('bots.view',     'bots',  'view',   'Bot一覧の閲覧',        'Bot'),
    ('bots.create',   'bots',  'create', 'Botの登録',            'Bot'),
    ('bots.update',   'bots',  'update', 'Bot情報の編集',        'Bot'),
    ('bots.delete',   'bots',  'delete', 'Botの削除',            'Bot')
ON CONFLICT (key) DO NOTHING;
