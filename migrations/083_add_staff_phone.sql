-- ============================================================================
-- Migration 083: staff テーブルに phone カラム追加
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
--   DO block で pg_namespace 走査して全 tenant_NNN schema に適用。
--   ADD COLUMN IF NOT EXISTS / CREATE INDEX IF NOT EXISTS で再実行可能。
--
-- 変更履歴:
--   2026-05-27: 初版
--   2026-05-31: テンプレート形式から pg_namespace 走査形式へ変更（deploy.yml 対応）
-- ============================================================================

DO $$
DECLARE
    schema_rec RECORD;
BEGIN
    FOR schema_rec IN
        SELECT nspname FROM pg_namespace
        WHERE nspname ~ '^tenant_\d+$'
        ORDER BY nspname
    LOOP
        -- staff テーブルが存在するスキーマのみ対象
        IF NOT EXISTS (
            SELECT 1 FROM pg_tables
            WHERE schemaname = schema_rec.nspname AND tablename = 'staff'
        ) THEN
            CONTINUE;
        END IF;

        -- phone カラム追加（冪等: IF NOT EXISTS）
        EXECUTE format(
            'ALTER TABLE %I.staff ADD COLUMN IF NOT EXISTS phone VARCHAR(20)',
            schema_rec.nspname
        );

        -- インデックス作成（冪等: IF NOT EXISTS）
        EXECUTE format(
            'CREATE INDEX IF NOT EXISTS idx_staff_phone ON %I.staff (phone) WHERE phone IS NOT NULL',
            schema_rec.nspname
        );

        -- カラムコメント
        EXECUTE format(
            $q$COMMENT ON COLUMN %I.staff.phone IS 'スタッフ個人の電話番号（アカウント設定画面で本人が登録）'$q$,
            schema_rec.nspname
        );
    END LOOP;
END;
$$;
