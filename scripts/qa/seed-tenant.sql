-- ============================================================================
-- ADR-038 / QA Smoke Suite: tenant_006 (tenant-review) 用 seed SQL
--
-- 目的:
--   QA Gate tenant_006 を「実データ入りの known state」に冪等 reset する。
--   毎スプリント開始時 (reset-tenant.sh) と CI 失敗復旧時に再投入する。
--
-- 設計:
--   - **tenant_code assert を最初に必ず実行** (`tenant_006` 以外で実行されたら
--     RAISE EXCEPTION で即停止し、他テナントを破壊しない)
--   - TRUNCATE で seed 対象テーブルを空にしたあと、固定 ID で INSERT する
--   - 接頭辞 `qa-` (英小文字) / `QA-` (英大文字) のいずれかを使い、
--     cleanup-smoke-data.sh から後追いで安全に削除可能
--   - 全件投入後に **行数 assert** を行い、ADR-038 の seed 表と差異があれば停止
--   - tenant_meta_config / meta_oauth_tokens は ADR-025 で「OAuth フロー外での
--     手動 INSERT 原則禁止」だが、本 seed は ADR-038 の書面承認 + QA Gate 専用
--     tenant_006 への限定投入 + audit_logs への manual_db_insert 記録で例外条件
--     1〜5 をすべて満たす
--
-- psql 変数 (reset-tenant.sh から -v で渡される):
--   :qa_admin_firebase_uid   admin ユーザーの Firebase UID
--   :qa_staff_firebase_uid   staff ユーザーの Firebase UID
--   :qa_viewer_firebase_uid  viewer ユーザーの Firebase UID
--   :qa_admin_password_hash  bcrypt 済 password hash (fallback 用)
--   :qa_staff_password_hash
--   :qa_viewer_password_hash
--
-- 関連:
--   docs/adr/ADR-038-qa-smoke-suite.md
--   docs/adr/ADR-025_meta_integration_operational_hardening.md
--   scripts/qa/reset-tenant.sh
--   scripts/qa/cleanup-smoke-data.sh
--
-- 変更履歴:
--   2026-05-15: ADR-038 初版
-- ============================================================================

\set ON_ERROR_STOP on
\set TENANT_ID 6
\set TENANT_CODE '''tenant-review'''
\set SCHEMA tenant_006

BEGIN;

-- ---------------------------------------------------------------------------
-- 0. tenant_code assert (誤実行ガード)
-- ---------------------------------------------------------------------------
DO $assert_tenant$
DECLARE
    actual_code TEXT;
BEGIN
    SELECT tenant_code INTO actual_code FROM public.tenants WHERE id = 6;
    IF actual_code IS NULL THEN
        RAISE EXCEPTION 'seed abort: public.tenants.id=6 が存在しません。setup_review_tenant.py を先に実行してください';
    END IF;
    IF actual_code <> 'tenant-review' THEN
        RAISE EXCEPTION 'seed abort: tenant_id=6 の tenant_code は %% だが、期待値は tenant-review。誤実行防止のため停止', actual_code;
    END IF;
    RAISE NOTICE 'tenant_code assert OK: tenant_id=6, tenant_code=tenant-review';
END
$assert_tenant$;

-- ---------------------------------------------------------------------------
-- 1. RLS 用の app.tenant_id を設定 (tenant_006 schema のテーブル用)
-- ---------------------------------------------------------------------------
SET search_path = tenant_006, public;
SELECT set_config('app.tenant_id', '6', false);

-- ---------------------------------------------------------------------------
-- 2. TRUNCATE seed 対象テーブル (FK 依存順)
--    - 子テーブル → 親テーブルの順
--    - public.meta_page_routing は CASCADE 不要 (単独テーブル)
-- ---------------------------------------------------------------------------
TRUNCATE TABLE
    tenant_006.meta_messages,
    tenant_006.tenant_meta_config,
    tenant_006.orders,
    tenant_006.contacts,
    tenant_006.companies,
    tenant_006.leads,
    tenant_006.products
    RESTART IDENTITY CASCADE;

