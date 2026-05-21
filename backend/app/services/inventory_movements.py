"""inventory_movements 反映ロジック（Sprint 6 F6 承認経路）。

spec.md v1.1 F6 AC6.1 / AC6.6:
  - approve 操作で `public.inventory_movements` に append-only INSERT +
    `public.products.stock_quantity += delta_qty` UPDATE を **同一トランザクション**
    で実行
  - 不変条件: `SUM(delta_qty WHERE product_id=X) == products.stock_quantity`
  - tenant_id は `public.products.tenant_id` を継承（NULL の場合は中央在庫扱い、
    inventory_movements.tenant_id = 0 = sentinel で記録、warning log 出力）
  - source_type='discord_inbound_review' で固定（migration 062 の CHECK 列挙に同梱済）

呼び出し元: backend/app/routers/parse_review.py の approve エンドポイント
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# AC6.6 不変条件を満たすため、tenant_id NULL の products は中央在庫扱い (sentinel 0)。
# inventory_movements.tenant_id は NOT NULL なので、NULL のままでは INSERT 不可。
_CENTRAL_TENANT_SENTINEL = 0


@dataclass
class MovementResult:
    movement_id: int
    product_id: int
    delta_qty: int
    before_qty: int
    after_qty: int


@dataclass
class ApplyResult:
    movements: list[MovementResult]
    skipped: int


class InventoryApplyError(Exception):
    """承認反映の業務エラー（product 不存在、delta=0 等）。"""


async def apply_inbound_items(
    db: AsyncSession,
    *,
    inbound_id: int,
    items: list[dict],
    operator_id: int,
    supplier_id: int | None,
) -> ApplyResult:
    """承認対象 items を inventory_movements + products へ反映する。

    呼び出し側はこの関数の前に楽観ロック (UPDATE ... WHERE version) を
    実行し、すでに行ロックを取得していること。

    Args:
        db: 同一トランザクションで走る AsyncSession。**この関数内では commit しない**。
            呼び出し側 (parse_review.py) が approve 全体の整合性を担保するために
            最後にまとめて commit する。
        inbound_id: source_id として inventory_movements に記録。
        items: ReviewItemInput.dict() のリスト。
            product_id=None の行は skip カウントのみインクリメント、movements 作成しない。
        operator_id: 承認した中央 admin の public.users.id。
        supplier_id: source supplier。movements.supplier_id に転記、トレース用。

    Returns:
        ApplyResult: 作成した movements 一覧 + skip 件数。
    """
    movements: list[MovementResult] = []
    skipped = 0

    for item in items:
        product_id = item.get("product_id")
        delta_qty = int(item.get("delta_qty") or 0)
        notes = item.get("notes")

        if product_id is None:
            skipped += 1
            continue
        if delta_qty == 0:
            # 0 動 → DB 反映なし。AC6.1 の「delta_qty だけ増減」と矛盾しない範囲で skip。
            skipped += 1
            continue

        # 1. products 行を SELECT FOR UPDATE で取得（同時更新ガード）
        prod_row = (
            (
                await db.execute(
                    text(
                        "SELECT id, tenant_id, stock_quantity "
                        "FROM public.products WHERE id = :pid FOR UPDATE"
                    ),
                    {"pid": product_id},
                )
            )
            .mappings()
            .first()
        )
        if prod_row is None:
            raise InventoryApplyError(
                f"product_id={product_id} が見つかりません (inbound_id={inbound_id})"
            )

        before_qty = int(prod_row["stock_quantity"])
        after_qty = before_qty + delta_qty
        tenant_id_for_movement = prod_row["tenant_id"]
        if tenant_id_for_movement is None:
            tenant_id_for_movement = _CENTRAL_TENANT_SENTINEL
            logger.warning(
                "products.tenant_id IS NULL for product_id=%s; "
                "recording inventory_movements with tenant_id=%s (central marketplace sentinel)",
                product_id,
                _CENTRAL_TENANT_SENTINEL,
            )

        # 2. inventory_movements に append-only INSERT。
        #    migration 062 の BEFORE INSERT trigger が
        #    after_qty == before_qty + delta_qty を assert する。
        mov_row = (
            await db.execute(
                text(
                    """
                INSERT INTO public.inventory_movements
                    (tenant_id, product_id, delta_qty, before_qty, after_qty,
                     source_type, source_id, supplier_id, operator_id, occurred_at, notes)
                VALUES
                    (:tenant_id, :product_id, :delta_qty, :before_qty, :after_qty,
                     'discord_inbound_review', :source_id, :supplier_id, :operator_id,
                     NOW(), :notes)
                RETURNING id
                """
                ),
                {
                    "tenant_id": tenant_id_for_movement,
                    "product_id": product_id,
                    "delta_qty": delta_qty,
                    "before_qty": before_qty,
                    "after_qty": after_qty,
                    "source_id": inbound_id,
                    "supplier_id": supplier_id,
                    "operator_id": operator_id,
                    "notes": notes,
                },
            )
        ).first()
        if mov_row is None:
            raise InventoryApplyError(
                f"inventory_movements INSERT failed for product_id={product_id}"
            )
        movement_id = int(mov_row[0])

        # 3. products.stock_quantity を更新
        await db.execute(
            text(
                "UPDATE public.products SET stock_quantity = :new_qty WHERE id = :pid"
            ),
            {"new_qty": after_qty, "pid": product_id},
        )

        movements.append(
            MovementResult(
                movement_id=movement_id,
                product_id=product_id,
                delta_qty=delta_qty,
                before_qty=before_qty,
                after_qty=after_qty,
            )
        )

    return ApplyResult(movements=movements, skipped=skipped)


async def verify_invariant_for_product(
    db: AsyncSession, *, product_id: int
) -> tuple[int, int]:
    """AC6.6 不変条件検証ヘルパ（テスト用）。

    Returns:
        (stock_quantity, SUM(delta_qty)) を返す。呼び出し側で
        `assert a == b` するかロギングする。
    """
    row = (
        (
            await db.execute(
                text(
                    "SELECT COALESCE(p.stock_quantity, 0) AS sq, "
                    "       COALESCE((SELECT SUM(delta_qty) "
                    "                   FROM public.inventory_movements "
                    "                  WHERE product_id = p.id), 0) AS dsum "
                    "  FROM public.products p WHERE p.id = :pid"
                ),
                {"pid": product_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise InventoryApplyError(f"product_id={product_id} が見つかりません")
    return int(row["sq"]), int(row["dsum"])


__all__ = [
    "ApplyResult",
    "InventoryApplyError",
    "MovementResult",
    "apply_inbound_items",
    "verify_invariant_for_product",
]
