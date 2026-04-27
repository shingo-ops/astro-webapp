from __future__ import annotations

"""
重複検知API（customers ベース）。

顧客の重複候補を検出する読み取り専用 API。
旧来 customers テーブル直下の手作業マージ画面 (CustomersPage) 用に残している。

検出ルール:
  1. メールアドレス完全一致
  2. 電話番号正規化後一致
  3. 会社名＋名前のレーベンシュタイン類似度

変更履歴:
  2026-04-17: 初版作成（Phase 3）。
  2026-04-27: Phase 1-B-2 Step 5d — merge_customers の関連レコード付け替えを
    customer_id ベースから company_id ベースに切替。
  2026-04-27 (round 1 review fix): Reviewer Major 1 — `master_id` / `merge_id` を
    `customers.id` のまま `UPDATE deals SET company_id = :customer_id` していた
    データ破壊バグを発見。新 B2B モデル (companies) ベースで再実装するまで
    一時的に 501 Not Implemented で無効化。
  2026-04-27 (A-4 / PR #145+#152 follow-up): 重複マージ機能を companies ベースで
    再設計し `POST /companies/{master_id}/merge` (routers/companies.py) として
    再実装した。本ルーターからは旧 `merge_customers` エンドポイントを撤去。
    検出 (`GET /customers/duplicates`) は引き続き customers テーブル直下の重複
    候補を返す（旧 UI の互換維持）。
"""

import re
from difflib import SequenceMatcher

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
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


# 重複「マージ」エンドポイントは companies ベースで再設計され、
# `POST /api/v1/companies/{master_id}/merge` (routers/companies.py) に移管された。
# 旧 `POST /api/v1/customers/{master_id}/merge` は撤去済み。