DELETE FROM public.meta_page_routing WHERE tenant_id = 6;

-- public.users と tenant_006.staff の QA ユーザー (qa- 接頭辞) は再投入のため一旦削除
DELETE FROM tenant_006.staff_ui_preferences
    WHERE staff_id IN (SELECT id FROM tenant_006.staff WHERE primary_email LIKE 'qa-%');
DELETE FROM tenant_006.user_roles
    WHERE user_id IN (SELECT id FROM public.users WHERE email LIKE 'qa-%@salesanchor.jp');
DELETE FROM tenant_006.staff WHERE primary_email LIKE 'qa-%';
DELETE FROM public.users WHERE email LIKE 'qa-%@salesanchor.jp';

-- ---------------------------------------------------------------------------
-- 3. users 3 件 (admin / staff / viewer)
--    - locale=ja 固定 (ADR-038 seed 表)
--    - email は `qa-` 接頭辞でクリーンアップ可能
-- ---------------------------------------------------------------------------
INSERT INTO public.users (tenant_id, username, email, password_hash, full_name, role, is_active, locale)
VALUES
    (6, 'qa-admin',  'qa-admin@salesanchor.jp',  :'qa_admin_password_hash',  'QA Admin',  'admin',  TRUE, 'ja'),
    (6, 'qa-staff',  'qa-staff@salesanchor.jp',  :'qa_staff_password_hash',  'QA Staff',  'user',   TRUE, 'ja'),
    (6, 'qa-viewer', 'qa-viewer@salesanchor.jp', :'qa_viewer_password_hash', 'QA Viewer', 'user',   TRUE, 'ja');

-- tenant_006.staff (per-tenant) と role 紐付け
-- role_id は seed_system_roles で既に作成済 (オーナー / システム管理者 / 営業)
INSERT INTO tenant_006.staff (tenant_id, user_id, staff_code, surname_jp, given_name_jp, primary_email, role_id, status, firebase_uid)
SELECT 6, u.id, 'QA-ADMIN-001', 'QA', 'Admin', u.email, r.id, 'active', :'qa_admin_firebase_uid'
FROM public.users u, tenant_006.roles r
WHERE u.email = 'qa-admin@salesanchor.jp' AND r.tenant_id = 6 AND r.name = 'オーナー';

INSERT INTO tenant_006.staff (tenant_id, user_id, staff_code, surname_jp, given_name_jp, primary_email, role_id, status, firebase_uid)
SELECT 6, u.id, 'QA-STAFF-001', 'QA', 'Staff', u.email, r.id, 'active', :'qa_staff_firebase_uid'
FROM public.users u, tenant_006.roles r
WHERE u.email = 'qa-staff@salesanchor.jp' AND r.tenant_id = 6 AND r.name = '営業';

INSERT INTO tenant_006.staff (tenant_id, user_id, staff_code, surname_jp, given_name_jp, primary_email, role_id, status, firebase_uid)
SELECT 6, u.id, 'QA-VIEWER-001', 'QA', 'Viewer', u.email, r.id, 'active', :'qa_viewer_firebase_uid'
FROM public.users u, tenant_006.roles r
WHERE u.email = 'qa-viewer@salesanchor.jp' AND r.tenant_id = 6 AND r.name = 'CS';

INSERT INTO tenant_006.staff_ui_preferences (staff_id)
SELECT id FROM tenant_006.staff WHERE primary_email LIKE 'qa-%';

INSERT INTO tenant_006.user_roles (user_id, role_id)
SELECT u.id, s.role_id
FROM public.users u
JOIN tenant_006.staff s ON s.primary_email = u.email
WHERE u.email LIKE 'qa-%@salesanchor.jp'
ON CONFLICT DO NOTHING;

