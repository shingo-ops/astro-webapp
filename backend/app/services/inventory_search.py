"""営業向け在庫検索ロジック (Sprint 7 / spec F7)。

spec.md v1.1 F7:
  - 全 7 種横断検索 (ja/en/expansion_code/card_number/jan_code/alias/tcg_series)
  - AND / OR トグル
  - 在庫 0 商品は末尾配置 + matched_via メタ
  - inventory.visibility.full=false の場合 stock_quantity マスク (None で返却)

設計判断 (PR description に明示):
  1. SQL 実装: CTE で各 source ごとに candidate product_id を抽出 → UNION ALL →
     LEFT JOIN public.products → ranking score (matched_via 優先度 + 在庫有無 + 完全一致)
     で ORDER BY し LIMIT する単一クエリ。
     UNION ALL を選んだ理由: 7 種それぞれの matched_via 情報を保持しつつ
     index を効かせやすい (各 source ごとに ILIKE / trigram が機能)。

  2. AND/OR: 入力 q を whitespace で token 分割し、各 token を ILIKE %t% で評価する。
     AND は INTERSECT 相当 (各 source 内で全 token AND)、OR は単純 ILIKE OR で評価。

  3. Ranking: card_number 完全一致 > jan_code 完全一致 > 完全一致 (name/name_en) >
     前方一致 > 部分一致 > supplier alias 部分一致 > tcg_series 部分一致。
     stock_quantity > 0 が score +10、stock=0 は score -10 で末尾に。

  4. matched_via: products_name / products_name_en / products_expansion_code /
                  products_card_number / products_jan_code / pokemon_dex /
                  trainer_dex / supplier_alias / tcg_series.

  5. visibility マスク: load_user_permissions の集合に inventory.visibility.full
     が含まれない場合、レスポンスの stock_quantity を None にする。
     フロントは None を `***` 表示で扱う (AC7.9)。

  6. pg_trgm 不可フォールバック: 本ロジックは ILIKE %q% のみで動作 (trigram は
     migration 068 の GIN index が PostgreSQL plan で自動利用される)。
     extension 未導入でも結果は同じ、レイテンシのみ劣化。
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


# 検索結果の matched_via 優先順位 (低数値が高優先)
MATCHED_VIA_PRIORITY: dict[str, int] = {
    "products_card_number_exact": 1,
    "products_jan_code_exact": 2,
    "products_name_exact": 3,
    "products_name_en_exact": 3,
    "products_card_number": 10,
    "products_jan_code": 11,
    "products_expansion_code": 12,
    "products_name": 13,
    "products_name_en": 14,
    "pokemon_dex": 20,
    "trainer_dex": 21,
    "tcg_series": 22,
    "supplier_alias": 30,
}

DEFAULT_LIMIT = 20
MAX_LIMIT = 50
MAX_QUERY_LEN = 255
MAX_TOKENS = 8


@dataclass(frozen=True)
class SearchCandidate:
    """検索候補 1 件。stock_quantity は visibility=False の user で None になる。"""

    product_id: int
    name: str
    name_en: str | None
    product_code: str | None
    expansion_code: str | None
    card_number: str | None
    jan_code: str | None
    unit_price: float | None
    stock_quantity: int | None
    supplier_default_id: int | None
    supplier_name: str | None
    image_url: str | None
    matched_via: str
    score: float


def _tokenize(query: str) -> list[str]:
    """ホワイトスペース分割 + 重複除去 + 長さ制限。"""
    if not query:
        return []
    raw = query.strip()[:MAX_QUERY_LEN]
    if not raw:
        return []
    tokens = [t for t in raw.split() if t]
    # 重複除去 (順序保持)
    seen: set[str] = set()
    out: list[str] = []
    for t in tokens:
        lk = t.lower()
        if lk in seen:
            continue
        seen.add(lk)
        out.append(t)
        if len(out) >= MAX_TOKENS:
            break
    return out


def _build_token_predicate(
    columns: list[str],
    tokens: list[str],
    op: str,
    params: dict[str, str],
    prefix: str,
) -> str:
    """1 source (columns 群) に対し tokens を AND/OR で結合した述語を返す。

    columns: list of column expressions (already qualified, e.g. "p.name", "pd.name_ja")
    tokens: list of search terms
    op: 'and' or 'or'
    params: 共有 SQL bind params 辞書 (副作用で埋める)
    prefix: bind param 名のプレフィックス (source 名 + token index)
    """
    if not tokens or not columns:
        return "FALSE"

    # 各 token に対し OR(column ILIKE :p) の塊を作る
    token_clauses: list[str] = []
    for ti, tk in enumerate(tokens):
        param_name = f"{prefix}_t{ti}"
        params[param_name] = f"%{tk}%"
        col_or = " OR ".join(f"{c} ILIKE :{param_name}" for c in columns)
        token_clauses.append(f"({col_or})")

    connector = " AND " if op == "and" else " OR "
    return f"({connector.join(token_clauses)})"


def build_search_sql(
    tokens: list[str],
    op: str,
    limit: int,
    params: dict[str, str | int],
) -> str:
    """7 種横断検索 SQL を構築する (PostgreSQL only)。

    params: 副作用で bind params を埋める。
    Returns: 完成した SQL 文字列。
    """
    # --- 各 source の candidate product_id を抽出する CTE ---
    # source ごとに matched_via ラベルと token AND/OR 述語を組み立てる。
    products_columns = ["p.name", "p.name_en"]
    products_card_columns = ["p.card_number"]
    products_jan_columns = ["p.jan_code"]
    products_expansion_columns = ["p.expansion_code"]
    pokemon_columns = ["pd.name_ja", "pd.name_en"]
    trainer_columns = ["td.name_ja", "td.name_en"]
    tcg_columns = ["tcg.name_ja", "tcg.name_en"]
    alias_columns = ["sa.alias_text"]

    products_pred = _build_token_predicate(
        products_columns, tokens, op, params, "p_name"
    )
    card_pred = _build_token_predicate(
        products_card_columns, tokens, op, params, "p_card"
    )
    jan_pred = _build_token_predicate(
        products_jan_columns, tokens, op, params, "p_jan"
    )
    exp_pred = _build_token_predicate(
        products_expansion_columns, tokens, op, params, "p_exp"
    )
    pokemon_pred = _build_token_predicate(pokemon_columns, tokens, op, params, "pk")
    trainer_pred = _build_token_predicate(trainer_columns, tokens, op, params, "tr")
    tcg_pred = _build_token_predicate(tcg_columns, tokens, op, params, "tcg")
    alias_pred = _build_token_predicate(alias_columns, tokens, op, params, "al")

    # 完全一致用 (最初の token のみで判定、スコア boost に使う)
    first_token = tokens[0] if tokens else ""
    params["first_token"] = first_token
    params["first_token_lower"] = first_token.lower()

    # 各 CTE: product_id と matched_via を返す。
    # supplier_alias / pokemon_dex / trainer_dex / tcg_series は product を直接持たないので
    #   public.products に JOIN (supplier_default_id / name / name_en 経由) して紐付ける。
    sql = f"""
