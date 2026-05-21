"""営業向け在庫検索 API ルーター (Sprint 7 / spec F7)。

spec.md v1.1 F7:
  GET /api/v1/inventory/search?q=<query>&lang=<ja|en>&op=<and|or>&limit=<n>

  - 全 7 種横断 (products name/name_en/expansion_code/card_number/jan_code +
    pokemon_dex name_ja/name_en + trainer_dex name_ja/name_en +
    tcg_series_master name_ja/name_en + supplier_aliases.alias_text)
  - AND / OR トグル
  - ranking + 在庫 0 末尾配置 + supplier 名同梱
  - inventory.visibility.full / .staff / .viewer のいずれか必須
  - inventory.visibility.full を持たない user では stock_quantity=None でマスク (AC7.9)

acceptance:
  AC7.1〜7.6 + 7.8 = 本ルーター
  AC7.7 = i18n (frontend)
  AC7.9 = mask 制御 (本ルーター + frontend)

権限階層:
  - products.view か inventory.visibility.full / staff / viewer のいずれか持っていれば検索可能
  - inventory.visibility.full ⇒ stock_quantity 露出
  - 上記なし ⇒ stock_quantity = None マスク
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import (
    get_current_tenant,
    get_current_user,
    load_user_permissions,
)
from app.database import get_db
from app.models import User
from app.schemas.inventory_search import (
    InventorySearchCandidate,
    InventorySearchResponse,
)
from app.services.inventory_search import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    MAX_QUERY_LEN,
    search_inventory,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# 検索 API を叩くために最低限必要な権限のいずれか (OR 条件)。
# inventory.visibility.full を持つ user は stock マスクなし、その他は stock=None マスク。
ALLOWED_PERMISSIONS: frozenset[str] = frozenset(
    {
        "products.view",
        "inventory.visibility.full",
        "inventory.visibility.staff",
        "inventory.visibility.viewer",
    }
)
FULL_VISIBILITY_PERMISSION = "inventory.visibility.full"


@router.get(
    "/inventory/search",
    response_model=InventorySearchResponse,
    summary="全 7 種横断 在庫検索 (F7)",
)
async def search_inventory_endpoint(
    q: str = Query(default="", max_length=MAX_QUERY_LEN, description="検索クエリ (whitespace 区切り tokens)"),
    lang: str = Query(default="ja", pattern="^(ja|en)$", description="UI 言語 (ja/en)。応答に影響なし、placeholder 等の UI 言語選択用ヒント"),
    op: str = Query(default="or", pattern="^(and|or)$", description="複数トークン時の結合演算子"),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT, description="最大返却件数"),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """全 7 種横断 在庫検索 API。

    - lang は応答 schema に影響しない (検索は ja/en 両方の列を横断する)。
    - 空クエリは {candidates: [], total: 0} を即返す。
    - inventory.visibility.full を持たないユーザーは stock_quantity を None でマスク。
    """
    # --- 権限チェック ---
    perms = await load_user_permissions(db, tenant_id, current_user.id)
    if not (perms & ALLOWED_PERMISSIONS):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="在庫検索を実行する権限がありません (inventory.visibility.* または products.view が必要)。",
        )

    mask_stock = FULL_VISIBILITY_PERMISSION not in perms

    # --- 検索実行 ---
    candidates = await search_inventory(
        db=db,
        query=q,
        op=op,
        limit=limit,
        mask_stock=mask_stock,
    )

    payload_candidates = [
        InventorySearchCandidate(
            product_id=c.product_id,
            name=c.name,
            name_en=c.name_en,
            product_code=c.product_code,
            expansion_code=c.expansion_code,
            card_number=c.card_number,
            jan_code=c.jan_code,
            unit_price=c.unit_price,
            stock_quantity=c.stock_quantity,
            supplier_default_id=c.supplier_default_id,
            supplier_name=c.supplier_name,
            image_url=c.image_url,
            matched_via=c.matched_via,
            score=c.score,
        )
        for c in candidates
    ]

    return InventorySearchResponse(
        query=q,
        op=op,
        total=len(payload_candidates),
        masked=mask_stock,
        candidates=payload_candidates,
    )
