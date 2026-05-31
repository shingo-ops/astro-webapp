-- migration 089: condition フィールド値の正規化と CHECK 制約追加
--
-- 背景: public.inventory.condition は自由文字列だった。
--       UI / LLM / ルールベースパーサが 'new' / 'used_a' / 'sealed' / 'opened'
--       / 'shrink' / 'no_shrink' などを個別に使っており、統一定義がなかった。
--
-- 正規値を以下 16 値に確定し強制する:
--   shrink / no_shrink / sealed / damage /
--   unsearched / searched / graded /
--   grade_s / grade_a / grade_b / grade_c / grade_d /
--   junk / bulk / normal / unknown
--
-- 手順:
--   1. 旧値を正規値に UPDATE（additive-only 原則維持）
--   2. CHECK 制約を追加
--
-- 注意: 本番適用前に件数を確認すること（PO 承認済み）

-- Step 1: 旧 UI 値 → 正規値へ変換
-- 'new' (新品) → 'sealed' (未開封が最も近い意味)
UPDATE public.inventory SET condition = 'sealed'   WHERE condition = 'new';

-- 'used' (使用済み汎用) → 'normal'
UPDATE public.inventory SET condition = 'normal'   WHERE condition = 'used';

-- 'used_a' (中古 A) → 'grade_a'
UPDATE public.inventory SET condition = 'grade_a'  WHERE condition = 'used_a';

-- 'opened' (開封済み) → 'no_shrink' (シュリンクなし)
UPDATE public.inventory SET condition = 'no_shrink' WHERE condition = 'opened';

-- 'shrink' / 'no_shrink' / 'sealed' は正規値と一致するため変換不要

-- Step 2: CHECK 制約追加（NULL は許容）
ALTER TABLE public.inventory
    ADD CONSTRAINT inventory_condition_check
    CHECK (
        condition IN (
            'shrink', 'no_shrink', 'sealed', 'damage',
            'unsearched', 'searched',
            'graded', 'grade_s', 'grade_a', 'grade_b', 'grade_c', 'grade_d',
            'junk', 'bulk', 'normal', 'unknown'
        )
        OR condition IS NULL
    );
