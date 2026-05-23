-- Migration 073: LeadStatus 整理 — 受信箱タブを商談進捗ベースに変更
--
-- 変更内容:
--   1. '案件化' → '商談中' にリネーム（商談開始後のリードを明示）
--   2. 廃止値を近隣ステータスへ移行:
--        AI対応中 / コンタクト中 / 提案中 → 新規（アサイン前リードに集約）
--        保留 → 追客（短期）（近隣の追客ステータスに移行）
--
-- 影響テーブル: {schema}.leads
-- 適用対象: 全テナント
-- 不可逆: 値の変更（ロールバック用 DDL は backup から復元）

BEGIN;

UPDATE {schema}.leads
SET    status = '商談中', updated_at = NOW()
WHERE  status = '案件化';

UPDATE {schema}.leads
SET    status = '新規', updated_at = NOW()
WHERE  status IN ('AI対応中', 'コンタクト中', '提案中');

UPDATE {schema}.leads
SET    status = '追客（短期）', updated_at = NOW()
WHERE  status = '保留';

COMMIT;
