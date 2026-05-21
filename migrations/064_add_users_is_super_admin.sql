-- ============================================================================
-- Migration 064: public.users に is_super_admin 列を追加
--
-- 経緯:
--   spec.md v1.1 F2 (Sprint 2):
--     - マーケットプレイス型に伴い「Jarvis 運用 admin（中央 admin）」と
--       「各テナント admin」を権限的に分離する必要がある
--     - 中央 admin 専用のマスタ編集 UI (/super-admin/masters) はテナント
--       admin（role='admin'）でもアクセス不可、`is_super_admin = true` の
--       公開 SaaS 運用者のみアクセス可能
--
-- 設計:
--   - is_super_admin BOOLEAN NOT NULL DEFAULT FALSE
--   - 既存ユーザーは全員 FALSE（明示的に admin が後から ENV / 手動 SQL で
--     true に切り替える運用、安全側 default）
--   - tenant.role='admin' とは独立の概念（テナント admin は数十名、
--     super_admin は 1〜2 名想定）
--
-- ADR-034 観点:
--   public.users への列追加は **1 回のみ実行**（テナントループの中ではない）。
--
-- 冪等性:
--   ADD COLUMN IF NOT EXISTS で再投入安全。
--
-- 関連:
--   .claude-pipeline/spec.md F2 / AC2.1 / AC2.7
--   backend/app/auth/dependencies.py (require_super_admin を新設、Sprint 2)
--
-- 作成日: 2026-05-21
-- ============================================================================

ALTER TABLE public.users
    ADD COLUMN IF NOT EXISTS is_super_admin BOOLEAN NOT NULL DEFAULT FALSE;

-- 索引（GIN は過剰、is_super_admin = TRUE は少数のため部分インデックスで十分）
CREATE INDEX IF NOT EXISTS idx_users_super_admin_partial
    ON public.users (id) WHERE is_super_admin = TRUE;

COMMENT ON COLUMN public.users.is_super_admin IS
    'Jarvis 運用 admin（マーケットプレイス中央 admin）フラグ。'
    'true のユーザーのみ /super-admin/masters 配下の中央マスタ編集にアクセス可能。'
    'テナント admin (users.role=''admin'') とは独立、本フラグは小数（運用者のみ）。';

-- ============================================================================
-- 初期 super_admin の付与
--
-- 運用上、初期 super_admin は以下 2 名想定（spec の登場人物より）:
--   - shingo@treasureislandjp.com (しんごさん、リポ/Claudeアカウント owner)
--   - その他 Jarvis 運用 admin (ひとしさん相当、メールは VPS 側で確定後設定)
--
-- 安全側でハードコードはせず、特定の email にだけ flag を立てる
-- （存在しないユーザーは no-op）。
-- ============================================================================
UPDATE public.users
    SET is_super_admin = TRUE
    WHERE email IN (
        'shingo@treasureislandjp.com'
        -- 注: ひとしさん相当の email は別途手動 SQL で追加（spec.md Notes 参照）
    );

-- ============================================================================
-- Rollback（緊急時のみ手動実行）:
--   DROP INDEX IF EXISTS idx_users_super_admin_partial;
--   ALTER TABLE public.users DROP COLUMN IF EXISTS is_super_admin;
-- ============================================================================
