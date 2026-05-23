-- Migration 074: english_name カラムを nickname にリネーム
--
-- 変更内容:
--   leads テーブルの english_name（英語名）を nickname（呼び名）に改名。
--   ADR-015 の定義では「呼び名」が意味的に正しく、"english_name" は誤った名称だった。
--
-- 影響テーブル: {schema}.leads
-- 適用対象: 全テナント
-- 不可逆: カラムリネーム（ロールバックは RENAME COLUMN nickname TO english_name で可）

ALTER TABLE {schema}.leads RENAME COLUMN english_name TO nickname;
