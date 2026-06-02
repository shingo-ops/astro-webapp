-- ADR-090 PR5c フォローアップ: 既存 public.products の unit / condition を
-- 受信通知の解析結果(parse_result_json)から名前一致で backfill する。
--
-- 背景: PR5b で unit 列、PR5c で取込時の unit/condition 転記を追加したが、
--       既に登録済みの商品（取込 apply の NOT EXISTS でスキップされる）には
--       単位・状態が入らないため、在庫表で「-」表示のままになる。
--       解析結果から名前一致するぶんを後追いで埋める。
--
-- 正規化は取込 apply と同一:
--   - unit: 小文字化 + carton→case、空文字は NULL（最頻値 mode を採用）
--   - condition: 小文字化、空文字は NULL（最頻値 mode）
-- 冪等性: unit / condition が NULL の行のみ更新（COALESCE で既存値は保持）。
--         再実行しても結果は変わらない。新規環境(解析結果なし)では 0 行更新。

WITH parsed AS (
    SELECT TRIM(it->>'product_name') AS pname,
           CASE WHEN LOWER(TRIM(it->>'unit')) = 'carton' THEN 'case'
                ELSE NULLIF(LOWER(TRIM(it->>'unit')), '') END AS u,
           NULLIF(LOWER(TRIM(it->>'condition')), '') AS c
    FROM public.discord_inbound_messages m,
         jsonb_array_elements(COALESCE(m.parse_result_json->'items', '[]'::jsonb)) it
    WHERE COALESCE(TRIM(it->>'product_name'), '') <> ''
),
rep AS (
    SELECT pname,
           mode() WITHIN GROUP (ORDER BY u) FILTER (WHERE u IS NOT NULL) AS u,
           mode() WITHIN GROUP (ORDER BY c) FILTER (WHERE c IS NOT NULL) AS c
    FROM parsed
    GROUP BY pname
)
UPDATE public.products p
SET unit = COALESCE(p.unit, rep.u),
    condition = COALESCE(p.condition, rep.c)
FROM rep
WHERE rep.pname = p.name
  AND ((p.unit IS NULL AND rep.u IS NOT NULL)
       OR (p.condition IS NULL AND rep.c IS NOT NULL));
