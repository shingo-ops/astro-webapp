-- migration 088: unit フィールド値の正規化と CHECK 制約追加
--
-- 背景: migration 084 で追加した public.inventory.unit (VARCHAR(20)) は
--       制約なしの自由文字列だった。正規値を以下5つに確定し強制する:
--         piece / pack / box / case / set
--
-- 手順:
--   1. 既存の汚染データを正規値に UPDATE（additive-only 原則維持）
--   2. CHECK 制約を追加
--
-- 注意: 本番適用前に件数を確認すること（PO 承認済み）

-- Step 1: 旧パーサ内部値 "carton" → "case"
UPDATE public.inventory
SET unit = 'case'
WHERE unit = 'carton';

-- Step 2: フロントエンド UI 旧値（大文字）→ 正規小文字値
UPDATE public.inventory SET unit = 'piece' WHERE unit IN ('Peace', 'peace', 'Piece');
UPDATE public.inventory SET unit = 'pack'  WHERE unit = 'Pack';
UPDATE public.inventory SET unit = 'box'   WHERE unit = 'Box';
UPDATE public.inventory SET unit = 'case'  WHERE unit IN ('Case', 'Carton', 'carton');
UPDATE public.inventory SET unit = 'set'   WHERE unit = 'Set';

-- Step 3: CHECK 制約追加（NULL は許容）
ALTER TABLE public.inventory
    ADD CONSTRAINT inventory_unit_check
    CHECK (unit IN ('piece', 'pack', 'box', 'case', 'set') OR unit IS NULL);
