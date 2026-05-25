from __future__ import annotations

"""
受注ごとの発送情報 API（order_shipping_details）。

ADR-021 Phase 3 / Sprint 3: 発送情報 MVP
  - POST   /orders/{order_id}/shipping — 新規作成（既存があれば 409）
  - GET    /orders/{order_id}/shipping — 取得（不存在 404）
  - PATCH  /orders/{order_id}/shipping — 部分更新（自動 updated_at）
  - DELETE /orders/{order_id}/shipping — 削除（CASCADE 任せでも済むが明示削除用）
  - GET    /orders/{order_id}/shipping/elogi-csv — eLogi 用 CSV 1 行 (text/csv)
  - GET    /shipping/elogi-csv?order_ids=... — bulk export (CSV)

権限・テナント:
  - require_permission("orders.view") for GET 系
  - require_permission("orders.update") for write 系
  - Depends(get_current_tenant) で tenant スキーマを切替（既存 orders と同じ経路）

ADR-021 制約 5「eLogi CSV 出力フォーマット互換性」:
  eLogi 既存フォーマット（19 列）を変更しない。adapter 層で吸収する。

変更履歴:
  2026-05-11: 初版（ADR-021 Phase 3 / Sprint 3）
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import (
    get_current_user,
    get_current_tenant,
    require_permission,
)
from app.database import get_db
from app.models import User
from app.schemas.order_shipping_detail import (
    INPUT_FIELDS,
    OrderShippingDetailCreate,
    OrderShippingDetailResponse,
    OrderShippingDetailUpdate,
)
from app.services.audit import record_audit_log
from app.services.shipping_carriers import get_adapter

router = APIRouter()


def _is_postgresql(db: AsyncSession) -> bool:
    """db の dialect が PostgreSQL 系か判定する (Issue #766)。

    pytest は SQLite (aiosqlite) で実行されるため、schema prefix を入れると
    "no such table: tenant_NNN.order_shipping_details" で失敗する。本判定で
    SQLite 系を検出して prefix なしに倒す。
    """
    bind = db.get_bind() if hasattr(db, "get_bind") else None
    if bind is None:
        bind = getattr(db, "bind", None)
    name = getattr(getattr(bind, "dialect", None), "name", "") or ""
    return name.startswith("postgresql")


def _t(db: AsyncSession, tenant_id: int, name: str) -> str:
    """tenant スキーマ修飾テーブル参照を返す (Issue #766)。

    - PostgreSQL: `tenant_{id:03d}.{name}` (schema prefix 明示)
    - SQLite (pytest): `{name}` (schema 概念なし)

    AsyncSession の commit 後は新コネクションが払い出されて session-level
    の search_path が失われる可能性があるため、raw text() を使う箇所では
    schema prefix を明示するのが安全 (Issue #563 / #565 / #766)。
    """
    if _is_postgresql(db):
        safe_id = int(tenant_id)
        return f"tenant_{safe_id:03d}.{name}"
    return name


# DB 列のうち入出力対象のホワイトリスト。動的 INSERT / UPDATE の組み立ては必ず
# この集合を経由すること（外部キー以外の任意フィールド書き換えを防ぐ）。
_UPDATABLE_COLUMNS: frozenset[str] = frozenset(INPUT_FIELDS)

_SELECT_COLS = """
    id, order_id, tenant_id,
    recipient_name, phone, email, tax_number,
    address1, address2, address3, city,
    state_code, zip_code, country_code,
    length_cm, width_cm, height_cm,
    weight_kg, volume_g, box_count,
    packing_memo, packing_type, inspection_status,
    item_description, item_price_usd, exchange_rate,
    hs_code, tax_id, fedex_id,
    carrier, ship_method, ship_date,
    tracking_number, est_shipping_fee,
    label_issued_at, pickup_requested_at,
    shipped_at, notified_at,
    ship_memo, created_at, updated_at
"""


async def _ensure_order_exists(db: AsyncSession, order_id: int, tenant_id: int) -> None:
    """受注の存在を確認する (Issue #766: schema prefix 明示)。"""
    orders_t = _t(db, tenant_id, "orders")
    res = await db.execute(
        text(f"SELECT id FROM {orders_t} WHERE id = :id"),
        {"id": order_id},
    )
    if not res.first():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="注文が見つかりません",
        )


async def _fetch_shipping_row(db: AsyncSession, order_id: int, tenant_id: int) -> dict | None:
    order_shipping_details_t = _t(db, tenant_id, "order_shipping_details")
    res = await db.execute(
        text(f"SELECT {_SELECT_COLS} FROM {order_shipping_details_t} WHERE order_id = :order_id"),
        {"order_id": order_id},
    )
    row = res.mappings().first()
    return dict(row) if row else None


async def _fetch_order_for_csv(db: AsyncSession, order_id: int, tenant_id: int) -> dict | None:
    """eLogi CSV 用に受注本体の必要カラム（order_number / created_at / notes）を取得する。"""
    orders_t = _t(db, tenant_id, "orders")
    res = await db.execute(
        text(f"""
            SELECT id, order_number, total_amount, currency, status,
                   notes, created_at, updated_at
            FROM {orders_t} WHERE id = :id
        """),
        {"id": order_id},
    )
    row = res.mappings().first()
    return dict(row) if row else None


@router.post(
    "/orders/{order_id}/shipping",
    response_model=OrderShippingDetailResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("orders.update"))],
)
async def create_order_shipping(
    order_id: int,
    data: OrderShippingDetailCreate,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """受注に発送情報を新規登録する。既存があれば 409。"""
    await _ensure_order_exists(db, order_id, tenant_id)

    existing = await _fetch_shipping_row(db, order_id, tenant_id)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="この受注の発送情報は既に登録されています",
        )

    payload = data.model_dump(mode="python")
    # ホワイトリスト経由で列を制限。明示指定された列のみ INSERT し、
    # それ以外は DB の DEFAULT NULL に任せる。
    insert_cols = ["tenant_id", "order_id"]
    insert_vals = [":tenant_id", ":order_id"]
    params: dict = {"tenant_id": tenant_id, "order_id": order_id}
    for col in INPUT_FIELDS:
        if col in payload:
            insert_cols.append(col)
            insert_vals.append(f":{col}")
            params[col] = payload[col]

    order_shipping_details_t = _t(db, tenant_id, "order_shipping_details")
    insert_sql = text(f"""
        INSERT INTO {order_shipping_details_t} ({', '.join(insert_cols)})
        VALUES ({', '.join(insert_vals)})
        RETURNING {_SELECT_COLS}
    """)
    result = await db.execute(insert_sql, params)
    row = result.mappings().first()

    await record_audit_log(
        db=db,
        tenant_id=tenant_id,
        user_id=current_user.id,
        action="create",
        table_name="order_shipping_details",
        record_id=row["id"],
        new_data=data.model_dump(mode="json", exclude_none=True),
    )
    await db.commit()

    return OrderShippingDetailResponse(**dict(row))


@router.get(
    "/orders/{order_id}/shipping",
    response_model=OrderShippingDetailResponse,
    dependencies=[Depends(require_permission("orders.view"))],
)
async def get_order_shipping(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """受注の発送情報を取得する。"""
    row = await _fetch_shipping_row(db, order_id, tenant_id)
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="発送情報が見つかりません",
        )
    return OrderShippingDetailResponse(**row)


@router.patch(
    "/orders/{order_id}/shipping",
    response_model=OrderShippingDetailResponse,
    dependencies=[Depends(require_permission("orders.update"))],
)
async def update_order_shipping(
    order_id: int,
    data: OrderShippingDetailUpdate,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """受注の発送情報を部分更新する（自動 updated_at）。"""
    old_row = await _fetch_shipping_row(db, order_id, tenant_id)
    if not old_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="発送情報が見つかりません",
        )

    update_data = data.model_dump(exclude_unset=True, mode="python")
    # ホワイトリスト経由でのみ列を許可（FK / id / tenant_id / *_at は変更不可）
    update_data = {k: v for k, v in update_data.items() if k in _UPDATABLE_COLUMNS}
    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="更新するフィールドを指定してください",
        )

    set_clauses = ", ".join(f"{k} = :{k}" for k in update_data)
    params = dict(update_data)
    params["order_id"] = order_id

    order_shipping_details_t = _t(db, tenant_id, "order_shipping_details")
    update_sql = text(f"""
        UPDATE {order_shipping_details_t}
        SET {set_clauses}, updated_at = NOW()
        WHERE order_id = :order_id
        RETURNING {_SELECT_COLS}
    """)
    result = await db.execute(update_sql, params)
    new_row = result.mappings().first()

    await record_audit_log(
        db=db,
        tenant_id=tenant_id,
        user_id=current_user.id,
        action="update",
        table_name="order_shipping_details",
        record_id=old_row["id"],
        old_data=old_row,
        new_data=update_data,
    )
    await db.commit()

    return OrderShippingDetailResponse(**dict(new_row))


