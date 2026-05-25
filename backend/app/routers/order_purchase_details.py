from __future__ import annotations

"""
受注ごとの仕入情報 API（order_purchase_details）。

ADR-021 Phase 4 / Sprint 4: 仕入情報 MVP
  - POST   /orders/{order_id}/purchase — 新規作成（既存があれば 409）
  - GET    /orders/{order_id}/purchase — 取得（不存在 404）
  - PATCH  /orders/{order_id}/purchase — 部分更新（自動 updated_at）
  - DELETE /orders/{order_id}/purchase — 削除（CASCADE 任せでも済むが明示削除用）
  - PATCH  /orders/{order_id}/purchase/status — 確定ショートカット
  - GET    /purchase/by-supplier?supplier_name=...&page=&per_page= — 仕入元別の取引履歴

権限・テナント:
  - require_permission("orders.view") for GET 系
  - require_permission("orders.update") for write 系
  - Depends(get_current_tenant) で tenant スキーマを切替（既存 orders と同じ経路）

設計:
  既存 purchase_orders テーブル（migration 007）とは別系統。本ルータが扱うのは
  受注 1 件 = 仕入情報 1 件の OrderFlow Manager 互換テーブル（migration 049）。
  仕入元マスタとの連携・ADR-014 在庫管理連携は本 Sprint スコープ外。

変更履歴:
  2026-05-11: 初版（ADR-021 Phase 4 / Sprint 4）
"""

import re

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import (
    get_current_user,
    get_current_tenant,
    require_permission,
)
from app.database import get_db
from app.models import User
from app.schemas.order_purchase_detail import (
    INPUT_FIELDS,
    OrderPurchaseDetailCreate,
    OrderPurchaseDetailResponse,
    OrderPurchaseDetailStatusUpdate,
    OrderPurchaseDetailUpdate,
    PurchaseBySupplierItem,
    PurchaseBySupplierResponse,
    compute_derived,
)
from app.services.audit import record_audit_log

router = APIRouter()


def _is_postgresql(db: AsyncSession) -> bool:
    """db の dialect が PostgreSQL 系か判定する (Issue #766)。

    pytest は SQLite (aiosqlite) で実行されるため、schema prefix を入れると
    "no such table: tenant_NNN.order_purchase_details" で失敗する。本判定で
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
    purchase_staff, purchase_date, transaction_no,
    supplier_name, supplier_url,
    purchase_amount, purchase_quantity,
    purchase_total, purchase_shipping,
    carrier_name, waybill_no,
    purchase_note, purchase_status,
    created_at, updated_at
"""


# 仕入元検索キーワードのサニタイズ用パターン（orders.py と同じ方針）。
# psycopg のパラメータ化バインディングで SQL injection は防げるが、
# ILIKE のメタ文字（% と _）は意図しない 0/全件マッチを生むのでエスケープする。
_LIKE_ESCAPE_RE = re.compile(r"([\\%_])")


def _sanitize_search(keyword: str | None) -> str | None:
    """supplier_name 検索キーワードを ILIKE 用にサニタイズする。"""
    if not keyword:
        return None
    cleaned = keyword.strip()
    if not cleaned:
        return None
    cleaned = "".join(ch for ch in cleaned if ch.isprintable() or ch == " ")
    if not cleaned:
        return None
    return _LIKE_ESCAPE_RE.sub(r"\\\1", cleaned)


# 仕入元別履歴のソート許可カラム（SQL injection 対策のホワイトリスト）。
_SUPPLIER_SORTABLE_COLUMNS = {
    "created_at",
    "updated_at",
    "purchase_date",
    "purchase_total",
    "supplier_name",
}


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


async def _fetch_purchase_row(db: AsyncSession, order_id: int, tenant_id: int) -> dict | None:
    order_purchase_details_t = _t(db, tenant_id, "order_purchase_details")
    res = await db.execute(
        text(f"SELECT {_SELECT_COLS} FROM {order_purchase_details_t} WHERE order_id = :order_id"),
        {"order_id": order_id},
    )
    row = res.mappings().first()
    return dict(row) if row else None


def _build_response(row: dict) -> OrderPurchaseDetailResponse:
    """DB row から導出フィールドを計算してレスポンスを組み立てる。"""
    enriched = dict(row)
    enriched.update(compute_derived(enriched))
    return OrderPurchaseDetailResponse(**enriched)


