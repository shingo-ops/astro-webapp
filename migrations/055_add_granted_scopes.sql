-- ============================================================================
-- !! テンプレート。scripts/migrate_adr041_granted_scopes.py 経由で
-- !! 全テナントスキーマに展開する（migration 040 と同じ運用）。
-- ============================================================================
-- ADR-041 / Migration 055: tenant_meta_config.granted_scopes 列追加
--
-- 目的:
--   ADR-041 で OAuth スコープを 6 → 7 permission に拡張（`business_management` 追加）。
--   既存テナント（旧 6 permission で接続済み）に再認証を促すため、
--   現在の接続が「どの permission を持っているか」を per-row で記録する。
--
-- 設計:
--   - `granted_scopes` は JSONB 配列（例: ["pages_show_list", ..., "business_management"]）
--   - 既存全行は backfill で **旧 6 permission** を入れる（再認証前の状態を表す）
--   - 再 OAuth 成功時に新スコープ（7 permission）に上書きする
--   - 再認証要否は backend で `'business_management' = ANY(granted_scopes)` を判定
--
-- 後方互換維持の終了条件（ADR-041 §4）:
--   全テナント再接続完了 OR ADR 適用後 90 日経過、のいずれか早い方まで。
--
-- 冪等性:
--   ADD COLUMN IF NOT EXISTS + UPDATE WHERE granted_scopes IS NULL で再実行可能。
--
-- 変更履歴:
--   2026-05-18: ADR-041 初版

ALTER TABLE {schema}.tenant_meta_config
    ADD COLUMN IF NOT EXISTS granted_scopes JSONB;

-- 既存接続済み行を旧 6 permission で backfill（再認証前の状態）
UPDATE {schema}.tenant_meta_config
    SET granted_scopes = '["pages_show_list","pages_manage_metadata","pages_messaging","pages_read_engagement","instagram_basic","instagram_manage_messages"]'::jsonb
    WHERE granted_scopes IS NULL;

COMMENT ON COLUMN {schema}.tenant_meta_config.granted_scopes IS
    'OAuth granted scopes JSONB array (ADR-041). business_management 不在の行は再認証対象。';