@router.delete(
    "/orders/{order_id}/shipping",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("orders.update"))],
)
async def delete_order_shipping(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """受注の発送情報を削除する（受注本体は残る）。"""
    old_row = await _fetch_shipping_row(db, order_id, tenant_id)
    if not old_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="発送情報が見つかりません",
        )

    order_shipping_details_t = _t(db, tenant_id, "order_shipping_details")
    await db.execute(
        text(f"DELETE FROM {order_shipping_details_t} WHERE order_id = :order_id"),
        {"order_id": order_id},
    )

    await record_audit_log(
        db=db,
        tenant_id=tenant_id,
        user_id=current_user.id,
        action="delete",
        table_name="order_shipping_details",
        record_id=old_row["id"],
        old_data=old_row,
    )
    await db.commit()


# ---------------------------------------------------------------------------
# eLogi CSV エクスポート
# ---------------------------------------------------------------------------


def _build_csv_entry(order_row: dict, shipping_row: dict | None) -> dict:
    """eLogi adapter に渡す entry dict を組み立てる。

    本 Sprint では SKU / 画像URL / 商品タイトル / 数量 / USD単価 を持つ列が
    DB にまだ無いため空文字を入れる（eLogi 側で補完する運用）。
    """
    return {
        "order": order_row,
        "shipping": shipping_row or {},
        "extras": {
            # 本 Sprint で持っていない列は空のまま（adapter が空文字に丸める）
            "ship_staff": None,
            "order_type": None,
            "sku": None,
            "image_url": None,
            "product_title": None,
            "qty": None,
            "usd_price": shipping_row.get("item_price_usd") if shipping_row else None,
            "buyer_id": None,
            "timestamp": None,  # adapter 側で now() に丸める
        },
    }


