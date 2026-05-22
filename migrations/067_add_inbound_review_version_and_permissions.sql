-- ============================================================================
-- Migration 067: discord_inbound_messages 楽観ロック (version) 列 +
--                central.parse_review.* 権限 seed
--
-- 経緯:
--   spec.md v1.1 F6 (Sprint 6) AC6.5:
--     - 同一 inbound を別 admin が同時に承認しようとすると後勝ち禁止
--       → 楽観ロックで 409 Conflict 返却
--   spec.md v1.1 F6 / 権限:
--     - central.parse_review.approve / central.parse_review.reject を seed
--       （require_super_admin 第一ガード + permissions 細分化準備、Sprint 9+
--         で role × permission 細分化検討。本 Sprint では seed のみで使用は
--         super_admin 全権）
--
-- 設計:
--   - public.discord_inbound_messages.version INTEGER NOT NULL DEFAULT 0
--     既存行は DEFAULT 0 で埋まる。承認 / reject 時に UPDATE ... WHERE
--     version = :expected で楽観ロック (mismatch → 0 行更新 → 409)
--   - 列名は `version` を選択（`updated_at` ベース楽観ロックは ms 解像度依存
--     で flaky、`rev` / `etag` より直観的）
--
-- ADR-034 観点: public schema のため 1 回のみ実行。
--
-- 冪等性:
--   - ADD COLUMN IF NOT EXISTS / INSERT ON CONFLICT DO NOTHING
--
-- 関連:
--   .claude-pipeline/spec.md F6 / AC6.5 / AC6.8
--   migrations/059_create_discord_inbound_messages.sql (本体)
--   migrations/065_seed_central_admin_permissions.sql (中央 admin 権限 seed の先行)
--
-- 作成日: 2026-05-22
-- ============================================================================

-- === 1. version 列追加（楽観ロック）===
ALTER TABLE public.discord_inbound_messages
    ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 0;

COMMENT ON COLUMN public.discord_inbound_messages.version IS
    'spec F6 AC6.5: approve/reject 時の楽観ロック用カウンタ（後勝ち禁止）';

-- === 2. central.parse_review.* 権限 seed ===
INSERT INTO public.permissions (key, resource, action, description, category) VALUES
    ('central.parse_review.approve',
        'central_parse_review', 'approve',
        'Discord 受信メッセージ解析結果の承認（inventory_movements へ反映、Jarvis 運用 admin 専用）',
        '中央マスタ'),
    ('central.parse_review.reject',
        'central_parse_review', 'reject',
        'Discord 受信メッセージ解析結果の差戻し（exclude_reason 必須、Jarvis 運用 admin 専用）',
        '中央マスタ')
ON CONFLICT (key) DO NOTHING;

-- ============================================================================
-- Rollback:
--   DELETE FROM public.permissions WHERE key IN (
--       'central.parse_review.approve', 'central.parse_review.reject'
--   );
--   ALTER TABLE public.discord_inbound_messages DROP COLUMN IF EXISTS version;
-- ============================================================================
