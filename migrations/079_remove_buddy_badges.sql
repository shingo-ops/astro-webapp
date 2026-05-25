-- バディ・バッジ機能の完全削除
-- 変更履歴: 2026-05-25 初版

-- 1. パーミッション削除（public スキーマ）
DELETE FROM public.permissions WHERE resource IN ('buddy', 'badges');

-- 2. 孤立したメニューパーミッション削除（migration 018 由来）
DELETE FROM public.permissions WHERE key IN ('menu.product_knowledge', 'menu.translation_prompt');

-- ※ テナントスキーマの buddy_pairs / buddy_feedbacks / badge_definitions / user_badges
--   テーブルおよび staff_ui_preferences.show_buddy_menu カラムは
--   scripts/migrate_079_remove_buddy_badges.py で全テナントに適用する。
