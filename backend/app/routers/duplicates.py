from __future__ import annotations

"""
重複検知・マージAPI。

顧客/リードの重複候補を検出し、マスターレコードにマージする。

検出ルール:
  1. メールアドレス完全一致
  2. 電話番号正規化後一致
  3. 会社名＋名前のレーベンシュタイン類似度

変更履歴:
  2026-04-17: 初版作成（Phase 3）
"""

import re
from difflib import SequenceMatcher

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, get_current_tenant, require_permission
from app.database import get_db
from app.models import User
from app.services.audit import record_audit_log

router = APIRouter()


def _normalize_phone(phone: str | None) -> str:
    if not phone:
        return ""
    return re.sub(r"[^\d]", "", phone)


def _similarity(a: str | None, b: str | None) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


class DuplicateMatch(BaseModel):
    match_score: float
    match_reason: str
    record_a: dict
    record_b: dict


class DuplicatesResponse(BaseModel):
    duplicates: list[DuplicateMatch]


class MergeRequest(BaseModel):
    merge_ids: list[int] = Field(min_length=1)


class MergeResponse(BaseModel):
    master_id: int
    merged_count: int
    reassigned_deals: int
    reassigned_orders: int
    reassigned_quotes: int
    reassigned_invoices: int


@router.get(
    "/customers/duplicates",
    response_model=DuplicatesResponse,
    dependencies=[Depends(require_permission("customers.view"))],
)
async def find_customer_duplicates(
    confidence: float = Query(default=0.7, ge=0.5, le=1.0),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """顧客の重複候補を検出する"""
    result = await db.execute(
        text("SELECT id, name, email, phone, company FROM customers WHERE status != 'merged' ORDER BY id")
    )
    customers = [dict(row) for row in result.mappings().all()]
    duplicates: list[DuplicateMatch] = []

    for i, c1 in enumerate(customers):
        for c2 in customers[i + 1:]:
            score = 0.0
            reason = ""

            # Rule 1: メール完全一致
            if c1["email"] and c2["email"] and c1["email"].lower() == c2["email"].lower():
                score = 1.0
                reason = "メールアドレス完全一致"
            # Rule 2: 電話番号正規化一致
            elif c1["phone"] and c2["phone"]:
                p1, p2 = _normalize_phone(c1["phone"]), _normalize_phone(c2["phone"])
                if p1 and p2 and p1 == p2 and len(p1) >= 10:
                    score = 0.95
                    reason = "電話番号一致"
            # Rule 3: 会社名+名前の類似度
            if score == 0 and c1.get("company") and c2.get("company"):
                co_sim = _similarity(c1["company"], c2["company"])
                nm_sim = _similarity(c1["name"], c2["name"])
                if co_sim > 0.85 and nm_sim > 0.85:
                    score = (co_sim + nm_sim) / 2
                    reason = "会社名＋名前の類似"

            if score >= confidence:
                duplicates.append(DuplicateMatch(
                    match_score=round(score, 3),
                    match_reason=reason,
                    record_a=c1,
                    record_b=c2,
                ))

    return DuplicatesResponse(duplicates=duplicates)


@router.post(
    "/customers/{master_id}/merge",
    response_model=MergeResponse,
    dependencies=[Depends(require_permission("customers.update"))],
)
async def merge_customers(
    master_id: int,
    data: MergeRequest,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """重複顧客をマスターレコードにマージする"""
    # マスター存在確認
    master = await db.execute(text("SELECT id FROM customers WHERE id = :id"), {"id": master_id})
    if not master.first():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="マスター顧客が見つかりません")

    reassigned = {"deals": 0, "orders": 0, "quotes": 0, "invoices": 0}
    merged = 0

    for merge_id in data.merge_ids:
        if merge_id == master_id:
            continue
        check = await db.execute(text("SELECT id FROM customers WHERE id = :id"), {"id": merge_id})
        if not check.first():
            continue

        # 関連レコードを付け替え
        for table, col in [("deals", "customer_id"), ("orders", "customer_id"),
                           ("quotes", "customer_id"), ("invoices", "customer_id")]:
            r = await db.execute(
                text(f"UPDATE {table} SET {col} = :master WHERE {col} = :old RETURNING id"),
                {"master": master_id, "old": merge_id},
            )
            count = len(r.fetchall())
            reassigned[table] = reassigned.get(table, 0) + count

        # マージ元をmergedステータスに
        await db.execute(
            text("UPDATE customers SET status = 'merged', notes = COALESCE(notes, '') || :note, updated_at = NOW() WHERE id = :id"),
            {"id": merge_id, "note": f"\n[マージ済み → CT-{master_id:05d}]"},
        )
        merged += 1

    await record_audit_log(
        db=db, tenant_id=tenant_id, user_id=current_user.id,
        action="merge", table_name="customers", record_id=master_id,
        new_data={"merged_ids": data.merge_ids, "reassigned": reassigned},
    )
    await db.commit()

    return MergeResponse(
        master_id=master_id,
        merged_count=merged,
        reassigned_deals=reassigned["deals"],
        reassigned_orders=reassigned["orders"],
        reassigned_quotes=reassigned["quotes"],
        reassigned_invoices=reassigned["invoices"],
    )
