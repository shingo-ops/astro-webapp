from __future__ import annotations

"""
商品・在庫管理API（CRUD + 在庫チェック）。

変更履歴:
  2026-04-17: 初版作成（Phase 2）
  2026-04-28: Phase 1-C M-MVP（Q4/Q5/Q9 確定）
              - 11 列対応（jan_code, card_number, expansion_code, rarity, language,
                unit_price_usd, unit_price_eur, image_url, is_archived,
                archived_at, supplier_default_id）
              - is_archived フィルタ追加（default false）
              - DELETE で FK 参照あり時は 409 + アーカイブ推奨（Q9）
              - PATCH で is_archived=true → archived_at 自動設定
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from app.auth.dependencies import get_current_user, get_current_tenant, require_permission
from app.cache import invalidate_dashboard_cache
from app.database import get_db
from app.models import User
from app.schemas.product import (
    InventoryCheckResponse,
    ProductArchiveResponse,
    ProductCreate,
    ProductResponse,
    ProductUpdate,
)
from app.services.audit import record_audit_log

router = APIRouter()


def _is_postgresql(db: AsyncSession) -> bool:
    """db の dialect が PostgreSQL 系か判定する (Issue #565)。

    pytest は SQLite (aiosqlite) で実行されるため、schema prefix を入れると
    "no such table: tenant_NNN.products" で失敗する。本判定で SQLite 系を
    検出して prefix なしに倒す。
    """
    bind = db.get_bind() if hasattr(db, "get_bind") else None
    if bind is None:
        bind = getattr(db, "bind", None)
    name = getattr(getattr(bind, "dialect", None), "name", "") or ""
    return name.startswith("postgresql")


def _t(db: AsyncSession, tenant_id: int, name: str) -> str:
    """tenant スキーマ修飾テーブル参照を返す (Issue #565)。

    - PostgreSQL: `tenant_{id:03d}.{name}` (schema prefix 明示)
    - SQLite (pytest): `{name}` (schema 概念なし)

    AsyncSession の commit 後は新コネクションが払い出されて session-level
    の search_path が失われる可能性があるため、raw text() を使う箇所では
    schema prefix を明示するのが安全 (Issue #563 / #565)。
    """
    if _is_postgresql(db):
        safe_id = int(tenant_id)
        return f"tenant_{safe_id:03d}.{name}"
    return name


_PRODUCT_COLUMNS = """
    id, product_code, name_ja, name_en, category, mark,
    status, condition, unit_price, quantity, weight,
    notes, release_date, created_at, updated_at,
    jan_code, card_number, expansion_code, rarity, language,
    unit_price_usd, unit_price_eur, image_url,
    is_archived, archived_at, supplier_default_id
"""

_UPDATABLE_COLUMNS = {
    "name_ja", "name_en", "category", "mark", "status", "condition",
    "unit_price", "quantity", "weight", "notes", "release_date",
    # Phase 1-C M-MVP
    "jan_code", "card_number", "expansion_code", "rarity", "language",
    "unit_price_usd", "unit_price_eur", "image_url",
    "is_archived", "supplier_default_id",
}


@router.get(
    "/products",
    response_model=list[ProductResponse],
    dependencies=[Depends(require_permission("products.view"))],
)
async def list_products(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None, max_length=255),
    category: str | None = Query(default=None, max_length=100),
    status_filter: str | None = Query(default=None, alias="status"),
    archived: bool = Query(
        default=False,
        description="true で廃番(is_archived=true)も含む。default は非表示",
    ),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    offset = (page - 1) * per_page
    conditions = []
    params: dict = {"limit": per_page, "offset": offset}

    if search:
        conditions.append(
            "(name_ja ILIKE :search OR name_en ILIKE :search OR product_code ILIKE :search "
            "OR mark ILIKE :search OR jan_code ILIKE :search OR card_number ILIKE :search)"
        )
        params["search"] = f"%{search}%"
    if category:
        conditions.append("category = :category")
        params["category"] = category
    if status_filter:
        conditions.append("status = :status")
        params["status"] = status_filter
    if not archived:
        conditions.append("(is_archived = FALSE OR is_archived IS NULL)")

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    products_t = _t(db, tenant_id, "products")
    result = await db.execute(
        text(f"SELECT {_PRODUCT_COLUMNS} FROM {products_t} {where} ORDER BY updated_at DESC LIMIT :limit OFFSET :offset"),
        params,
    )
    return [ProductResponse(**row) for row in result.mappings().all()]


@router.get(
    "/products/{product_id}",
    response_model=ProductResponse,
    dependencies=[Depends(require_permission("products.view"))],
)
async def get_product(
    product_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    products_t = _t(db, tenant_id, "products")
    result = await db.execute(
        text(f"SELECT {_PRODUCT_COLUMNS} FROM {products_t} WHERE id = :id"),
        {"id": product_id},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="商品が見つかりません")
    return ProductResponse(**row)


@router.post(
    "/products",
    response_model=ProductResponse,
    status_code=201,
    dependencies=[Depends(require_permission("products.create"))],
)
async def create_product(
    data: ProductCreate,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    payload = data.model_dump()
    if payload.get("status") is not None:
        payload["status"] = payload["status"].value if hasattr(payload["status"], "value") else payload["status"]
    payload["tenant_id"] = tenant_id

    products_t = _t(db, tenant_id, "products")
    result = await db.execute(
        text(f"""
            INSERT INTO {products_t} (
                tenant_id, name_ja, name_en, category, mark,
                status, condition, unit_price, quantity, weight,
                notes, release_date,
                jan_code, card_number, expansion_code, rarity, language,
                unit_price_usd, unit_price_eur, image_url,
                is_archived, supplier_default_id
            ) VALUES (
                :tenant_id, :name_ja, :name_en, :category, :mark,
                :status, :condition, :unit_price, :quantity, :weight,
                :notes, :release_date,
                :jan_code, :card_number, :expansion_code, :rarity, :language,
                :unit_price_usd, :unit_price_eur, :image_url,
                :is_archived, :supplier_default_id
            ) RETURNING id
        """),
        payload,
    )
    new_id = result.scalar_one()

    await db.execute(
        text(f"UPDATE {products_t} SET product_code = :code WHERE id = :id"),
        {"code": f"PD-{new_id:05d}", "id": new_id},
    )

    fetched = await db.execute(
        text(f"SELECT {_PRODUCT_COLUMNS} FROM {products_t} WHERE id = :id"),
        {"id": new_id},
    )
    row = fetched.mappings().first()

    await record_audit_log(
        db=db, tenant_id=tenant_id, user_id=current_user.id,
        action="create", table_name="products", record_id=new_id,
        new_data=data.model_dump(exclude_none=True, mode="json"),
    )
    await db.commit()
    await invalidate_dashboard_cache(tenant_id)

    return ProductResponse(**row)


@router.patch(
    "/products/{product_id}",
    response_model=ProductResponse,
    dependencies=[Depends(require_permission("products.update"))],
)
async def update_product(
    product_id: int,
    data: ProductUpdate,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    products_t = _t(db, tenant_id, "products")
    old_result = await db.execute(
        text(f"SELECT {_PRODUCT_COLUMNS} FROM {products_t} WHERE id = :id"),
        {"id": product_id},
    )
    old_row = old_result.mappings().first()
    if not old_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="商品が見つかりません")

    update_data = data.model_dump(exclude_unset=True)
    update_data = {k: v for k, v in update_data.items() if k in _UPDATABLE_COLUMNS}
    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="更新するフィールドを指定してください")

    if "status" in update_data and update_data["status"] is not None:
        update_data["status"] = update_data["status"].value if hasattr(update_data["status"], "value") else update_data["status"]

    # is_archived=true への遷移時に archived_at を自動設定
    set_clauses = ", ".join(f"{k} = :{k}" for k in update_data)
    if update_data.get("is_archived") is True and not old_row.get("is_archived"):
        set_clauses += ", archived_at = NOW()"
    elif update_data.get("is_archived") is False and old_row.get("is_archived"):
        set_clauses += ", archived_at = NULL"

    update_data["id"] = product_id

    result = await db.execute(
        text(f"""
            UPDATE {products_t} SET {set_clauses}, updated_at = NOW()
            WHERE id = :id
            RETURNING {_PRODUCT_COLUMNS}
        """),
        update_data,
    )
    row = result.mappings().first()

    await record_audit_log(
        db=db, tenant_id=tenant_id, user_id=current_user.id,
        action="update", table_name="products", record_id=product_id,
        old_data=dict(old_row), new_data=update_data,
    )
    await db.commit()
    await invalidate_dashboard_cache(tenant_id)

    return ProductResponse(**row)


# 削除時に検査する下流テーブルの allowlist。
# 識別子は文字列リテラルのみ、tenant スキーマは search_path から解決される。
#
# TODO(M3 / docs/products_design.md §5-2): product_inventory を追加する。
#   - 在庫履歴があれば削除拒否がポリシー（履歴は監査証跡）
#   - product_inventory.product_id への参照を 'product_inventory' エントリで検出
# TODO(M4 / docs/products_design.md §5-3): product_supplier_mappings を追加する。
#   - 仕入先マッピングがあれば削除拒否（CASCADE は危険）
_DOWNSTREAM_TABLES_TO_CHECK = (
    "quote_items",
    "invoice_items",
    "purchase_order_items",
)


async def _check_product_references(
    db: AsyncSession, product_id: int, tenant_id: int
) -> list[str]:
    """指定 product_id を参照している下流テーブルのリストを返す。

    Phase 1-C M-MVP Q9: FK 参照ありの場合は物理削除せず 409 を返す。

    実装方針（PR #173 review Major 1 対応）:
        - テーブル存在チェックは to_regclass で先取り（schema 修飾名で存在確認）
        - 例外握り潰しを廃止、DB 例外は呼び出し側に伝播
        - 識別子はモジュール定数 _DOWNSTREAM_TABLES_TO_CHECK の allowlist のみ使用

    Issue #565: search_path 依存をやめて schema prefix を明示する。
    SQLite (pytest) は to_regclass 未対応のため prefix なしの dialect 分岐に倒す。
    """
    blocking: list[str] = []
    for table in _DOWNSTREAM_TABLES_TO_CHECK:
        qualified = _t(db, tenant_id, table)
        # テーブル存在確認。未投入テナントは無音 SKIP（dangling FK にはならない）
        if _is_postgresql(db):
            exists_result = await db.execute(
                text("SELECT to_regclass(:qname) IS NOT NULL"),
                {"qname": qualified},
            )
            if not exists_result.scalar():
                continue
        else:
            # SQLite: sqlite_master で確認（schema 概念なしなので table 名のみ）
            exists_result = await db.execute(
                text("SELECT EXISTS(SELECT 1 FROM sqlite_master WHERE type='table' AND name = :n)"),
                {"n": table},
            )
            if not exists_result.scalar():
                continue

        # 識別子は allowlist 確定済 + tenant schema 修飾、:id だけバインド
        result = await db.execute(
            text(f"SELECT EXISTS(SELECT 1 FROM {qualified} WHERE product_id = :id)"),
            {"id": product_id},
        )
        if result.scalar():
            blocking.append(table)
    return blocking


@router.delete(
    "/products/{product_id}",
    status_code=204,
    dependencies=[Depends(require_permission("products.delete"))],
    responses={
        409: {
            "model": ProductArchiveResponse,
            "description": "下流テーブルから参照されているため物理削除不可。is_archived=true でアーカイブを推奨",
        },
    },
)
async def delete_product(
    product_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """商品を物理削除する。

    Q9（2026-04-28 確定）: FK 参照あり時は 409 を返し、is_archived=true の
    アーカイブ運用に誘導する。参照なしのときだけ物理削除する。
    """
    products_t = _t(db, tenant_id, "products")
    old_result = await db.execute(
        text(f"SELECT {_PRODUCT_COLUMNS} FROM {products_t} WHERE id = :id"),
        {"id": product_id},
    )
    old_row = old_result.mappings().first()
    if not old_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="商品が見つかりません")

    blocking = await _check_product_references(db, product_id, tenant_id)
    if blocking:
        # PR #173 review Minor 6 follow-up: 失敗 DELETE 試行も audit_log に残す。
        # 「誰がいつ削除を試みたが下流参照で拒否された」を運用側で追えるようにする。
        await record_audit_log(
            db=db, tenant_id=tenant_id, user_id=current_user.id,
            action="delete_blocked", table_name="products", record_id=product_id,
            old_data=dict(old_row),
            new_data={"blocking_references": blocking, "result": "409_conflict"},
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "id": product_id,
                "name_ja": old_row["name_ja"],
                "is_archived": bool(old_row.get("is_archived")),
                "blocking_references": blocking,
                "detail": (
                    f"以下のテーブルから参照されているため物理削除できません: "
                    f"{', '.join(blocking)}。"
                    f"is_archived=true で論理削除（アーカイブ）を推奨します"
                ),
            },
        )

    # PR #173 review Major 2 対応: _check_product_references の網羅漏れ
    # （M3/M4 で増える FK や allowlist 外の下流参照）に備え、IntegrityError を
    # キャッチして同じ 409 構造で返す + rollback で aborted transaction を
    # 残さない。
    try:
        await db.execute(text(f"DELETE FROM {products_t} WHERE id = :id"), {"id": product_id})
        await record_audit_log(
            db=db, tenant_id=tenant_id, user_id=current_user.id,
            action="delete", table_name="products", record_id=product_id,
            old_data=dict(old_row),
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        logger.warning(
            "delete_product IntegrityError fallback: tenant=%d product=%d err=%s",
            tenant_id, product_id, exc.orig,
        )
        # IntegrityError fallback も監査ログに残す（参照先未特定で拒否された記録）
        try:
            await record_audit_log(
                db=db, tenant_id=tenant_id, user_id=current_user.id,
                action="delete_blocked", table_name="products", record_id=product_id,
                old_data=dict(old_row),
                new_data={"blocking_references": ["unknown"], "result": "409_integrity_error"},
            )
            await db.commit()
        except Exception:
            # audit log 自体の失敗で 500 を返さない（ベストエフォート）
            await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "id": product_id,
                "name_ja": old_row["name_ja"],
                "is_archived": bool(old_row.get("is_archived")),
                # _check_product_references で検出できなかった参照
                "blocking_references": ["unknown"],
                "detail": (
                    "下流参照があるため物理削除できません（参照先未特定）。"
                    "is_archived=true で論理削除（アーカイブ）を推奨します"
                ),
            },
        )

    await invalidate_dashboard_cache(tenant_id)


@router.get(
    "/products/{product_id}/check-inventory",
    response_model=InventoryCheckResponse,
    dependencies=[Depends(require_permission("products.view"))],
)
async def check_inventory(
    product_id: int,
    quantity: int = Query(ge=1),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """指定商品の在庫が要求数量を満たすか確認する"""
    products_t = _t(db, tenant_id, "products")
    result = await db.execute(
        text(f"SELECT id, name_ja, quantity FROM {products_t} WHERE id = :id"),
        {"id": product_id},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="商品が見つかりません")

    return InventoryCheckResponse(
        product_id=row["id"],
        product_name=row["name_ja"],
        available=row["quantity"] >= quantity,
        current_quantity=row["quantity"],
        requested_quantity=quantity,
    )