-- ---------------------------------------------------------------------------
-- 4. leads 5 件 (status: 新規 / 対応中 / 評価済 / 失注 / 受注)
--    - lead_code は QA- 接頭辞で識別可能
--    - status 値は既存実装の VARCHAR(50) で「新規 / 対応中 / 評価済 / 失注 / 受注」
-- ---------------------------------------------------------------------------
INSERT INTO tenant_006.leads (tenant_id, lead_code, customer_name, company_name, email, source, status, ai_collection_state)
VALUES
    (6, 'QA-LD-001', 'QA Lead New',       'QA Company A', 'qa-lead-new@example.com',       'web',       '新規',     'completed'),
    (6, 'QA-LD-002', 'QA Lead Contacted', 'QA Company B', 'qa-lead-contacted@example.com', 'instagram', '対応中',   'completed'),
    (6, 'QA-LD-003', 'QA Lead Qualified', 'QA Company C', 'qa-lead-qualified@example.com', 'messenger', '評価済',   'completed'),
    (6, 'QA-LD-004', 'QA Lead Lost',      'QA Company D', 'qa-lead-lost@example.com',      'web',       '失注',     'completed'),
    (6, 'QA-LD-005', 'QA Lead Won',       'QA Company E', 'qa-lead-won@example.com',       'web',       '受注',     'completed');

-- ---------------------------------------------------------------------------
-- 5. companies 5 件 (うち 2 件は Meta Channel 接続済 — companies と
--    tenant_meta_config の page_id を後で対応付け)
-- ---------------------------------------------------------------------------
INSERT INTO tenant_006.companies (tenant_id, company_code, lead_id, name, name_en, industry, status)
SELECT 6, 'QA-CO-001', l.id, 'QA Company A', 'QA Company A Ltd.', 'B2B EC', 'active' FROM tenant_006.leads l WHERE l.lead_code='QA-LD-001';
INSERT INTO tenant_006.companies (tenant_id, company_code, lead_id, name, name_en, industry, status)
SELECT 6, 'QA-CO-002', l.id, 'QA Company B', 'QA Company B Ltd.', 'B2B EC', 'active' FROM tenant_006.leads l WHERE l.lead_code='QA-LD-002';
INSERT INTO tenant_006.companies (tenant_id, company_code, lead_id, name, name_en, industry, status)
SELECT 6, 'QA-CO-003', l.id, 'QA Company C', 'QA Company C Ltd.', 'B2B EC', 'active' FROM tenant_006.leads l WHERE l.lead_code='QA-LD-003';
INSERT INTO tenant_006.companies (tenant_id, company_code, lead_id, name, name_en, industry, status)
SELECT 6, 'QA-CO-004', l.id, 'QA Company D', 'QA Company D Ltd.', 'B2B EC', 'active' FROM tenant_006.leads l WHERE l.lead_code='QA-LD-004';
INSERT INTO tenant_006.companies (tenant_id, company_code, lead_id, name, name_en, industry, status)
SELECT 6, 'QA-CO-005', l.id, 'QA Company E', 'QA Company E Ltd.', 'B2B EC', 'active' FROM tenant_006.leads l WHERE l.lead_code='QA-LD-005';

