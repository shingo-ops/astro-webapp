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
  2026-04-27: Phase 1-B-2 Step 5d — merge_customers の関連レコード付け替えを
    customer_id ベースから company_id ベースに切替。
    （旧 customer_id 列は Step 5d 以降コードから書き込まれず、PR β migration 035
    で物理削除予定。customers/duplicates 検出ロジック自体は customers テーブル
    本体を残している関係で従来通り customers ベースのままとする。）
  2026-04-27 (round 1 review fix): Reviewer Major 1 — `master_id` / `merge_id` を
    `customers.id` のまま `UPDATE deals SET company_id = :customer_id` していた
    データ破壊バグを発見。新 B2B モデル (companies) ベースで再実装するまで
    一時的に 501 Not Implemented で無効化する。
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
    """顧客の重複候補を検出する（新スキーマ：customer_addresses 副テーブル対応）"""
    # 各顧客について、表示名・メール・電話を billing / delivery の両方から集約
    result = await db.execute(
        text("""
            SELECT
                c.id,
                COALESCE(c.billing_display_name, c.company_name) AS name,
                c.company_name AS company,
                ba.email AS billing_email,
                da.email AS delivery_email,
                ba.telephone AS billing_phone,
                da.telephone AS delivery_phone,
                c.status
            FROM customers c
            LEFT JOIN customer_addresses ba ON ba.customer_id = c.id AND ba.address_type = 'billing'
            LEFT JOIN customer_addresses da ON da.customer_id = c.id AND da.address_type = 'delivery'
            WHERE c.status != 'archived'
            ORDER BY c.id
        """)
    )
    customers = [dict(row) for row in result.mappings().all()]
    duplicates: list[DuplicateMatch] = []

    def _first_non_empty(*vals: str | None) -> str | None:
        for v in vals:
            if v:
                return v
        return None

    for i, c1 in enumerate(customers):
        for c2 in customers[i + 1:]:
            score = 0.0
            reason = ""
            c1_email = _first_non_empty(c1.get("billing_email"), c1.get("delivery_email"))
            c2_email = _first_non_empty(c2.get("billing_email"), c2.get("delivery_email"))
            c1_phone = _first_non_empty(c1.get("billing_phone"), c1.get("delivery_phone"))
            c2_phone = _first_non_empty(c2.get("billing_phone"), c2.get("delivery_phone"))

            # Rule 1: メール完全一致
            if c1_email and c2_email and c1_email.lower() == c2_email.lower():
                score = 1.0
                reason = "メールアドレス完全一致"
            # Rule 2: 電話番号正規化一致
            elif c1_phone and c2_phone:
                p1, p2 = _normalize_phone(c1_phone), _normalize_phone(c2_phone)
                if p1 and p2 and p1 == p2 and len(p1) >= 10:
                    score = 0.95
                    reason = "電話番号一致"
            # Rule 3: 会社名+表示名の類似度
            if score == 0 and c1.get("company") and c2.get("company"):
                co_sim = _similarity(c1["company"] or "", c2["company"] or "")
                nm_sim = _similarity(c1["name"] or "", c2["name"] or "")
                if co_sim > 0.85 and nm_sim > 0.85:
                    score = (co_sim + nm_sim) / 2
                    reason = "会社名＋表示名の類似"

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
    """重複顧客のマージ（Phase 1-B-2 Step 5d で一時無効化）。

    Reviewer round 1 で「`master_id` / `merge_id` は `customers.id` の値だが、
    UPDATE 文では `deals.company_id = :customer_id` のように別 ID 空間の値を
    そのまま代入していた」というデータ破壊バグが指摘された。

    新 B2B モデル (companies / contacts) では「重複マージ」は会社単位 or
    担当者単位で別エンドポイント (`POST /companies/{master}/merge` / `POST
    /contacts/{master}/merge` 等) として再設計する必要があるため、本エンドポイント
    は 501 Not Implemented で即時 reject する。

    再設計までは利用頻度の低い手動マージ機能を一時封鎖し、誤った会社の
    deals/orders/quotes/invoices が付け替えられる事故を防ぐ。
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=(
            "Phase 1-B-2 Step 5d で重複マージ機能は再設計中。"
            "新 B2B モデル (companies) ベースで再実装するまで一時的に無効化"
        ),
    )
