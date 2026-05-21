-- ============================================================================
-- Migration 066: Sprint 5 (F5) 連動 hotfix
--                public.tenant_llm_budgets に通知 de-bounce 列 + Sprint 4 申し送り seed
--
-- 経緯:
--   Sprint 4 (PR #517) Reviewer 申し送り 2 件を本 Sprint 5 で同梱対応:
--     1. M1 通知連投抑止: notify_budget_exhausted が 1 メッセージごとに発火し、
--        Discord 通知が荒れる問題。`last_hard_stop_notified_at` 列を追加し、
--        サービス側で 1h de-bounce を実装する (服飾は backend/app/services/
--        discord_notifier.py 拡張)。
--     2. tenant_llm_budgets seed: tenant_004 / tenant_006 に行が無く、
--        check_budget が NO_BUDGET_ROW を返す → LLM フォールバック完全停止。
--        本 migration で 2 行 ON CONFLICT DO NOTHING を投入。
--
-- 設計:
--   - 列追加は `IF NOT EXISTS` で冪等
--   - seed は ON CONFLICT (tenant_id) DO NOTHING で既存値は壊さない
--   - tenant_004 (本番) は monthly_budget_usd = 5.00, hard_stop = true
--   - tenant_006 (撮影/QA) は monthly_budget_usd = 1.00, hard_stop = true
--
-- ADR-034 観点: public schema のため 1 回のみ実行。
--
-- 関連:
--   .claude-pipeline/spec.md F5 / F4
--   migrations/062_create_inventory_movements_and_budget.sql (元定義)
--   backend/app/services/discord_notifier.py (de-bounce 実装)
--   PR #517 (Sprint 4) Reviewer 申し送り
--
-- 作成日: 2026-05-22
-- ============================================================================

-- === 1. last_hard_stop_notified_at 列を追加 (1h de-bounce 用) ===
ALTER TABLE public.tenant_llm_budgets
    ADD COLUMN IF NOT EXISTS last_hard_stop_notified_at TIMESTAMPTZ;

COMMENT ON COLUMN public.tenant_llm_budgets.last_hard_stop_notified_at IS
    'Sprint 5 (F5) 同梱: notify_budget_exhausted の 1h de-bounce 用タイムスタンプ。NULL = 未通知、NOW() - 1h より前 = 再通知 OK。';

-- === 2. tenant_004 / tenant_006 seed (Sprint 4 申し送り対応) ===
-- Sprint 4 Reviewer 指摘: 行が無いため check_budget が NO_BUDGET_ROW を返し、
-- LLM フォールバックが完全に呼ばれない。実運用に必要な行を冪等投入する。
--
-- 注意: ON CONFLICT DO NOTHING のため、既存値（手動で別予算を設定済の場合等）
-- は上書きしない。新規テナントのみ初期値を投入する。
INSERT INTO public.tenant_llm_budgets
    (tenant_id, monthly_budget_usd, current_month_usd,
     last_reset_at, hard_stop, notify_admin)
VALUES
    (4, 5.00, 0, NOW(), TRUE, TRUE),
    (6, 1.00, 0, NOW(), TRUE, TRUE)
ON CONFLICT (tenant_id) DO NOTHING;

-- ============================================================================
-- Rollback:
--   ALTER TABLE public.tenant_llm_budgets DROP COLUMN IF EXISTS last_hard_stop_notified_at;
--   -- seed の DELETE は実運用が始まっている可能性があり、慎重判断。手動推奨:
--   --   DELETE FROM public.tenant_llm_budgets WHERE tenant_id IN (4, 6) AND current_month_usd = 0;
-- ============================================================================