-- ---------------------------------------------------------------------------
-- 6. contacts 5 件 (1社1担当者)
-- ---------------------------------------------------------------------------
INSERT INTO tenant_006.contacts (tenant_id, company_id, contact_code, lead_id, display_name, primary_email, status)
SELECT 6, c.id, 'QA-CT-001', c.lead_id, 'QA Contact A', 'qa-contact-a@example.com', 'active' FROM tenant_006.companies c WHERE c.company_code='QA-CO-001';
INSERT INTO tenant_006.contacts (tenant_id, company_id, contact_code, lead_id, display_name, primary_email, status)
SELECT 6, c.id, 'QA-CT-002', c.lead_id, 'QA Contact B', 'qa-contact-b@example.com', 'active' FROM tenant_006.companies c WHERE c.company_code='QA-CO-002';
INSERT INTO tenant_006.contacts (tenant_id, company_id, contact_code, lead_id, display_name, primary_email, status)
SELECT 6, c.id, 'QA-CT-003', c.lead_id, 'QA Contact C', 'qa-contact-c@example.com', 'active' FROM tenant_006.companies c WHERE c.company_code='QA-CO-003';
INSERT INTO tenant_006.contacts (tenant_id, company_id, contact_code, lead_id, display_name, primary_email, status)
SELECT 6, c.id, 'QA-CT-004', c.lead_id, 'QA Contact D', 'qa-contact-d@example.com', 'active' FROM tenant_006.companies c WHERE c.company_code='QA-CO-004';
INSERT INTO tenant_006.contacts (tenant_id, company_id, contact_code, lead_id, display_name, primary_email, status)
SELECT 6, c.id, 'QA-CT-005', c.lead_id, 'QA Contact E', 'qa-contact-e@example.com', 'active' FROM tenant_006.companies c WHERE c.company_code='QA-CO-005';

-- ---------------------------------------------------------------------------
-- 7. orders 3 件 (status: pending / shipped / canceled)
--    deal_id は seed では未使用 (NULL 許容)、order_number は QA- 接頭辞
-- ---------------------------------------------------------------------------
INSERT INTO tenant_006.orders (tenant_id, company_id, contact_id, order_number, total_amount, status)
SELECT 6, c.id, ct.id, 'QA-OR-001', 15000.00, 'pending'
FROM tenant_006.companies c JOIN tenant_006.contacts ct ON ct.company_id=c.id WHERE c.company_code='QA-CO-001';
INSERT INTO tenant_006.orders (tenant_id, company_id, contact_id, order_number, total_amount, status)
SELECT 6, c.id, ct.id, 'QA-OR-002', 32500.00, 'shipped'
FROM tenant_006.companies c JOIN tenant_006.contacts ct ON ct.company_id=c.id WHERE c.company_code='QA-CO-002';
INSERT INTO tenant_006.orders (tenant_id, company_id, contact_id, order_number, total_amount, status)
SELECT 6, c.id, ct.id, 'QA-OR-003', 8900.00, 'canceled'
FROM tenant_006.companies c JOIN tenant_006.contacts ct ON ct.company_id=c.id WHERE c.company_code='QA-CO-003';

-- ---------------------------------------------------------------------------
-- 8. products 5 件 (カテゴリ違い)
-- ---------------------------------------------------------------------------
INSERT INTO tenant_006.products (tenant_id, product_code, category, name_ja, name_en, status, unit_price, quantity)
VALUES
    (6, 'QA-PR-001', 'TCG-pokemon',  'QA ポケモンカードA',   'QA Pokemon Card A',  'active', 1500.00, 10),
    (6, 'QA-PR-002', 'TCG-yugioh',   'QA 遊戯王カードB',     'QA Yu-Gi-Oh Card B', 'active', 2300.00, 5),
    (6, 'QA-PR-003', 'manga',        'QA 漫画C',             'QA Manga C',         'active', 880.00,  20),
    (6, 'QA-PR-004', 'figure',       'QA フィギュアD',       'QA Figure D',        'active', 4500.00, 3),
    (6, 'QA-PR-005', 'game',         'QA ゲームE',           'QA Game E',          'active', 6800.00, 7);

