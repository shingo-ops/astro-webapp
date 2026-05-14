-- ADR-027 ロールバック: locale カラムを削除
ALTER TABLE public.users
    DROP COLUMN IF EXISTS locale;
