-- ADR-033: users テーブルに theme カラムを追加
-- ユーザー個人単位のテーマ設定（'light' / 'dark'）
-- ADD COLUMN IF NOT EXISTS で idempotent
ALTER TABLE public.users
    ADD COLUMN IF NOT EXISTS theme VARCHAR(10) NOT NULL DEFAULT 'light';

-- 既存ユーザーは全員 'light' に設定（DEFAULT 'light' で自動設定済）

-- 撮影用テナントの review@salesanchor.jp は 'light' に明示設定（OS設定に依存しないクリーンな撮影環境）
UPDATE public.users
    SET theme = 'light'
    WHERE email = 'review@salesanchor.jp';
