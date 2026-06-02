"""
中央 admin 用 Discord Inbound 一覧 / 詳細 API。

spec.md v1.1 F5 (Sprint 5) / AC5.5:
  - require_super_admin で保護（is_super_admin=true のみ）
  - public.discord_inbound_messages を時系列降順で返す
  - parse_status / supplier_id / search クエリでフィルタ可能
  - 詳細 API で parse_result_json も返す（F6 レビュー UI が後段で参照）

API:
  GET /api/v1/super-admin/inbound/discord       一覧
  GET /api/v1/super-admin/inbound/discord/{id}  詳細
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_super_admin
from app.database import get_db
from app.schemas.discord_inbound import (
    DiscordInboundDetail,
    DiscordInboundListItem,
    InboundProductCandidate,
    InboundProductCandidatesResponse,
    InboundProductImportApply,
    InboundProductImportApplyResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()


_LIST_COLS = (
    "m.id, m.discord_message_id, m.discord_channel_id, m.supplier_id, "
    "m.raw_content, m.parse_status, m.parse_engine, "
    "m.received_at, m.llm_cost_usd, s.name AS supplier_name"
)

_DETAIL_COLS = (
    "m.id, m.discord_message_id, m.discord_channel_id, m.supplier_id, "
    "m.raw_content, m.parse_status, m.parse_engine, "
    "m.parse_result_json, m.received_at, m.exclude_reason, "
    "m.operator_comment, m.operator_id, m.approved_at, m.llm_cost_usd, "
    "m.created_at, m.updated_at, s.name AS supplier_name"
)

_PREVIEW_LEN = 200


def _row_to_list_item(row: dict) -> DiscordInboundListItem:
    raw = row.get("raw_content") or ""
    return DiscordInboundListItem(
        id=row["id"],
        discord_message_id=row["discord_message_id"],
        discord_channel_id=row["discord_channel_id"],
        supplier_id=row.get("supplier_id"),
        supplier_name=row.get("supplier_name"),
        raw_content_preview=raw[:_PREVIEW_LEN],
        parse_status=row["parse_status"],
        parse_engine=row.get("parse_engine"),
        received_at=row["received_at"],
        llm_cost_usd=row.get("llm_cost_usd"),
    )


@router.get(
    "/super-admin/inbound/discord",
    response_model=list[DiscordInboundListItem],
    dependencies=[Depends(require_super_admin)],
)
async def list_inbound(
    parse_status: str | None = Query(default=None, max_length=30),
    supplier_id: int | None = Query(default=None),
    q: str | None = Query(default=None, max_length=255),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    """Discord 受信メッセージ一覧。時系列降順。

    AC5.5: tenant_006 に予め INSERT した 3 件が新しい順で表示される。
    """
    offset = (page - 1) * per_page
    conditions: list[str] = []
    params: dict = {"limit": per_page, "offset": offset}

    if parse_status:
        conditions.append("m.parse_status = :status")
        params["status"] = parse_status
    if supplier_id is not None:
        conditions.append("m.supplier_id = :sup_id")
        params["sup_id"] = supplier_id
    if q:
        conditions.append("m.raw_content ILIKE :q")
        params["q"] = f"%{q}%"

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    sql = (
        f"SELECT {_LIST_COLS} "
        f"FROM public.discord_inbound_messages m "
        f"LEFT JOIN public.suppliers s ON s.id = m.supplier_id "
        f"{where} "
        f"ORDER BY m.received_at DESC, m.id DESC "
        f"LIMIT :limit OFFSET :offset"
    )
    result = await db.execute(text(sql), params)
    return [_row_to_list_item(dict(row)) for row in result.mappings().all()]


@router.get(
    "/super-admin/inbound/discord/{inbound_id}",
    response_model=DiscordInboundDetail,
    dependencies=[Depends(require_super_admin)],
)
async def get_inbound(
    inbound_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Discord 受信メッセージ詳細。parse_result_json 含む。"""
    result = await db.execute(
        text(
            f"SELECT {_DETAIL_COLS} "
            f"FROM public.discord_inbound_messages m "
            f"LEFT JOIN public.suppliers s ON s.id = m.supplier_id "
            f"WHERE m.id = :id"
        ),
        {"id": inbound_id},
    )
    row = result.mappings().first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="inbound not found"
        )
    return DiscordInboundDetail(
        id=row["id"],
        discord_message_id=row["discord_message_id"],
        discord_channel_id=row["discord_channel_id"],
        supplier_id=row.get("supplier_id"),
        supplier_name=row.get("supplier_name"),
        raw_content=row["raw_content"],
        parse_status=row["parse_status"],
        parse_engine=row.get("parse_engine"),
        parse_result_json=row.get("parse_result_json"),
        received_at=row["received_at"],
        exclude_reason=row.get("exclude_reason"),
        operator_comment=row.get("operator_comment"),
        operator_id=row.get("operator_id"),
        approved_at=row.get("approved_at"),
        llm_cost_usd=row.get("llm_cost_usd"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


# ---------------------------------------------------------------------------
# 受信通知 → 商品マスタ取込（プレビュー付き）
#
# 受信通知の解析結果（parse_result_json.items[].product_name）には商品マスタ
# （public.products）へ未登録の商品名が多数含まれる（例: ヴァイスシュヴァルツ等）。
# preview で未登録の候補を出現回数付きで抽出し、オペレータがノイズを外したうえで
# apply で選択分を public.products へ一括登録する。
# ---------------------------------------------------------------------------

# 解析結果から商品名候補を取り出すための共通 CTE。
# parse_result_json.items[] の product_name をトリムし、空でないものだけ対象にする。
# PR5c: 取込時に転記する unit / condition も同時に取り出す。
#   - unit は小文字化し carton→case に正規化（ユーザー方針 2026-06-02）
#   - condition は小文字化（表記揺れ吸収）。空文字は NULL 扱い
_PARSED_ITEMS_CTE = (
    "SELECT TRIM(it->>'product_name') AS pname, it->>'raw_line' AS raw_line, "
    "CASE WHEN LOWER(TRIM(it->>'unit')) = 'carton' THEN 'case' "
    "     ELSE NULLIF(LOWER(TRIM(it->>'unit')), '') END AS unit, "
    "NULLIF(LOWER(TRIM(it->>'condition')), '') AS condition "
    "FROM public.discord_inbound_messages m, "
    "jsonb_array_elements(COALESCE(m.parse_result_json->'items', '[]'::jsonb)) it "
    "WHERE COALESCE(TRIM(it->>'product_name'), '') <> ''"
)
# 取込候補の言語は全件デフォルト「日本語(ja)」（ユーザー方針 2026-06-02）。
# 英語の商品は取込 UI でオペレータが個別に 'en' へ修正する。
_DEFAULT_IMPORT_LANGUAGE = "ja"


@router.get(
    "/super-admin/inbound/product-candidates",
    response_model=InboundProductCandidatesResponse,
    dependencies=[Depends(require_super_admin)],
)
async def list_product_candidates(
    db: AsyncSession = Depends(get_db),
):
    """受信通知の解析結果のうち、商品マスタ未登録の商品名候補を抽出する。

    - public.products.name に exact 一致しないものだけを返す
    - 出現回数（occurrences）の多い順、同数なら名前順
    - 抽出元の受信本文サンプル（sample）を 1 件添える
    """
    result = await db.execute(
        text(
            f"WITH parsed AS ({_PARSED_ITEMS_CTE}) "
            "SELECT p.pname AS name, COUNT(*) AS occurrences, MIN(p.raw_line) AS sample, "
            "  mode() WITHIN GROUP (ORDER BY p.unit) FILTER (WHERE p.unit IS NOT NULL) AS unit, "
            "  mode() WITHIN GROUP (ORDER BY p.condition) FILTER (WHERE p.condition IS NOT NULL) AS condition "
            "FROM parsed p "
            "WHERE NOT EXISTS ("
            "  SELECT 1 FROM public.products pr WHERE pr.name = p.pname"
            ") "
            "GROUP BY p.pname "
            "ORDER BY COUNT(*) DESC, p.pname"
        )
    )
    rows = result.mappings().all()
    candidates = [
        InboundProductCandidate(
            name=r["name"],
            occurrences=int(r["occurrences"]),
            sample=r.get("sample"),
            unit=r.get("unit"),
            condition=r.get("condition"),
            # 言語は全件デフォルト日本語。取込 UI でオペレータが個別修正可能。
            language=_DEFAULT_IMPORT_LANGUAGE,
        )
        for r in rows
    ]
    return InboundProductCandidatesResponse(candidates=candidates, total=len(candidates))


@router.post(
    "/super-admin/inbound/product-candidates/apply",
    response_model=InboundProductImportApplyResponse,
    dependencies=[Depends(require_super_admin)],
)
async def apply_product_candidates(
    payload: InboundProductImportApply,
    db: AsyncSession = Depends(get_db),
):
    """選択された商品名候補を public.products へ一括登録する。

    - 同名（name 完全一致）が既に存在する場合はスキップ
      （NOT EXISTS による重複防止。products.name に UNIQUE は無いため
      厳密な同時実行排他ではないが、通常運用では実質冪等）
    - category は任意。指定があれば全件に同じ分類を付与する
    - PR5c: 解析結果(parse_result_json) から代表的な unit / condition を転記する。
      unit は carton→case 正規化済・小文字、condition は小文字。
    - language は payload.languages の上書き（取込 UI でオペレータが修正した値）を
      優先し、無指定なら商品名から自動判定（日本語文字があれば ja、無ければ en）。
    """
    # public.products.name は VARCHAR(255)。超過名はバッチ全体を巻き込む
    # 制約違反（→全件ロールバック）になるため、登録対象から除外する。
    _NAME_MAX_LEN = 255
    category = (payload.category or "").strip() or None

    # 商品名 → 代表的な unit / condition（最頻値）。解析結果全体から一括取得して
    # 名前ごとに引く（候補抽出と同じ正規化ルール）。
    rep_result = await db.execute(
        text(
            f"WITH parsed AS ({_PARSED_ITEMS_CTE}) "
            "SELECT pname, "
            "  mode() WITHIN GROUP (ORDER BY unit) FILTER (WHERE unit IS NOT NULL) AS unit, "
            "  mode() WITHIN GROUP (ORDER BY condition) FILTER (WHERE condition IS NOT NULL) AS condition "
            "FROM parsed GROUP BY pname"
        )
    )
    rep: dict[str, tuple[str | None, str | None]] = {
        r["pname"]: (r.get("unit"), r.get("condition")) for r in rep_result.mappings().all()
    }
    overrides = payload.languages or {}

    inserted = 0
    skipped = 0
    seen: set[str] = set()
    for raw_name in payload.names:
        name = (raw_name or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        if len(name) > _NAME_MAX_LEN:
            skipped += 1
            continue
        unit, condition = rep.get(name, (None, None))
        # 言語は UI 上書きを優先し、無指定/不正値はデフォルト日本語。
        lang = (overrides.get(name) or "").strip().lower()
        if lang not in ("ja", "en"):
            lang = _DEFAULT_IMPORT_LANGUAGE
        result = await db.execute(
            text(
                "INSERT INTO public.products (name, category, unit, condition, language) "
                "SELECT :name, :category, :unit, :condition, :language "
                "WHERE NOT EXISTS ("
                "  SELECT 1 FROM public.products WHERE name = :name"
                ")"
            ),
            {
                "name": name,
                "category": category,
                "unit": unit,
                "condition": condition,
                "language": lang,
            },
        )
        if result.rowcount:
            inserted += 1
        else:
            skipped += 1
    await db.commit()
    logger.info(
        "inbound product import: inserted=%s skipped=%s category=%s",
        inserted,
        skipped,
        category,
    )
    return InboundProductImportApplyResponse(inserted=inserted, skipped=skipped)
