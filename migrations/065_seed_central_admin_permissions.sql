-- ============================================================================
-- Migration 065: 中央 admin 用 (central.*) 権限の seed
--
-- 経緯:
--   spec.md v1.1 F2 (Sprint 2):
--     - マーケットプレイス型の中央 admin（is_super_admin=true）が
--       /super-admin/masters 配下で操作する権限キーを public.permissions に
--       追加する
--     - 注意: これらは require_permission() でも使えるが、本 Sprint では
--       require_super_admin (= public.users.is_super_admin=true 判定) を
--       第一ガードとして使う。permissions seed は将来の細分化 / audit 用。
--
-- 設計:
--   - 中央 (super-admin only):
--     - central.knowledge.edit           (public.knowledge_rules CRUD)
--     - central.aliases.edit             (public.supplier_aliases CRUD)
--     - central.tcg.edit                 (public.tcg_series_master CRUD)
--     - central.dex.edit                 (public.pokemon_dex / trainer_dex CRUD)
--     - central.supplier.edit            (public.suppliers CRUD)
--     - central.supplier_discord_routing.edit (public.supplier_discord_routing CRUD)
--
--   - テナント admin 側 (tenant.inventory_visibility.edit) は既に 063 で seed 済。
--
-- ADR-034 観点:
--   public.permissions への INSERT は 1 回のみ実行。
--
-- 冪等性:
--   ON CONFLICT (key) DO NOTHING で再投入安全。
--
-- 関連:
--   .claude-pipeline/spec.md F2 / AC2.1 〜 AC2.7
--   migrations/002_add_permissions_master.sql (本体)
--   migrations/063_tenant_rbac_extensions.sql (tenant.inventory_visibility.edit)
--
-- 作成日: 2026-05-21
-- ============================================================================

INSERT INTO public.permissions (key, resource, action, description, category) VALUES
    ('central.knowledge.edit',
        'central_knowledge', 'edit',
        '正規化辞書（public.knowledge_rules）の CRUD（Jarvis 運用 admin 専用）',
        '中央マスタ'),
    ('central.aliases.edit',
        'central_aliases', 'edit',
        '仕入元 alias（public.supplier_aliases）の CRUD（Jarvis 運用 admin 専用）',
        '中央マスタ'),
    ('central.tcg.edit',
        'central_tcg', 'edit',
        'TCG シリーズマスタ（public.tcg_series_master）の CRUD（Jarvis 運用 admin 専用）',
        '中央マスタ'),
    ('central.dex.edit',
        'central_dex', 'edit',
        'ポケモン / トレーナー図鑑（public.pokemon_dex / trainer_dex）の CRUD（Jarvis 運用 admin 専用）',
        '中央マスタ'),
    ('central.supplier.edit',
        'central_supplier', 'edit',
        '仕入元マスタ（public.suppliers）の CRUD（Jarvis 運用 admin 専用）',
        '中央マスタ'),
    ('central.supplier_discord_routing.edit',
        'central_supplier_discord_routing', 'edit',
        '仕入元 × Discord routing（public.supplier_discord_routing）の CRUD（Jarvis 運用 admin 専用）',
        '中央マスタ')
ON CONFLICT (key) DO NOTHING;

-- ============================================================================
-- Rollback（緊急時のみ手動実行）:
--   DELETE FROM public.permissions WHERE key IN (
--       'central.knowledge.edit', 'central.aliases.edit',
--       'central.tcg.edit', 'central.dex.edit',
--       'central.supplier.edit', 'central.supplier_discord_routing.edit'
--   );
-- ============================================================================
