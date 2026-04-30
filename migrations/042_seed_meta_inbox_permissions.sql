-- Phase 1-D Sprint 1 / Migration 042: Meta Inbox 用の permissions を seed
--
-- 背景:
--   Phase 1-D（Meta Inbox UI）で必要な 4 つの権限キーを public.permissions に追加し、
--   既存テナントの「オーナー」「システム管理者」ロールに role_permissions として紐付ける。
--
-- 関連:
--   spec.md §5-8（権限定義）
--   migrations/002_add_permissions_master.sql（既存パターン）
--   migrations/025_resync_owner_admin_all_permissions.sql（owner/admin への ALL 同期パターン）
--
-- 追加される権限:
--   channels.view    : Channels 設定画面の閲覧
--   channels.manage  : Facebook Page / Instagram の OAuth 接続・切断
--   messaging.view   : Inbox の閲覧、メッセージ履歴取得、既読マーク
--   messaging.send   : メッセージ送信
--
-- 冪等性:
--   - permissions: ON CONFLICT (key) DO NOTHING
--   - role_permissions: ON CONFLICT (role_id, permission_id) DO NOTHING
--   再実行しても副作用なし。
--
-- 実行方法:
--   docker compose exec postgres psql -U <user> -d <db> -f /migrations/042_seed_meta_inbox_permissions.sql
--
-- 変更履歴:
--   2026-04-30: 初版（しんごさん依頼、Phase 1-D Sprint 1）

-- === 1. public.permissions に 4 件 INSERT ===
INSERT INTO public.permissions (key, resource, action, description, category) VALUES
    ('channels.view',    'channels',  'view',   'Channels 設定画面の閲覧',                   'メッセージ'),
    ('channels.manage',  'channels',  'manage', 'Facebook Page / Instagram の接続・切断',    'メッセージ'),
    ('messaging.view',   'messaging', 'view',   'Inbox の閲覧・メッセージ履歴取得',          'メッセージ'),
    ('messaging.send',   'messaging', 'send',   'メッセージ送信',                            'メッセージ')
ON CONFLICT (key) DO NOTHING;

-- === 2. 既存テナントの「オーナー」「システム管理者」ロールへ紐付け ===
-- migration 025 と同じパターン:
--   オーナー         : ALL（4 件すべて）
--   システム管理者   : ALL_EXCEPT_SYSTEM_MANAGE → 本 4 件はすべて system.manage 以外なので 4 件すべて

DO $meta_inbox_perms$
DECLARE
    schema_rec RECORD;
    role_rec RECORD;
    inserted_count INTEGER;
    total_inserted INTEGER := 0;
BEGIN
    FOR schema_rec IN
        SELECT nspname FROM pg_namespace
        WHERE nspname ~ '^tenant_\d+$'
        ORDER BY nspname
    LOOP
        -- roles / role_permissions 両方が存在するスキーマのみ対象
        IF NOT EXISTS (
            SELECT 1 FROM pg_tables WHERE schemaname = schema_rec.nspname AND tablename = 'roles'
        ) OR NOT EXISTS (
            SELECT 1 FROM pg_tables WHERE schemaname = schema_rec.nspname AND tablename = 'role_permissions'
        ) THEN
            CONTINUE;
        END IF;

        FOR role_rec IN
            EXECUTE format(
                'SELECT id, name FROM %I.roles WHERE name IN (''オーナー'', ''システム管理者'')',
                schema_rec.nspname
            )
        LOOP
            EXECUTE format(
                'INSERT INTO %I.role_permissions (role_id, permission_id) '
                'SELECT %s, p.id FROM public.permissions p '
                'WHERE p.key IN (''channels.view'', ''channels.manage'', ''messaging.view'', ''messaging.send'') '
                'ON CONFLICT (role_id, permission_id) DO NOTHING',
                schema_rec.nspname, role_rec.id
            );
            GET DIAGNOSTICS inserted_count = ROW_COUNT;
            IF inserted_count > 0 THEN
                RAISE NOTICE 'migration 042: %: % (id=%) に % 件の Meta Inbox 権限を追加',
                    schema_rec.nspname, role_rec.name, role_rec.id, inserted_count;
            END IF;
            total_inserted := total_inserted + inserted_count;
        END LOOP;
    END LOOP;
    RAISE NOTICE 'migration 042: 全テナント合計 % 件の権限割当を追加', total_inserted;
END $meta_inbox_perms$;
