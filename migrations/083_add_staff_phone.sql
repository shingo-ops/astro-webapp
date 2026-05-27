-- ============================================================================
-- !! テンプレート。{schema} プレースホルダが含まれるため psql では直接実行不可 !!
-- 全テナントへの適用経路を PR body に記載すること（backend/CLAUDE.md 参照）
-- ============================================================================
--
-- Migration 083: {schema}.staff に phone カラム追加
--
-- 目的:
--   アカウント設定画面でスタッフが自身の電話番号を登録・更新できるようにする。
--   PATCH /api/v1/staff/me/profile エンドポイント経由で更新。
--
-- 設計判断:
--   - public.users ではなく {schema}.staff に追加（プロフィール情報はテナント固有）
--   - VARCHAR(20): 国番号付き最大 15 桁 + ハイフン等の区切り文字を考慮
--   - NULLABLE: 既存スタッフへの backfill 不要
--   - インデックス: phone での検索・フィルタを将来対応するために作成
--
-- 冪等性:
--   ADD COLUMN IF NOT EXISTS / CREATE INDEX IF NOT EXISTS で再実行可能
--
-- 変更履歴:
--   2026-05-27: 初版
-- ============================================================================

ALTER TABLE {schema}.staff
    ADD COLUMN IF NOT EXISTS phone VARCHAR(20);

CREATE INDEX IF NOT EXISTS idx_staff_phone
    ON {schema}.staff (phone) WHERE phone IS NOT NULL;

COMMENT ON COLUMN {schema}.staff.phone IS
    'スタッフ個人の電話番号（アカウント設定画面で本人が登録）';
