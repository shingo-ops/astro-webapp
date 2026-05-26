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

from app.auth.dependencies import require_super_admin
from app.database import get_db
from app.schemas.inventory_offers import (
    InventoryOfferCreate,
    InventoryOfferListResponse,
    InventoryOfferResponse,
    InventoryOfferUpdate,
)

router = APIRouter()


_BASE_SELECT = """
    SELECT i.id, i.supplier_id, i.product_id, i.condition, i.quantity,
           i.unit_price, i.status, i.notes_ja, i.notes_en,
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
                        (supplier_id, product_id, condition, quantity, unit_price,
                         status, notes_ja, notes_en, expires_at, source)
                    VALUES (:supplier_id, :product_id, :condition, :quantity, :unit_price,
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
    """admin が在庫数 / 単価 / status / メモ / 期限を編集 (AC11.5)。

    UNIQUE キー (supplier_id, product_id, condition) は変更不可。変更したい場合は
    DELETE + POST してください。
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

    result = await db.execute(
        text(f"UPDATE public.inventory SET {set_clause} WHERE id = :id RETURNING id"),
        update_data,
    )
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