@router.post(
    "/orders/{order_id}/purchase",
    response_model=OrderPurchaseDetailResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("orders.update"))],
)
async def create_order_purchase(
    order_id: int,
    data: OrderPurchaseDetailCreate,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """受注に仕入情報を新規登録する。既存があれば 409。"""
    await _ensure_order_exists(db, order_id, tenant_id)

    existing = await _fetch_purchase_row(db, order_id, tenant_id)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="この受注の仕入情報は既に登録されています",
        )

    payload = data.model_dump(mode="python")
    # ホワイトリスト経由で列を制限。明示指定された列のみ INSERT し、
    # それ以外は DB の DEFAULT NULL / 0 / "" に任せる。
    insert_cols = ["tenant_id", "order_id"]
    insert_vals = [":tenant_id", ":order_id"]
    params: dict = {"tenant_id": tenant_id, "order_id": order_id}
    for col in INPUT_FIELDS:
        if col in payload:
            value = payload[col]
            # purchase_status の None は DB DEFAULT '' に丸める（NOT NULL 制約のため）
            if col == "purchase_status" and value is None:
                continue
            insert_cols.append(col)
            insert_vals.append(f":{col}")
            params[col] = value

    order_purchase_details_t = _t(db, tenant_id, "order_purchase_details")
    insert_sql = text(f"""
        INSERT INTO {order_purchase_details_t} ({', '.join(insert_cols)})
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
        table_name="order_purchase_details",
        record_id=row["id"],
        new_data=data.model_dump(mode="json", exclude_none=True),
    )
    await db.commit()

    return _build_response(dict(row))


@router.get(
    "/orders/{order_id}/purchase",
    response_model=OrderPurchaseDetailResponse,
    dependencies=[Depends(require_permission("orders.view"))],
)
async def get_order_purchase(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """受注の仕入情報を取得する。"""
    row = await _fetch_purchase_row(db, order_id, tenant_id)
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="仕入情報が見つかりません",
        )
    return _build_response(row)


@router.patch(
    "/orders/{order_id}/purchase",
    response_model=OrderPurchaseDetailResponse,
    dependencies=[Depends(require_permission("orders.update"))],
)
async def update_order_purchase(
    order_id: int,
    data: OrderPurchaseDetailUpdate,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """受注の仕入情報を部分更新する（自動 updated_at）。"""
    old_row = await _fetch_purchase_row(db, order_id, tenant_id)
    if not old_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="仕入情報が見つかりません",
        )

    update_data = data.model_dump(exclude_unset=True, mode="python")
    # ホワイトリスト経由でのみ列を許可（FK / id / tenant_id / *_at は変更不可）
    update_data = {k: v for k, v in update_data.items() if k in _UPDATABLE_COLUMNS}
    # purchase_status は NOT NULL 制約があるため、None を渡された場合は変更しない。
    if "purchase_status" in update_data and update_data["purchase_status"] is None:
        update_data.pop("purchase_status")
    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="更新するフィールドを指定してください",
        )

    set_clauses = ", ".join(f"{k} = :{k}" for k in update_data)
    params = dict(update_data)
    params["order_id"] = order_id

    order_purchase_details_t = _t(db, tenant_id, "order_purchase_details")
    update_sql = text(f"""
        UPDATE {order_purchase_details_t}
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
        table_name="order_purchase_details",
        record_id=old_row["id"],
        old_data=old_row,
        new_data=update_data,
    )
    await db.commit()

    return _build_response(dict(new_row))


@router.delete(
    "/orders/{order_id}/purchase",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("orders.update"))],
)
async def delete_order_purchase(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """受注の仕入情報を削除する（受注本体は残る）。"""
    old_row = await _fetch_purchase_row(db, order_id, tenant_id)
    if not old_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="仕入情報が見つかりません",
        )

    order_purchase_details_t = _t(db, tenant_id, "order_purchase_details")
    await db.execute(
        text(f"DELETE FROM {order_purchase_details_t} WHERE order_id = :order_id"),
        {"order_id": order_id},
    )

    await record_audit_log(
        db=db,
        tenant_id=tenant_id,
        user_id=current_user.id,
        action="delete",
        table_name="order_purchase_details",
        record_id=old_row["id"],
        old_data=old_row,
    )
    await db.commit()


@router.patch(
    "/orders/{order_id}/purchase/status",
    response_model=OrderPurchaseDetailResponse,
    dependencies=[Depends(require_permission("orders.update"))],
)
async def update_order_purchase_status(
    order_id: int,
    data: OrderPurchaseDetailStatusUpdate | None = None,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """確定ショートカット。

    body 省略時は `purchase_status='confirmed'` に切り替える（最頻ユースケース）。
    body で `status: ""` を渡された場合は確認中に戻す（取り消し用途）。
    """
    old_row = await _fetch_purchase_row(db, order_id, tenant_id)
    if not old_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="仕入情報が見つかりません",
        )

    new_status: str = "confirmed"
    if data is not None and data.status is not None:
        new_status = data.status

    order_purchase_details_t = _t(db, tenant_id, "order_purchase_details")
    update_sql = text(f"""
        UPDATE {order_purchase_details_t}
        SET purchase_status = :status, updated_at = NOW()
        WHERE order_id = :order_id
        RETURNING {_SELECT_COLS}
    """)
    result = await db.execute(
        update_sql, {"status": new_status, "order_id": order_id}
    )
    new_row = result.mappings().first()

    await record_audit_log(
        db=db,
        tenant_id=tenant_id,
        user_id=current_user.id,
        action="update",
        table_name="order_purchase_details",
        record_id=old_row["id"],
        old_data={"purchase_status": old_row.get("purchase_status")},
        new_data={"purchase_status": new_status},
    )
    await db.commit()

    return _build_response(dict(new_row))


@router.get(
    "/purchase/by-supplier",
    response_model=PurchaseBySupplierResponse,
    dependencies=[Depends(require_permission("orders.view"))],
)
async def list_purchase_by_supplier(
    supplier_name: str | None = Query(
        default=None,
        description="仕入元名の partial match キーワード（テナント内）",
    ),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    sort_by: str = Query(
        default="created_at",
        description="ソート対象。created_at / updated_at / purchase_date / purchase_total / supplier_name",
    ),
    sort_order: str = Query(
        default="desc",
        description="asc / desc",
    ),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """仕入元別の取引履歴を一覧取得する（テナント単位 / partial match / ページング）。

    ADR-021 第 2 節 AC-002 の最小実装。orders テーブルに LEFT JOIN して
    order_number を返し、画面側の「仕入元 → 過去の受注」遷移に使う。
    """
    if sort_by not in _SUPPLIER_SORTABLE_COLUMNS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"sort_by は {sorted(_SUPPLIER_SORTABLE_COLUMNS)} のいずれかを指定してください",
        )
    sort_order_lc = (sort_order or "desc").lower()
    if sort_order_lc not in ("asc", "desc"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="sort_order は asc / desc を指定してください",
        )
    sort_dir = "DESC" if sort_order_lc == "desc" else "ASC"

    sanitized = _sanitize_search(supplier_name)

    where_parts: list[str] = []
    params: dict = {}
    if sanitized:
        where_parts.append("p.supplier_name ILIKE :supplier_search ESCAPE '\\'")
        params["supplier_search"] = f"%{sanitized}%"

    where_sql = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

    # COUNT は同じ where を使う（JOIN なし）
    order_purchase_details_t = _t(db, tenant_id, "order_purchase_details")
    orders_t = _t(db, tenant_id, "orders")
    count_sql = text(f"""
        SELECT COUNT(*) AS total
        FROM {order_purchase_details_t} p
        {where_sql}
    """)
    cnt_res = await db.execute(count_sql, params)
    total_row = cnt_res.mappings().first()
    total = int(total_row["total"]) if total_row and total_row["total"] is not None else 0

    offset = (page - 1) * per_page
    list_params = dict(params)
    list_params["limit"] = per_page
    list_params["offset"] = offset

    list_sql = text(f"""
        SELECT
            p.id, p.order_id,
            o.order_number AS order_number,
            p.purchase_date, p.transaction_no,
            p.supplier_name, p.supplier_url,
            p.purchase_amount, p.purchase_quantity,
            p.purchase_total, p.purchase_shipping,
            p.purchase_status,
            p.created_at, p.updated_at
        FROM {order_purchase_details_t} p
        LEFT JOIN {orders_t} o ON o.id = p.order_id
        {where_sql}
        ORDER BY p.{sort_by} {sort_dir}, p.id DESC
        LIMIT :limit OFFSET :offset
    """)
    res = await db.execute(list_sql, list_params)
    rows = [dict(r) for r in res.mappings().all()]

    items = [PurchaseBySupplierItem(**r) for r in rows]
    return PurchaseBySupplierResponse(
        items=items,
        total=total,
        page=page,
        per_page=per_page,
        supplier_name=supplier_name,
    )