@router.get(
    "/orders/{order_id}/shipping/elogi-csv",
    dependencies=[Depends(require_permission("orders.view"))],
)
async def get_order_shipping_elogi_csv(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """単一受注の eLogi CSV（ヘッダ 1 行 + データ 1 行）を text/csv で返す。"""
    order_row = await _fetch_order_for_csv(db, order_id, tenant_id)
    if not order_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="注文が見つかりません",
        )
    shipping_row = await _fetch_shipping_row(db, order_id, tenant_id)
    # 発送情報が無くても CSV 自体は出す（一部列が空で出るだけ）。
    # eLogi 側で「最小の order_number だけ」も取り込めるユースケースに対応。

    adapter = get_adapter("elogi")
    csv_text = adapter.to_csv_text([_build_csv_entry(order_row, shipping_row)])

    filename = f"elogi-{order_row['order_number']}.csv"
    return Response(
        content=csv_text,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.get(
    "/shipping/elogi-csv",
    dependencies=[Depends(require_permission("orders.view"))],
)
async def bulk_export_elogi_csv(
    order_ids: str = Query(
        ...,
        description="カンマ区切りの order_id（例: '1,2,3'）。最大 1000 件。",
        max_length=10000,
    ),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """複数受注を bulk export（CSV ヘッダ 1 行 + データ N 行）。

    order_ids はクエリ文字列でカンマ区切り（最大 1000 件）。順序はパラメータ順。
    存在しない id はスキップ（空行は出さない）。1 件も該当なければ 404。
    """
    # 入力パース。空要素 / 非整数は弾く。重複は除去。
    ids: list[int] = []
    seen: set[int] = set()
    for tok in order_ids.split(","):
        tok = tok.strip()
        if not tok:
            continue
        try:
            n = int(tok)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"order_ids に整数以外が含まれています: '{tok}'",
            )
        if n <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="order_ids は正の整数を指定してください",
            )
        if n in seen:
            continue
        seen.add(n)
        ids.append(n)

    if not ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="order_ids を 1 件以上指定してください",
        )
    if len(ids) > 1000:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="order_ids は最大 1000 件までです",
        )

    # 受注本体と発送情報を一括取得。順序はリクエスト指定順を維持。
    entries: list[dict] = []
    for oid in ids:
        order_row = await _fetch_order_for_csv(db, oid, tenant_id)
        if not order_row:
            continue  # 存在しない id はスキップ
        shipping_row = await _fetch_shipping_row(db, oid, tenant_id)
        entries.append(_build_csv_entry(order_row, shipping_row))

    if not entries:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="指定された注文が 1 件も見つかりません",
        )

    adapter = get_adapter("elogi")
    csv_text = adapter.to_csv_text(entries)

    filename = "elogi-bulk.csv"
    return Response(
        content=csv_text,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )
