"""中央 admin 用 public.inventory CRUD ルーター (spec.md v1.3 F11 / AC11.5)。

API:
  GET    /api/v1/super-admin/inventory-offers           list (filter + paginate)
  POST   /api/v1/super-admin/inventory-offers           create (409 on UNIQUE 衝突)
  PATCH  /api/v1/super-admin/inventory-offers/{id}      update (quantity/unit_price/status/notes/expires_at)
  DELETE /api/v1/super-admin/inventory-offers/{id}      hard delete

AC11.5 の admin 編集を満たす最小 CRUD。UPSERT は F6 承認時 (`apply_inbound_items`) 経路で
別途処理する設計のため、本ルーターでは INSERT は UNIQUE 衝突時 409 を返し、
admin は明示的に PATCH を選ぶ。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_permission, require_super_admin
from app.database import get_db
from app.schemas.inventory_offers import (
    InventoryListResponse,
    InventoryOfferCreate,
    InventoryOfferListResponse,
    InventoryOfferResponse,
    InventoryOfferUpdate,
    InventoryRow,
)

router = APIRouter()


_BASE_SELECT = """
    SELECT i.id, i.supplier_id, i.product_id, i.condition, i.quantity,
           i.unit_price, i.unit, i.offer_type, i.ship_timing,
           i.status, i.notes_ja, i.notes_en,
           i.offered_at, i.expires_at, i.source,
           i.created_at, i.updated_at,
           s.name AS supplier_name,
           p.product_code AS product_code,
           p.name AS product_name
    FROM public.inventory i
    LEFT JOIN public.suppliers s ON s.id = i.supplier_id
    LEFT JOIN public.products  p ON p.id = i.product_id
"""

_UPDATABLE_COLS = {
    "quantity",
    "unit_price",
    "unit",
    # ADR-093 Phase 3: 区分/発送日も admin が編集可（UNIQUE キー要素のため衝突時は 409）
    "offer_type",
    "ship_timing",
    "status",
    "notes_ja",
    "notes_en",
    "expires_at",
}


async def _load_offer(db: AsyncSession, offer_id: int) -> dict | None:
    row = (
        await db.execute(
            text(f"{_BASE_SELECT} WHERE i.id = :id"),
            {"id": offer_id},
        )
    ).mappings().first()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# 最終ユーザー向け在庫表ビュー GET /inventory（ADR-093 Phase 2）
# 各クライアントの営業担当ロール以上（products.view）が閲覧。読み取り専用。
# ---------------------------------------------------------------------------

# 在庫表ビュー用 SELECT（参考画像準拠の列。admin 専用の notes/source/status は除外）。
_VIEW_SELECT = """
    SELECT i.id, i.product_id, i.condition, i.unit,
           i.offer_type, i.ship_timing, i.unit_price,
           i.quantity, i.offered_at, i.supplier_id,
           s.name AS supplier_name,
           p.name AS product_name,
           p.name_en AS name_en,
           p.category AS category,
           p.mark AS mark,
           p.tcg_type AS tcg_type
    FROM public.inventory i
    LEFT JOIN public.suppliers s ON s.id = i.supplier_id
    LEFT JOIN public.products  p ON p.id = i.product_id
"""

_VIEW_COUNT_FROM = (
    "FROM public.inventory i "
    "LEFT JOIN public.suppliers s ON s.id = i.supplier_id "
    "LEFT JOIN public.products  p ON p.id = i.product_id "
)


@router.get(
    "/inventory",
    response_model=InventoryListResponse,
    dependencies=[Depends(require_permission("products.view"))],
)
async def list_inventory_view(
    q: str | None = Query(default=None, max_length=255, description="商品名/英名/コード/カテゴリ/マーク/仕入元の部分一致"),
    tcg_type: str | None = Query(default=None, max_length=50, description="TCG種別 (public.products.tcg_type)"),
    offer_type: str | None = Query(default=None, pattern="^(in_stock|pre_order)$", description="区分: in_stock(在庫) / pre_order(予約)"),
    sort: str = Query(default="name", pattern="^(name)$"),
    order: str = Query(default="asc", pattern="^(asc|desc)$"),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """在庫表（最終ユーザー向け）。

    public.inventory の status='in_stock' かつ未失効 (expires_at > NOW()) のオファーを
    「商品×仕入元×状態」の明細行で返す。名前ソート + TCG種別フィルタ + 検索 + ページング。

    - 権限: products.view（各クライアントの営業担当ロール以上）。編集/削除は持たない。
    - 18h 失効: expires_at <= NOW() の行は非表示（表示フィルタのみ、実データは消さない）。
    - 在庫数マスクなし（I-05 撤廃 / 在庫は全テナント共通で見える）。
    """
    offset = (page - 1) * per_page
    conditions: list[str] = [
        "i.status = 'in_stock'",
        "(i.expires_at IS NULL OR i.expires_at > NOW())",
    ]
    params: dict = {"limit": per_page, "offset": offset}
    if tcg_type:
        conditions.append("p.tcg_type = :tcg_type")
        params["tcg_type"] = tcg_type
    if offer_type:
        conditions.append("i.offer_type = :offer_type")
        params["offer_type"] = offer_type
    if q:
        conditions.append(
            "(s.name ILIKE :q OR p.name ILIKE :q OR p.name_en ILIKE :q "
            "OR p.product_code ILIKE :q OR p.category ILIKE :q OR p.mark ILIKE :q)"
        )
        params["q"] = f"%{q}%"
    where = "WHERE " + " AND ".join(conditions)
    order_dir = "ASC" if order == "asc" else "DESC"

    total = (
        await db.execute(
            text(f"SELECT COUNT(*) {_VIEW_COUNT_FROM} {where}"),
            params,
        )
    ).scalar_one()

    result = await db.execute(
        text(
            f"{_VIEW_SELECT} {where} "
            f"ORDER BY p.name {order_dir} NULLS LAST, i.id ASC "
            "LIMIT :limit OFFSET :offset"
        ),
        params,
    )
    items = [InventoryRow(**dict(r)) for r in result.mappings().all()]
    return InventoryListResponse(
        items=items, total=int(total or 0), page=page, per_page=per_page
    )


@router.get(
    "/super-admin/inventory-offers",
    response_model=InventoryOfferListResponse,
    dependencies=[Depends(require_super_admin)],
)
async def list_offers(
    supplier_id: int | None = Query(default=None, gt=0),
    product_id: int | None = Query(default=None, gt=0),
    condition: str | None = Query(default=None, max_length=50),
    status_filter: str | None = Query(default=None, alias="status", max_length=20),
    q: str | None = Query(default=None, max_length=255, description="supplier_name / product_name / product_code 部分一致"),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    """仕入元現在オファー一覧 (AC11.5)。"""
    offset = (page - 1) * per_page
    conditions: list[str] = []
    params: dict = {"limit": per_page, "offset": offset}

    if supplier_id is not None:
        conditions.append("i.supplier_id = :supplier_id")
        params["supplier_id"] = supplier_id
    if product_id is not None:
        conditions.append("i.product_id = :product_id")
        params["product_id"] = product_id
    if condition:
        conditions.append("i.condition = :condition")
        params["condition"] = condition
    if status_filter:
        conditions.append("i.status = :status_filter")
        params["status_filter"] = status_filter
    if q:
        conditions.append(
            "(s.name ILIKE :q OR p.name ILIKE :q OR p.product_code ILIKE :q)"
        )
        params["q"] = f"%{q}%"

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    total_row = await db.execute(
        text(f"SELECT COUNT(*) AS c FROM public.inventory i "
             f"LEFT JOIN public.suppliers s ON s.id = i.supplier_id "
             f"LEFT JOIN public.products  p ON p.id = i.product_id {where}"),
        params,
    )
    total = int(total_row.scalar_one() or 0)

    result = await db.execute(
        text(
            f"{_BASE_SELECT} {where} "
            "ORDER BY i.offered_at DESC, i.id DESC "
            "LIMIT :limit OFFSET :offset"
        ),
        params,
    )
    items = [InventoryOfferResponse(**dict(r)) for r in result.mappings().all()]
    return InventoryOfferListResponse(
        items=items, total=total, page=page, per_page=per_page
    )


@router.post(
    "/super-admin/inventory-offers",
    response_model=InventoryOfferResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_super_admin)],
)
async def create_offer(
    payload: InventoryOfferCreate,
    db: AsyncSession = Depends(get_db),
):
    """新規オファーを admin が手動追加 (AC11.5)。"""
    try:
        new_id = (
            await db.execute(
                text(
                    """
                    INSERT INTO public.inventory
                        (supplier_id, product_id, condition, quantity, unit_price, unit,
                         offer_type, ship_timing,
                         status, notes_ja, notes_en, expires_at, source)
                    VALUES (:supplier_id, :product_id, :condition, :quantity, :unit_price, :unit,
                            :offer_type, :ship_timing,
                            :status, :notes_ja, :notes_en, :expires_at, :source)
                    RETURNING id
                    """
                ),
                payload.model_dump(),
            )
        ).scalar_one()
        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "同じ supplier × product × condition のオファーが既に存在します。"
                "PATCH で更新するか、condition を変えて作成してください。"
            ),
        ) from e

    offer = await _load_offer(db, int(new_id))
    if offer is None:
        raise HTTPException(status_code=500, detail="INSERT 直後の取得に失敗しました")
    return InventoryOfferResponse(**offer)


@router.patch(
    "/super-admin/inventory-offers/{offer_id}",
    response_model=InventoryOfferResponse,
    dependencies=[Depends(require_super_admin)],
)
async def update_offer(
    offer_id: int,
    payload: InventoryOfferUpdate,
    db: AsyncSession = Depends(get_db),
):
    """admin が在庫数 / 単価 / 形態 / 区分 / 発送日 / status / メモ / 期限を編集 (AC11.5)。

    supplier_id / product_id / condition は変更不可。unit / offer_type / ship_timing は
    UNIQUE キー要素のため、変更により他オファーと衝突する場合は 409 を返す（ADR-093 Phase 3）。
    """
    update_data = payload.model_dump(exclude_unset=True)
    update_data = {k: v for k, v in update_data.items() if k in _UPDATABLE_COLS}
    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="更新するフィールドを指定してください",
        )

    set_clause = ", ".join(f"{k} = :{k}" for k in update_data)
    update_data["id"] = offer_id

    try:
        result = await db.execute(
            text(f"UPDATE public.inventory SET {set_clause} WHERE id = :id RETURNING id"),
            update_data,
        )
    except IntegrityError as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "形態 / 区分 / 発送日 の変更で同一キー（仕入元×商品×状態×形態×区分×発送日）の"
                "オファーと衝突しました。既存行を確認してください。"
            ),
        ) from e
    if result.first() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="指定されたオファーが見つかりません",
        )
    await db.commit()

    offer = await _load_offer(db, offer_id)
    if offer is None:
        raise HTTPException(status_code=500, detail="UPDATE 直後の取得に失敗しました")
    return InventoryOfferResponse(**offer)


@router.delete(
    "/super-admin/inventory-offers/{offer_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_super_admin)],
)
async def delete_offer(
    offer_id: int,
    db: AsyncSession = Depends(get_db),
):
    """オファーを物理削除 (AC11.5)。再投入は F6 承認 or POST で。"""
    result = await db.execute(
        text("DELETE FROM public.inventory WHERE id = :id RETURNING id"),
        {"id": offer_id},
    )
    if result.first() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="指定されたオファーが見つかりません",
        )
    await db.commit()