WITH
  -- 1. products name / name_en
  m_products AS (
    SELECT p.id AS product_id,
           CASE
             WHEN LOWER(p.name) = :first_token_lower
               OR LOWER(COALESCE(p.name_en, '')) = :first_token_lower
             THEN 'products_name_exact'
             ELSE 'products_name'
           END AS matched_via
    FROM public.products p
    WHERE p.is_archived IS NOT TRUE
      AND {products_pred}
  ),
  -- 2. products.card_number
  m_card AS (
    SELECT p.id AS product_id,
           CASE WHEN LOWER(COALESCE(p.card_number, '')) = :first_token_lower
                THEN 'products_card_number_exact'
                ELSE 'products_card_number' END AS matched_via
    FROM public.products p
    WHERE p.is_archived IS NOT TRUE
      AND p.card_number IS NOT NULL
      AND {card_pred}
  ),
  -- 3. products.jan_code
  m_jan AS (
    SELECT p.id AS product_id,
           CASE WHEN LOWER(COALESCE(p.jan_code, '')) = :first_token_lower
                THEN 'products_jan_code_exact'
                ELSE 'products_jan_code' END AS matched_via
    FROM public.products p
    WHERE p.is_archived IS NOT TRUE
      AND p.jan_code IS NOT NULL
      AND {jan_pred}
  ),
  -- 4. products.expansion_code
  m_exp AS (
    SELECT p.id AS product_id,
           'products_expansion_code'::text AS matched_via
    FROM public.products p
    WHERE p.is_archived IS NOT TRUE
      AND p.expansion_code IS NOT NULL
      AND {exp_pred}
  ),
  -- 5. pokemon_dex → products (name_ja / name_en 経由で products.name / name_en 一致)
  m_pokemon AS (
    SELECT p.id AS product_id,
           'pokemon_dex'::text AS matched_via
    FROM public.pokemon_dex pd
    JOIN public.products p
      ON (p.name = pd.name_ja OR p.name_en = pd.name_en OR p.name = pd.name_en)
    WHERE p.is_archived IS NOT TRUE
      AND {pokemon_pred}
  ),
  -- 6. trainer_dex → products
  m_trainer AS (
    SELECT p.id AS product_id,
           'trainer_dex'::text AS matched_via
    FROM public.trainer_dex td
    JOIN public.products p
      ON (p.name = td.name_ja OR p.name_en = td.name_en OR p.name = td.name_en)
    WHERE p.is_archived IS NOT TRUE
      AND {trainer_pred}
  ),
  -- 7. tcg_series_master → products (expansion_code = series_code)
  m_tcg AS (
    SELECT p.id AS product_id,
           'tcg_series'::text AS matched_via
    FROM public.tcg_series_master tcg
    JOIN public.products p
      ON p.expansion_code = tcg.series_code
    WHERE p.is_archived IS NOT TRUE
      AND {tcg_pred}
  ),
  -- 8. supplier_aliases.alias_text → products (alias.product_id 直結)
  m_alias AS (
    SELECT p.id AS product_id,
           'supplier_alias'::text AS matched_via
    FROM public.supplier_aliases sa
    JOIN public.products p ON p.id = sa.product_id
    WHERE p.is_archived IS NOT TRUE
      AND sa.product_id IS NOT NULL
      AND {alias_pred}
  ),
  all_matches AS (
    SELECT * FROM m_products
    UNION ALL SELECT * FROM m_card
    UNION ALL SELECT * FROM m_jan
    UNION ALL SELECT * FROM m_exp
    UNION ALL SELECT * FROM m_pokemon
    UNION ALL SELECT * FROM m_trainer
    UNION ALL SELECT * FROM m_tcg
    UNION ALL SELECT * FROM m_alias
  ),
  -- 各 product_id について、最も高優先な matched_via を 1 行採用
  ranked AS (
    SELECT DISTINCT ON (product_id)
           product_id, matched_via
    FROM all_matches
    ORDER BY product_id,
             CASE matched_via
               WHEN 'products_card_number_exact' THEN 1
               WHEN 'products_jan_code_exact'   THEN 2
               WHEN 'products_name_exact'       THEN 3
               WHEN 'products_name_en_exact'    THEN 3
               WHEN 'products_card_number'      THEN 10
               WHEN 'products_jan_code'         THEN 11
               WHEN 'products_expansion_code'   THEN 12
               WHEN 'products_name'             THEN 13
               WHEN 'products_name_en'          THEN 14
               WHEN 'pokemon_dex'               THEN 20
               WHEN 'trainer_dex'               THEN 21
               WHEN 'tcg_series'                THEN 22
               WHEN 'supplier_alias'            THEN 30
               ELSE 99
             END
  )
