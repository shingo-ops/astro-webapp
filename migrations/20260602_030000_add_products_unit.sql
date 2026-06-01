-- ADR-090 PR5b: 在庫表(public.products)に取引単位(unit)列を追加
-- 単位は商品マスタ属性として保持し、在庫表に「単位」列として表示する。
-- 値の充足は Discord 取込(PR5c)で行う。本 migration は additive かつ冪等。
-- 想定値: piece / pack / box / case / set（public.inventory.unit と同系統。CHECK は付けず柔軟に保持）

ALTER TABLE public.products ADD COLUMN IF NOT EXISTS unit VARCHAR(20);
