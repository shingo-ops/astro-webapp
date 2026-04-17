from __future__ import annotations

"""
配送・物流管理API（ゾーン/料金マスタ + 配送料自動計算）。

旧GAS版の13_Shipping.gs に相当。
国→ゾーン→重量帯→料金の3段階検索で配送料を算出。
キャリア未指定時はFedEx/DHL/UPS3社比較で最安値を返す。

変更履歴:
  2026-04-17: 初版作成（Phase 2）
"""

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, get_current_tenant, require_permission
from app.database import get_db
from app.models import User
from app.schemas.shipping import (
    ShippingCalcRequest,
    ShippingCalcResponse,
    ShippingCalcResult,
    ShippingRateCreate,
    ShippingRateResponse,
    ShippingZoneCreate,
    ShippingZoneResponse,
)
from app.services.audit import record_audit_log

router = APIRouter()


# =========================================================================
# 配送ゾーン
# =========================================================================

@router.get(
    "/shipping/zones",
    response_model=list[ShippingZoneResponse],
    dependencies=[Depends(require_permission("shipping.view"))],
)
async def list_zones(
    carrier: str | None = Query(default=None),
    country_code: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    conditions = []
    params: dict = {}
    if carrier:
        conditions.append("carrier = :carrier")
        params["carrier"] = carrier
    if country_code:
        conditions.append("country_code = :cc")
        params["cc"] = country_code.upper()
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    result = await db.execute(
        text(f"SELECT id, country_code, country_name, carrier, zone, created_at FROM shipping_zones {where} ORDER BY country_name, carrier"),
        params,
    )
    return [ShippingZoneResponse(**row) for row in result.mappings().all()]


@router.post(
    "/shipping/zones",
    response_model=ShippingZoneResponse,
    status_code=201,
    dependencies=[Depends(require_permission("shipping.manage"))],
)
async def create_zone(
    data: ShippingZoneCreate,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    try:
        result = await db.execute(
            text("""
                INSERT INTO shipping_zones (tenant_id, country_code, country_name, carrier, zone)
                VALUES (:tid, :cc, :cn, :carrier, :zone)
                RETURNING id, country_code, country_name, carrier, zone, created_at
            """),
            {
                "tid": tenant_id,
                "cc": data.country_code.upper(),
                "cn": data.country_name,
                "carrier": data.carrier,
                "zone": data.zone,
            },
        )
        row = result.mappings().first()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="同じ国・キャリアのゾーンが既に存在します")

    await record_audit_log(
        db=db, tenant_id=tenant_id, user_id=current_user.id,
        action="create", table_name="shipping_zones", record_id=row["id"],
        new_data=data.model_dump(),
    )
    await db.commit()
    return ShippingZoneResponse(**dict(row))


@router.delete(
    "/shipping/zones/{zone_id}",
    status_code=204,
    dependencies=[Depends(require_permission("shipping.manage"))],
)
async def delete_zone(
    zone_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        text("DELETE FROM shipping_zones WHERE id = :id RETURNING id"),
        {"id": zone_id},
    )
    if not result.first():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ゾーンが見つかりません")
    await record_audit_log(
        db=db, tenant_id=tenant_id, user_id=current_user.id,
        action="delete", table_name="shipping_zones", record_id=zone_id,
    )
    await db.commit()


# =========================================================================
# 配送料金
# =========================================================================

@router.get(
    "/shipping/rates",
    response_model=list[ShippingRateResponse],
    dependencies=[Depends(require_permission("shipping.view"))],
)
async def list_rates(
    carrier: str | None = Query(default=None),
    zone: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    conditions = []
    params: dict = {}
    if carrier:
        conditions.append("carrier = :carrier")
        params["carrier"] = carrier
    if zone:
        conditions.append("zone = :zone")
        params["zone"] = zone
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    result = await db.execute(
        text(f"""
            SELECT id, carrier, zone, weight_min, weight_max, price, currency, created_at, updated_at
            FROM shipping_rates {where}
            ORDER BY carrier, zone, weight_min
        """),
        params,
    )
    return [ShippingRateResponse(**row) for row in result.mappings().all()]


@router.post(
    "/shipping/rates",
    response_model=ShippingRateResponse,
    status_code=201,
    dependencies=[Depends(require_permission("shipping.manage"))],
)
async def create_rate(
    data: ShippingRateCreate,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        text("""
            INSERT INTO shipping_rates (tenant_id, carrier, zone, weight_min, weight_max, price, currency)
            VALUES (:tid, :carrier, :zone, :wmin, :wmax, :price, :currency)
            RETURNING id, carrier, zone, weight_min, weight_max, price, currency, created_at, updated_at
        """),
        {
            "tid": tenant_id,
            "carrier": data.carrier,
            "zone": data.zone,
            "wmin": data.weight_min,
            "wmax": data.weight_max,
            "price": data.price,
            "currency": data.currency,
        },
    )
    row = result.mappings().first()

    await record_audit_log(
        db=db, tenant_id=tenant_id, user_id=current_user.id,
        action="create", table_name="shipping_rates", record_id=row["id"],
        new_data=data.model_dump(mode="json"),
    )
    await db.commit()
    return ShippingRateResponse(**dict(row))


@router.delete(
    "/shipping/rates/{rate_id}",
    status_code=204,
    dependencies=[Depends(require_permission("shipping.manage"))],
)
async def delete_rate(
    rate_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        text("DELETE FROM shipping_rates WHERE id = :id RETURNING id"),
        {"id": rate_id},
    )
    if not result.first():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="料金が見つかりません")
    await record_audit_log(
        db=db, tenant_id=tenant_id, user_id=current_user.id,
        action="delete", table_name="shipping_rates", record_id=rate_id,
    )
    await db.commit()


# =========================================================================
# 配送料自動計算
# =========================================================================

async def calculate_shipping_fee(
    db: AsyncSession,
    country_code: str,
    weight_kg: Decimal,
    carrier: str | None = None,
) -> list[ShippingCalcResult]:
    """
    国コード＋重量から配送料を計算する。
    carrier指定時はそのキャリアのみ、未指定時はFedEx/DHL/UPS全社を返す。
    """
    conditions = ["sz.country_code = :cc"]
    params: dict = {"cc": country_code.upper(), "weight": weight_kg}
    if carrier:
        conditions.append("sz.carrier = :carrier")
        params["carrier"] = carrier

    where = " AND ".join(conditions)

    result = await db.execute(
        text(f"""
            SELECT sz.carrier, sz.zone, sr.price, sr.currency
            FROM shipping_zones sz
            JOIN shipping_rates sr
              ON sr.carrier = sz.carrier
             AND sr.zone = sz.zone
             AND sr.weight_min <= :weight
             AND sr.weight_max > :weight
            WHERE {where}
            ORDER BY sr.price
        """),
        params,
    )
    rows = result.mappings().all()
    return [
        ShippingCalcResult(carrier=r["carrier"], zone=r["zone"], fee=r["price"], currency=r["currency"])
        for r in rows
    ]


@router.post(
    "/shipping/calculate",
    response_model=ShippingCalcResponse,
    dependencies=[Depends(require_permission("shipping.view", "shipping.calculate"))],
)
async def calc_shipping(
    data: ShippingCalcRequest,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """配送料を自動計算する。キャリア未指定時は3社比較で最安値も返す。"""
    results = await calculate_shipping_fee(db, data.country_code, data.weight_kg, data.carrier)
    cheapest = results[0] if results else None
    return ShippingCalcResponse(results=results, cheapest=cheapest)
