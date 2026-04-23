-- ============================================================================
-- !! 警告 !! 警告 !! 警告 !!
--
-- このSQLファイルは **テンプレート** です。`{schema}`, `{schema_raw}`,
-- `{tenant_id}` のプレースホルダを含むため、そのまま psql 等で実行すると
-- シンタックスエラーになります。
--
-- 必ず scripts/migrate_phase1_redesign.py 経由で実行してください。
--
-- ============================================================================
--
-- Phase 1 再設計 / Migration 023: システム管理者ロールの is_system フラグ修正
--
-- 背景:
--   Migration 021 の INSERT ... ON CONFLICT (tenant_id, name) DO NOTHING は、
--   既にテナント内に「システム管理者」という名前のロールが存在する場合、
--   新しい値（is_system=TRUE）を無視して旧値を保持する。
--   本番 VPS の tenant_001 / tenant_003 / tenant_004 / tenant_005 のうち、
--   一部で「システム管理者」が is_system=FALSE のまま残っていた。
--
-- 修正内容:
--   全テナントの {schema}.roles で、システム管理者 / オーナー の is_system を
--   TRUE に UPDATE する（設計書の想定通り）。
--   旧値が既に TRUE なら UPDATE は no-op（冪等）。
--
-- 変更履歴:
--   2026-04-23: 初版作成（Phase 1 再設計 軽微課題）

UPDATE {schema}.roles
SET is_system = TRUE, updated_at = NOW()
WHERE tenant_id = {tenant_id}
  AND name IN ('オーナー', 'システム管理者')
  AND is_system = FALSE;
