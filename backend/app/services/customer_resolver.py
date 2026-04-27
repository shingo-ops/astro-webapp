from __future__ import annotations

"""
Phase 1-B-2 Step 5c-3: 新 B2B モデル (company_id, contact_id) → 旧 customer_id 逆引き。

frontend は Step 5c-3 から CompanyContactSelector で (company_id, contact_id) を送信する。
backend の deals/orders/quotes/leads.convert は customer_id を Step 5d まで FK 整合性のため
保持する必要があるため、新モデル送信時は内部で _customer_migration_map から逆引きする。

Step 5d で customer_id 列が drop されたら本モジュールごと削除する。
"""

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def resolve_customer_id(
    db: AsyncSession,
    contact_id: int,
    company_id: int | None = None,
) -> int:
    """contact_id から旧 customer_id を逆引きする。

    company_id も与えられた場合は contact が指定 company に所属しているかも検証する。
    マップに該当が無い場合は 404、所属不一致は 400。

    本関数は SELECT のみで、IntegrityError を投げる側ではない（PR #150 review M3）。

    PR #147 review F3 / migration 034:
      `_customer_migration_map.new_contact_id` には UNIQUE 制約 `uniq_cmm_new_contact_id`
      が migration 034 で付与されており、`.first()` の結果は決定的（最大 1 行）。
      もし将来 manual_merge / manual_override 等で 1 contact に 2 customers を
      紐づけようとした場合、その INSERT/UPDATE は上流の UPSERT 経路
      （例: `migrate_companies_contacts_from_customers.py`、または将来の管理画面 API）で
      DB レベルの IntegrityError として捕捉される。
      本 resolver はその構造的保証の恩恵を受けて、`.first()` の非決定性を回避できる。
    """
    row = (
        await db.execute(
            text(
                "SELECT old_customer_id, new_company_id "
                "FROM _customer_migration_map WHERE new_contact_id = :cid"
            ),
            {"cid": contact_id},
        )
    ).first()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="指定された担当者の旧顧客マッピングが見つかりません",
        )
    if company_id is not None and row[1] != company_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="指定された担当者は指定会社に所属していません",
        )
    return row[0]
