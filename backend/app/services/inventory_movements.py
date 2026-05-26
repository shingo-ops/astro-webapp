"""inventory_movements + inventory 反映ロジック（Sprint 6 F6 + Sprint 9 F9 + Sprint 11 F11）。

spec.md v1.1 F6 AC6.1 / AC6.6:
  - approve 操作で `public.inventory_movements` に append-only INSERT +
    `public.products.stock_quantity += delta_qty` UPDATE を **同一トランザクション**
    で実行
  - 不変条件: `SUM(delta_qty WHERE product_id=X) == products.stock_quantity`
    （Phase B/C のみ。Phase A では SUM(delta_qty) は記録、stock_quantity は GS 真値）
  - tenant_id は `public.products.tenant_id` を継承（NULL の場合は中央在庫扱い、
    inventory_movements.tenant_id = 0 = sentinel で記録、warning log 出力）
  - source_type='discord_inbound_review' で固定（migration 062 の CHECK 列挙に同梱済）

spec.md v1.3 F9 AC9.1 (Sprint 9 revised、v1.2 Phase A 並走方針を撤回):
  - Phase A (緊急戻し時のみ): inventory_movements 記録、stock_quantity は更新しない。
    ApplyResult.stock_quantity_skipped=True を返し呼出側で warning toast 表示。
  - Phase B/C (標準運用): 従来挙動 (stock_quantity も更新) + F11 inventory UPSERT。

spec.md v1.3 F11 AC11.3 (Sprint 11、本 module で実装):
  - Phase B/C + supplier_id 指定 + items.condition 指定 の場合のみ、
    `public.inventory` を UPSERT (UNIQUE: supplier_id × product_id × condition)。
  - items.condition が無い場合は UPSERT skip (backward compat、既存テスト不変)。
  - items.quantity_offered / items.unit_price も任意で受け取り反映。

呼び出し元: backend/app/routers/parse_review.py の approve エンドポイント
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.phase_gate import Phase, get_phase

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
    # Sprint 9 / F9 v1.2: Phase A 並走時の状態を呼出側 (parse_review.py) に伝える
    stock_quantity_skipped: bool = False
    phase: Phase = "B"
    # Phase A では products.stock_quantity の更新を skip した行数を記録
    stock_updates_skipped: int = 0
    # 同 sprint で stock を実際に更新した件数（Phase B/C のみ加算）
    stock_updates_applied: int = 0


class InventoryApplyError(Exception):
    """承認反映の業務エラー（product 不存在、delta=0 等）。"""


async def apply_inbound_items(
    db: AsyncSession,
    *,
    inbound_id: int,
    items: list[dict],
    operator_id: int,
    supplier_id: int | None,
    phase: Phase | None = None,
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
        phase: Sprint 9 / F9 v1.2 — 明示的に Phase を渡すと tenant_settings 参照を
            スキップする (テスト用 / migration 070 未適用環境用)。None の場合は
            products.tenant_id 由来で `phase_gate.get_phase` を呼ぶ。

    Returns:
        ApplyResult: 作成した movements 一覧 + skip 件数 +
            Phase A 並走時の stock_quantity_skipped フラグ。
    """
    movements: list[MovementResult] = []
    skipped = 0
    stock_updates_applied = 0
    stock_updates_skipped = 0
    # Phase 決定は products.tenant_id ごとに行うが、ループ初回で一度だけ取得し
    # 同一 inbound 内では tenant が混在しない前提で 1 回判定する。
    # 明示 phase が渡されたらそれを尊重 (テスト/旧来動作用)。
    resolved_phase: Phase | None = phase

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
        # Phase A: after_qty は記録上 before_qty + delta_qty とするが、
        #   実際の products.stock_quantity は更新しない（GS が真値）。
        # Phase B/C: after_qty = before_qty + delta_qty で products も更新。
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

        # Sprint 9 / F9 v1.2: Phase 判定（明示 phase 引数 > tenant_settings 参照）。
        # tenant_id_for_movement=0 (中央 sentinel) の場合は tenant_settings 行が
        # 無いはずなので get_phase は 'A' fallback を返す（warning ログ付き）。
        if resolved_phase is None:
            try:
                resolved_phase = await get_phase(int(tenant_id_for_movement), db)
            except Exception as exc:  # noqa: BLE001
                # tenant_settings テーブルが migration 070 未適用環境では
                # 旧来挙動 (Phase B 相当) で fallback して既存テストを壊さない。
                logger.warning(
                    "phase_gate.get_phase 失敗 (tenant_id=%s, err=%s)。Phase='B' で fallback。",
                    tenant_id_for_movement,
                    exc,
                )
                resolved_phase = "B"

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

        # 3. products.stock_quantity を更新（Phase B/C のみ。Phase A は skip）
        if resolved_phase == "A":
            stock_updates_skipped += 1
            logger.info(
                "Phase A: products.stock_quantity 更新を skip "
                "(product_id=%s, delta_qty=%s, recorded in inventory_movements only)",
                product_id,
                delta_qty,
            )
        else:
            await db.execute(
                text(
                    "UPDATE public.products SET stock_quantity = :new_qty WHERE id = :pid"
                ),
                {"new_qty": after_qty, "pid": product_id},
            )
            stock_updates_applied += 1

            # 4. (F11 AC11.3) public.inventory に UPSERT — 仕入元 × 商品 × 状態 の現在オファー
            #    条件: Phase B/C + supplier_id 指定 + items.condition 指定
            #    backward compat: items.condition が無い場合は UPSERT skip (既存テスト不変)
            condition_raw = item.get("condition")
            if supplier_id is not None and condition_raw:
                offered_qty = item.get("quantity_offered")
                if offered_qty is None:
                    # 後方互換: quantity_offered 未指定なら after_qty で代替
                    offered_qty = after_qty
                offered_price = int(item.get("unit_price") or 0)
                await db.execute(
                    text(
                        """
                        INSERT INTO public.inventory
                            (supplier_id, product_id, condition, quantity, unit_price,
                             status, source)
                        VALUES (:sid, :pid, :cond, :qty, :up, 'in_stock', 'f6_approved')
                        ON CONFLICT (supplier_id, product_id, condition) DO UPDATE SET
                            quantity = EXCLUDED.quantity,
                            unit_price = EXCLUDED.unit_price,
                            status = EXCLUDED.status,
                            source = 'f6_approved',
                            offered_at = NOW(),
                            updated_at = NOW()
                        """
                    ),
                    {
                        "sid": supplier_id,
                        "pid": product_id,
                        "cond": str(condition_raw),
                        "qty": int(offered_qty),
                        "up": offered_price,
                    },
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

    final_phase: Phase = resolved_phase or "B"
    return ApplyResult(
        movements=movements,
        skipped=skipped,
        stock_quantity_skipped=(final_phase == "A" and stock_updates_skipped > 0),
        phase=final_phase,
        stock_updates_applied=stock_updates_applied,
        stock_updates_skipped=stock_updates_skipped,
    )


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