-- ---------------------------------------------------------------------------
-- 9. tenant_meta_config 2 件 (接続済 page) + public.meta_page_routing 2 件
--    - ADR-025: 通常は OAuth フロー外の直 INSERT 禁止だが、QA Gate tenant_006
--      かつ ADR-038 書面承認下なので例外条件を満たす
--    - encrypted token は dummy bytes (本番 Fernet key で復号不可)
--    - audit_logs に manual_db_insert を記録 (ADR-025 例外条件 #3)
-- ---------------------------------------------------------------------------
INSERT INTO tenant_006.tenant_meta_config (
    tenant_id, page_id, page_name, page_access_token_encrypted,
    instagram_business_account_id, instagram_username, subscribed_fields,
    connected_at, is_active
)
VALUES
    (6, 'QA-PAGE-1000000000000001', 'QA Test Page Alpha',
     decode('00', 'hex'),                                  -- dummy ciphertext
     'QA-IG-2000000000000001', 'qa_test_alpha',
     '["messages","messaging_postbacks","message_reactions"]'::jsonb,
     NOW(), TRUE),
    (6, 'QA-PAGE-1000000000000002', 'QA Test Page Beta',
     decode('00', 'hex'),
     'QA-IG-2000000000000002', 'qa_test_beta',
     '["messages","messaging_postbacks","message_reactions"]'::jsonb,
     NOW(), TRUE);

INSERT INTO public.meta_page_routing (tenant_id, config_id, schema_name, page_id, instagram_business_account_id, is_active)
SELECT 6, c.id, 'tenant_006', c.page_id, c.instagram_business_account_id, TRUE
FROM tenant_006.tenant_meta_config c
WHERE c.tenant_id = 6 AND c.is_active = TRUE;

-- ---------------------------------------------------------------------------
-- 10. meta_messages 10 件 (messenger 6 + instagram 4)
--     - message_id は ADR-026 で TEXT 型化済。100 文字超え (105 文字) を 1 件含める
--     - lead_id は seed 済 leads から借用
-- ---------------------------------------------------------------------------
INSERT INTO tenant_006.meta_messages (tenant_id, lead_id, platform, sender_id, sender_name, message_text, direction, message_id, raw_payload)
SELECT 6, l.id, 'messenger', 'QA-PSID-001', 'QA Sender 1', 'Hello, do you ship to JP?', 'inbound',
       'qa-mid.' || repeat('a', 12),
       jsonb_build_object('platform','messenger','test',TRUE)
FROM tenant_006.leads l WHERE l.lead_code='QA-LD-001';

INSERT INTO tenant_006.meta_messages (tenant_id, lead_id, platform, sender_id, sender_name, message_text, direction, message_id, raw_payload)
SELECT 6, l.id, 'messenger', 'QA-PSID-002', 'QA Sender 2', 'I have a question about pricing', 'inbound',
       'qa-mid.' || repeat('b', 14),
       jsonb_build_object('platform','messenger','test',TRUE)
FROM tenant_006.leads l WHERE l.lead_code='QA-LD-002';

INSERT INTO tenant_006.meta_messages (tenant_id, lead_id, platform, sender_id, sender_name, message_text, direction, message_id, raw_payload)
SELECT 6, l.id, 'messenger', 'QA-PSID-001', 'QA Sender 1', 'Sure, we ship worldwide via FedEx', 'outbound',
       'qa-mid.' || repeat('c', 16),
       jsonb_build_object('platform','messenger','test',TRUE)
FROM tenant_006.leads l WHERE l.lead_code='QA-LD-001';

INSERT INTO tenant_006.meta_messages (tenant_id, lead_id, platform, sender_id, sender_name, message_text, direction, message_id, raw_payload)
SELECT 6, l.id, 'messenger', 'QA-PSID-003', 'QA Sender 3', 'Order #QA-OR-001 confirmation?', 'inbound',
       'qa-mid.' || repeat('d', 18),
       jsonb_build_object('platform','messenger','test',TRUE)
FROM tenant_006.leads l WHERE l.lead_code='QA-LD-002';

INSERT INTO tenant_006.meta_messages (tenant_id, lead_id, platform, sender_id, sender_name, message_text, direction, message_id, raw_payload)
SELECT 6, l.id, 'messenger', 'QA-PSID-004', 'QA Sender 4', 'Got the tracking number, thanks', 'inbound',
       'qa-mid.' || repeat('e', 20),
       jsonb_build_object('platform','messenger','test',TRUE)
FROM tenant_006.leads l WHERE l.lead_code='QA-LD-003';

-- message_id が 100 文字超え (105 文字) — ADR-026 / scene-04 で TEXT 型確認の根拠
INSERT INTO tenant_006.meta_messages (tenant_id, lead_id, platform, sender_id, sender_name, message_text, direction, message_id, raw_payload)
SELECT 6, l.id, 'messenger', 'QA-PSID-005', 'QA Sender 5', 'Long message_id test (105 chars)', 'inbound',
       'qa-mid.' || repeat('x', 98),  -- 'qa-mid.' (7) + 98 = 105 文字
       jsonb_build_object('platform','messenger','test',TRUE,'long_id_test',TRUE)
FROM tenant_006.leads l WHERE l.lead_code='QA-LD-001';

-- instagram 4 件
INSERT INTO tenant_006.meta_messages (tenant_id, lead_id, platform, sender_id, sender_name, message_text, direction, message_id, raw_payload)
SELECT 6, l.id, 'instagram', 'QA-IGSID-001', 'qa_ig_user_1', 'Hi via Instagram DM', 'inbound',
       'qa-igmid.' || repeat('f', 20),
       jsonb_build_object('platform','instagram','test',TRUE)
FROM tenant_006.leads l WHERE l.lead_code='QA-LD-002';

INSERT INTO tenant_006.meta_messages (tenant_id, lead_id, platform, sender_id, sender_name, message_text, direction, message_id, raw_payload)
SELECT 6, l.id, 'instagram', 'QA-IGSID-002', 'qa_ig_user_2', 'Are you open today?', 'inbound',
       'qa-igmid.' || repeat('g', 22),
       jsonb_build_object('platform','instagram','test',TRUE)
FROM tenant_006.leads l WHERE l.lead_code='QA-LD-003';

INSERT INTO tenant_006.meta_messages (tenant_id, lead_id, platform, sender_id, sender_name, message_text, direction, message_id, raw_payload)
SELECT 6, l.id, 'instagram', 'QA-IGSID-001', 'qa_ig_user_1', 'Yes, we are open 24/7 online', 'outbound',
       'qa-igmid.' || repeat('h', 24),
       jsonb_build_object('platform','instagram','test',TRUE)
FROM tenant_006.leads l WHERE l.lead_code='QA-LD-002';

INSERT INTO tenant_006.meta_messages (tenant_id, lead_id, platform, sender_id, sender_name, message_text, direction, message_id, raw_payload)
SELECT 6, l.id, 'instagram', 'QA-IGSID-003', 'qa_ig_user_3', 'Do you accept PayPal?', 'inbound',
       'qa-igmid.' || repeat('i', 26),
       jsonb_build_object('platform','instagram','test',TRUE)
FROM tenant_006.leads l WHERE l.lead_code='QA-LD-005';

-- ---------------------------------------------------------------------------
-- 11. settings (public.tenants.settings JSONB に QA デフォルトを書き込み)
--     - 個別の settings テーブルは無く、tenants.settings JSONB を使う
-- ---------------------------------------------------------------------------
UPDATE public.tenants
SET settings = jsonb_build_object(
    'qa_smoke_seed_version', 1,
    'qa_smoke_seed_at', NOW()::TEXT,
    'qa_smoke_locale', 'ja'
)
WHERE id = 6 AND tenant_code = 'tenant-review';

-- ---------------------------------------------------------------------------
-- 12. audit_logs: ADR-025 例外条件 #3 (manual_db_insert 記録)
-- ---------------------------------------------------------------------------
INSERT INTO tenant_006.audit_logs (tenant_id, user_id, action, table_name, record_id, new_data)
SELECT 6, s.id, 'manual_db_insert', 'tenant_meta_config', mc.id,
       jsonb_build_object(
           'reason', 'ADR-038 QA Smoke Suite seed',
           'adr', 'ADR-038',
           'actor', 'scripts/qa/seed-tenant.sql',
           'page_id', mc.page_id
       )
FROM tenant_006.tenant_meta_config mc
CROSS JOIN LATERAL (SELECT id FROM tenant_006.staff WHERE primary_email='qa-admin@salesanchor.jp' LIMIT 1) s
WHERE mc.tenant_id = 6;

-- ---------------------------------------------------------------------------
-- 13. 行数 assert (ADR-038 seed 表との突合せ)
-- ---------------------------------------------------------------------------
DO $assert_counts$
DECLARE
    n INTEGER;
BEGIN
    -- users
    SELECT COUNT(*) INTO n FROM public.users WHERE tenant_id = 6 AND email LIKE 'qa-%@salesanchor.jp';
    IF n <> 3 THEN RAISE EXCEPTION 'seed assert FAIL: users expected=3, got=%', n; END IF;

    -- companies
    SELECT COUNT(*) INTO n FROM tenant_006.companies WHERE company_code LIKE 'QA-CO-%';
    IF n <> 5 THEN RAISE EXCEPTION 'seed assert FAIL: companies expected=5, got=%', n; END IF;

    -- contacts
    SELECT COUNT(*) INTO n FROM tenant_006.contacts WHERE contact_code LIKE 'QA-CT-%';
    IF n <> 5 THEN RAISE EXCEPTION 'seed assert FAIL: contacts expected=5, got=%', n; END IF;

    -- leads
    SELECT COUNT(*) INTO n FROM tenant_006.leads WHERE lead_code LIKE 'QA-LD-%';
    IF n <> 5 THEN RAISE EXCEPTION 'seed assert FAIL: leads expected=5, got=%', n; END IF;

    -- orders
    SELECT COUNT(*) INTO n FROM tenant_006.orders WHERE order_number LIKE 'QA-OR-%';
    IF n <> 3 THEN RAISE EXCEPTION 'seed assert FAIL: orders expected=3, got=%', n; END IF;

    -- products
    SELECT COUNT(*) INTO n FROM tenant_006.products WHERE product_code LIKE 'QA-PR-%';
    IF n <> 5 THEN RAISE EXCEPTION 'seed assert FAIL: products expected=5, got=%', n; END IF;

    -- meta_messages
    SELECT COUNT(*) INTO n FROM tenant_006.meta_messages;
    IF n <> 10 THEN RAISE EXCEPTION 'seed assert FAIL: meta_messages expected=10, got=%', n; END IF;

    -- messenger 6 件
    SELECT COUNT(*) INTO n FROM tenant_006.meta_messages WHERE platform = 'messenger';
    IF n <> 6 THEN RAISE EXCEPTION 'seed assert FAIL: messenger expected=6, got=%', n; END IF;

    -- instagram 4 件
    SELECT COUNT(*) INTO n FROM tenant_006.meta_messages WHERE platform = 'instagram';
    IF n <> 4 THEN RAISE EXCEPTION 'seed assert FAIL: instagram expected=4, got=%', n; END IF;

    -- 100 文字超え message_id (ADR-026 / scene-04 用)
    SELECT COUNT(*) INTO n FROM tenant_006.meta_messages WHERE length(message_id) > 100;
    IF n < 1 THEN RAISE EXCEPTION 'seed assert FAIL: 100 文字超え message_id 行が必要 (ADR-026 / scene-04)'; END IF;

    -- tenant_meta_config 2 件
    SELECT COUNT(*) INTO n FROM tenant_006.tenant_meta_config WHERE tenant_id = 6 AND is_active = TRUE;
    IF n <> 2 THEN RAISE EXCEPTION 'seed assert FAIL: tenant_meta_config expected=2, got=%', n; END IF;

    -- public.meta_page_routing 2 件
    SELECT COUNT(*) INTO n FROM public.meta_page_routing WHERE tenant_id = 6 AND is_active = TRUE;
    IF n <> 2 THEN RAISE EXCEPTION 'seed assert FAIL: meta_page_routing expected=2, got=%', n; END IF;

    RAISE NOTICE 'seed row-count assert: ALL OK';
END
$assert_counts$;

COMMIT;