SELECT
    p.id AS product_id,
    p.name,
    p.name_en,
    p.product_code,
    p.expansion_code,
    p.card_number,
    p.jan_code,
    p.unit_price,
    p.stock_quantity,
    p.supplier_default_id,
    s.name AS supplier_name,
    p.image_url,
    r.matched_via,
    -- ranking score:
    --   matched_via 優先度 (10〜30) を base + 在庫切れ penalty (+1000 で末尾) で総合化
    (CASE r.matched_via
       WHEN 'products_card_number_exact' THEN 1
       WHEN 'products_jan_code_exact'   THEN 2
       WHEN 'products_name_exact'       THEN 3
       WHEN 'products_name_en_exact'    THEN 3
       WHEN 'products_card_number'      THEN 10
       WHEN 'products_jan_code'         THEN 11
       WHEN 'products_expansion_code'   THEN 12
       WHEN 'products_name'             THEN 13
       WHEN 'products_name_en'          THEN 14
       WHEN 'pokemon_dex'               THEN 20
       WHEN 'trainer_dex'               THEN 21
       WHEN 'tcg_series'                THEN 22
       WHEN 'supplier_alias'            THEN 30
       ELSE 99
     END)
     + CASE WHEN COALESCE(p.stock_quantity, 0) <= 0 THEN 1000 ELSE 0 END
     AS score
