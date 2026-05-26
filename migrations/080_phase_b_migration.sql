-- ============================================================================
-- Migration 080: spec.md v1.3 Phase B 即時移行
--
-- spec.md v1.3 (2026-05-26):
--   Phase A 長期方針を撤回、Phase B 即時移行に方針転換。
--   既存テナント (`public.tenant_settings.spreadsheet_phase = 'A'`) を 'B' に
--   一括更新し、新規テナントのデフォルトも 'B' に変更する。
--
-- 経緯:
--   migration 070 (2026-05-22 spec v1.2) で `spreadsheet_phase` 列を default 'A' で
--   導入したが、v1.3 で「テストデータ投入 + CRM 正本化」方針に転換したため、
--   既存 'A' レコードを 'B' に進める。
--
-- 変更内容:
--   1. ALTER COLUMN ... DROP DEFAULT → SET DEFAULT 'B'
--   2. UPDATE public.tenant_settings SET spreadsheet_phase = 'B' WHERE spreadsheet_phase = 'A'
--   3. CHECK 制約 ('A','B','C') はそのまま (A 状態への手動切戻しは引き続き許可、
--      ただし運用上は B が標準)
--
-- 影響テーブル: public.tenant_settings
-- 適用対象: public スキーマ（テナント横断 1 回のみ実行）
-- 不可逆: UPDATE は WHERE 条件付きで冪等、再走しても 'B' → 'B' で副作用なし
--
-- 冪等チェック: UPDATE は WHERE 句で 'A' のみ対象、DEFAULT 変更も再走可
--
-- 関連:
--   migrations/070_add_spreadsheet_phase.sql (default 'A' 起源)
--   docs/specs/inventory-management/spec.md v1.3
--   backend/app/services/phase_gate.py
-- ============================================================================

-- 1. DEFAULT を 'A' → 'B' に変更
ALTER TABLE public.tenant_settings
  ALTER COLUMN spreadsheet_phase SET DEFAULT 'B';

-- 2. 既存 'A' レコードを 'B' に migrate
UPDATE public.tenant_settings
  SET spreadsheet_phase = 'B',
      updated_at = NOW()
WHERE spreadsheet_phase = 'A';
