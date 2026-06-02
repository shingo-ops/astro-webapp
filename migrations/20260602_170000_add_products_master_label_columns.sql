-- ============================================================================
-- Migration 20260602_170000: ADR-093 PR1 — public.products に
--   発送ラベル / 検索 / 分類 用の 7 列を additive 追加
--
-- 在庫表 / 商品マスタ再設計 (ADR-093 Phase 1)。
-- 「商品マスタ.csv」相当の項目のうち public.products に未実装の列を追加し、
-- 管理者が商品マスタ管理画面で全項目を編集できるようにする。
--
-- 追加列:
--   - volume_weight           NUMERIC(8,3)  -- 容積重量 (VOLUME WEIGHT)
--   - search_keywords         TEXT          -- 検索キーワード (横断検索 / 名寄せ)
--   - exclude_keywords        TEXT          -- 除外キーワード (誤名寄せ防止 / GAS Exclude Keywords 移植先)
--   - related_series          VARCHAR(255)  -- 関連シリーズ
--   - category_classification VARCHAR(100)  -- カテゴリ分類
--   - required_output_value   VARCHAR(255)  -- 発送ラベル用の必須出力値 (HSコード検索等)
--   - item                    VARCHAR(255)  -- 品目 (発送ラベル / 通関用)
--
-- 既に DB に在る Box 属性列 (boxes_per_case / packs_per_box / box_weight_kg /
-- case_weight_kg / moq / hs_code / material, migration 082) は本 PR で API/UI に
-- 露出するのみで、列追加は不要。
--
-- 適用対象: public スキーマ (1 回のみ)
-- 冪等: ADD COLUMN IF NOT EXISTS で再走可。全列 NULL 許可のためゼロダウンタイム。
-- additive-only (backend/CLAUDE.md): 列追加のみ。削除・型変更なし。
-- ============================================================================

ALTER TABLE public.products
    ADD COLUMN IF NOT EXISTS volume_weight           NUMERIC(8, 3),
    ADD COLUMN IF NOT EXISTS search_keywords         TEXT,
    ADD COLUMN IF NOT EXISTS exclude_keywords        TEXT,
    ADD COLUMN IF NOT EXISTS related_series          VARCHAR(255),
    ADD COLUMN IF NOT EXISTS category_classification VARCHAR(100),
    ADD COLUMN IF NOT EXISTS required_output_value   VARCHAR(255),
    ADD COLUMN IF NOT EXISTS item                    VARCHAR(255);