FROM ranked r
JOIN public.products p ON p.id = r.product_id
LEFT JOIN public.suppliers s ON s.id = p.supplier_default_id
ORDER BY score ASC, p.id ASC
LIMIT :limit
"""
    params["limit"] = limit
    return sql


async def search_inventory(
    db: AsyncSession,
    query: str,
    op: str,
    limit: int,
    mask_stock: bool,
) -> list[SearchCandidate]:
    """7 種横断検索 + ranking + (optionally) stock マスクを実行する。

    Args:
      db: 既に search_path が設定された AsyncSession。
      query: 検索クエリ文字列 (whitespace 区切り tokens)。
      op: 'and' | 'or'。
      limit: 結果上限 (1〜MAX_LIMIT)。
      mask_stock: True の場合 stock_quantity を None に置換する。

    Returns:
      List[SearchCandidate] (score 昇順、在庫 0 末尾)。

    空クエリ / トークン抽出後 0 件の場合は空リストを返す (DB 呼出しなし)。
    """
    tokens = _tokenize(query)
    if not tokens:
        return []

    op_norm = "and" if op.lower() == "and" else "or"
    limit_norm = max(1, min(int(limit) if limit else DEFAULT_LIMIT, MAX_LIMIT))

    params: dict[str, str | int] = {}
    sql = build_search_sql(tokens, op_norm, limit_norm, params)

    result = await db.execute(text(sql), params)
    rows = result.mappings().all()
    out: list[SearchCandidate] = []
    for r in rows:
        stock = r.get("stock_quantity")
        if mask_stock:
            stock = None
        out.append(
            SearchCandidate(
                product_id=int(r["product_id"]),
                name=str(r["name"]),
                name_en=r.get("name_en"),
                product_code=r.get("product_code"),
                expansion_code=r.get("expansion_code"),
                card_number=r.get("card_number"),
                jan_code=r.get("jan_code"),
                unit_price=(float(r["unit_price"]) if r.get("unit_price") is not None else None),
                stock_quantity=(int(stock) if stock is not None else None),
                supplier_default_id=r.get("supplier_default_id"),
                supplier_name=r.get("supplier_name"),
                image_url=r.get("image_url"),
                matched_via=str(r["matched_via"]),
                score=float(r["score"]),
            )
        )
    return out
