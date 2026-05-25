-- ============================================================================
-- !! 警告 !! 警告 !! 警告 !!
--
-- このSQLファイルは **テンプレート** です。`{schema}`, `{schema_raw}`,
-- `{tenant_id}` のプレースホルダを含むため、そのまま psql 等で実行すると
-- シンタックスエラーになります。
--
-- 必ず scripts/migrate_phase1_redesign.py 経由で実行してください。
--
-- ============================================================================
--
-- Phase 1 再設計 / Migration 021: 新7役割 seed + メニュー権限マトリクス seed
--
-- 内容:
--   [1] 既存 {schema}.roles に新6役割を追加（オーナーは migrate_phase1.py で既存）
--       - システム管理者 / リーダー / 営業 / CS / 仕入れ担当 / 発送担当
--   [2] 各役割のメニュー権限 (menu.*) を role_permissions に INSERT
--       設計書の期待値に準拠（オーナー19/19、システム管理者19/19、リーダー16/19、
--       営業11/19、CS 6/19）
--
-- 未確定（2026-04-23 時点）:
--   - 仕入れ担当 / 発送担当 の権限マトリクスは設計書に未定義
--   - 本 migration では両役割の INSERT は**行わない**（role_permissions 行なし=全権限なし）
--   - 後日しんごさん確認後、別 migration または seeds スクリプトで追加する
--
-- 前提:
--   - 018 で public.permissions に menu.* 19件が seed 済
--   - 019 で {schema}.staff 作成済（本 migration では不要だが依存順序の参考）
--
-- 設計書参照:
--   - salesanchor_staff_roles_bots_design.docx §3-2, §3-4
--   - salesanchor_system_overview.docx 第3章 3-2 HIGH LIFE JPN 用7役割
--   - migrate_staff_roles_bots_PATCH.md §4-4
--
-- 変更履歴:
--   2026-04-23: 初版作成（Phase 1 再設計）

-- === [1] 新6役割を {schema}.roles に追加 ===
-- オーナーは migrate_phase1.py の seed_system_roles() で既に存在するためスキップ

INSERT INTO {schema}.roles (tenant_id, name, color, priority, is_system, description) VALUES
    ({tenant_id}, 'システム管理者', '#9b59b6', 900, TRUE,  '技術管理者。全権限を持つ'),
    ({tenant_id}, 'リーダー',        '#2ecc71', 700, FALSE, '営業リーダー'),
    ({tenant_id}, '営業',            '#3498db', 500, FALSE, '一般営業'),
    ({tenant_id}, 'CS',              '#f39c12', 400, FALSE, 'カスタマーサポート'),
    ({tenant_id}, '仕入れ担当',      '#e67e22', 450, FALSE, '仕入れ発注を担当'),
    ({tenant_id}, '発送担当',        '#16a085', 350, FALSE, '発送業務を担当')
ON CONFLICT (tenant_id, name) DO NOTHING;

-- === [2] 役割 × メニュー権限マトリクス ===
-- {schema}.role_permissions は migration 003 で定義済み：
--   id SERIAL PK, role_id FK, permission_id FK (UNIQUE(role_id, permission_id))
-- 既存 role_permissions には CRUD 粒度の権限がオーナー/メンバー用に入っているが、
-- 本 migration ではそれに重ねて menu.* 19件を役割別に INSERT する。
--
-- 設計書の期待値:
--   オーナー        : 19 / 19 全 TRUE
--   システム管理者  : 19 / 19 全 TRUE
--   リーダー        : 16 / 19（staff_management, role_management, data_management のみ FALSE）
--   営業            : 11 / 19（chat 6 + sales 5 = 11）
--   CS              :  6 / 19（chat 6 のみ）

-- --- オーナー: 全 19 menu 権限を付与 ---
INSERT INTO {schema}.role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM {schema}.roles r
CROSS JOIN public.permissions p
WHERE r.tenant_id = {tenant_id}
  AND r.name = 'オーナー'
  AND p.permission_group IS NOT NULL
ON CONFLICT (role_id, permission_id) DO NOTHING;

-- --- システム管理者: 全 19 menu 権限を付与 ---
INSERT INTO {schema}.role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM {schema}.roles r
CROSS JOIN public.permissions p
WHERE r.tenant_id = {tenant_id}
  AND r.name = 'システム管理者'
  AND p.permission_group IS NOT NULL
ON CONFLICT (role_id, permission_id) DO NOTHING;

-- --- リーダー: 16/19（admin 配下の staff_management / role_management / data_management のみ除外） ---
INSERT INTO {schema}.role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM {schema}.roles r
CROSS JOIN public.permissions p
WHERE r.tenant_id = {tenant_id}
  AND r.name = 'リーダー'
  AND p.permission_group IS NOT NULL
  AND p.key NOT IN ('menu.staff_management', 'menu.role_management', 'menu.data_management')
ON CONFLICT (role_id, permission_id) DO NOTHING;

-- --- 営業: 11/19（chat 6 + sales 5） ---
INSERT INTO {schema}.role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM {schema}.roles r
CROSS JOIN public.permissions p
WHERE r.tenant_id = {tenant_id}
  AND r.name = '営業'
  AND p.permission_group IN ('chat', 'sales')
ON CONFLICT (role_id, permission_id) DO NOTHING;

-- --- CS: 6/19（chat 6 のみ） ---
INSERT INTO {schema}.role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM {schema}.roles r
CROSS JOIN public.permissions p
WHERE r.tenant_id = {tenant_id}
  AND r.name = 'CS'
  AND p.permission_group = 'chat'
ON CONFLICT (role_id, permission_id) DO NOTHING;

-- --- 仕入れ担当 / 発送担当: 権限マトリクス未定義（設計書で TBD）---
-- TODO: しんごさん確認後、別 migration または seeds スクリプトで付与すること。
--       暫定ではレコードなし = 全メニュー権限なし扱い。
