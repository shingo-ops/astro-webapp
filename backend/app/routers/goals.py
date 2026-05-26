from __future__ import annotations

"""
目標管理 API。

目標の CRUD と、ダッシュボード固定エリア向けサマリーを提供する。

変更履歴:
  2026-05-25: 初版作成（ダッシュボード強化）
"""

import logging
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import (
    get_current_tenant,
    get_current_user,
    require_permission,
    reset_tenant_context,
)
from app.database import get_db
from app.models import User
from app.schemas.goal import (
    GoalCreate,
    GoalResponse,
    GoalSummaryResponse,
    GoalUpdate,
    GoalWithActual,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _current_week_num() -> int:
    return date.today().isocalendar()[1]


def _achievement_rate(actual: float, target: float) -> float:
    if target <= 0:
        return 0.0
    return round(actual / target * 100, 1)


# ─────────────────────────────────────────────
# CRUD
# ─────────────────────────────────────────────

@router.get(
    "/goals",
    response_model=list[GoalResponse],
    dependencies=[Depends(require_permission("goals.view"))],
)
async def list_goals(
    user_id: int | None = Query(default=None),
    team_id: int | None = Query(default=None),
    period_type: str | None = Query(default=None),
    period_year: int | None = Query(default=None),
    period_num: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """目標一覧取得"""
    filters = []
    params: dict = {}
    if user_id is not None:
        filters.append("user_id = :user_id")
        params["user_id"] = user_id
    if team_id is not None:
        filters.append("team_id = :team_id")
        params["team_id"] = team_id
    if period_type is not None:
        filters.append("period_type = :period_type")
        params["period_type"] = period_type
    if period_year is not None:
        filters.append("period_year = :period_year")
        params["period_year"] = period_year
    if period_num is not None:
        filters.append("period_num = :period_num")
        params["period_num"] = period_num

    where = ("WHERE " + " AND ".join(filters)) if filters else ""
    result = await db.execute(
        text(f"SELECT * FROM goals {where} ORDER BY period_year DESC, period_num DESC"),
        params,
    )
    rows = result.mappings().all()
    return [GoalResponse(**dict(r)) for r in rows]


@router.post(
    "/goals",
    response_model=GoalResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("goals.edit"))],
)
async def create_goal(
    body: GoalCreate,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """目標作成"""
    if (body.user_id is None) == (body.team_id is None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="user_id か team_id のどちらか一方のみ指定してください",
        )

    result = await db.execute(
        text("""
            INSERT INTO goals
                (user_id, team_id, period_type, period_year, period_num,
                 kpi_type, target_value, created_by)
            VALUES
                (:user_id, :team_id, :period_type, :period_year, :period_num,
                 :kpi_type, :target_value, :created_by)
            ON CONFLICT (user_id, team_id, period_type, period_year, period_num, kpi_type)
            DO UPDATE SET
                target_value = EXCLUDED.target_value,
                updated_at   = NOW()
            RETURNING *
        """),
        {
            "user_id": body.user_id,
            "team_id": body.team_id,
            "period_type": body.period_type,
            "period_year": body.period_year,
            "period_num": body.period_num,
            "kpi_type": body.kpi_type,
            "target_value": body.target_value,
            "created_by": current_user.id,
        },
    )
    await db.commit()
    await reset_tenant_context(db, tenant_id)  # ADR-072 Phase 2.5
    row = result.mappings().first()
    return GoalResponse(**dict(row))


@router.patch(
    "/goals/{goal_id}",
    response_model=GoalResponse,
    dependencies=[Depends(require_permission("goals.edit"))],
)
async def update_goal(
    goal_id: int,
    body: GoalUpdate,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """目標更新（target_value のみ）"""
    result = await db.execute(
        text("""
            UPDATE goals
            SET target_value = :target_value, updated_at = NOW()
            WHERE id = :id
            RETURNING *
        """),
        {"target_value": body.target_value, "id": goal_id},
    )
    await db.commit()
    await reset_tenant_context(db, tenant_id)  # ADR-072 Phase 2.5
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="目標が見つかりません")
    return GoalResponse(**dict(row))


@router.delete(
    "/goals/{goal_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("goals.edit"))],
)
async def delete_goal(
    goal_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """目標削除"""
    result = await db.execute(
        text("DELETE FROM goals WHERE id = :id RETURNING id"),
        {"id": goal_id},
    )
    await db.commit()
    await reset_tenant_context(db, tenant_id)  # ADR-072 Phase 2.5
    if not result.mappings().first():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="目標が見つかりません")


# ─────────────────────────────────────────────
# ダッシュボード用サマリー
# ─────────────────────────────────────────────

@router.get(
    "/goals/summary",
    response_model=GoalSummaryResponse,
    dependencies=[Depends(require_permission("goals.view"))],
)
async def get_goal_summary(
    tab: str = Query(default="individual", description="'team' または 'individual'"),
    user_id: int | None = Query(default=None, description="個人タブ時のユーザーID（未指定は自分）"),
    team_id: int | None = Query(default=None, description="チームタブ時のチームID"),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """
    ダッシュボード固定エリア用：今月・今週の目標 + 実績を返す。

    tab='individual': user_id（未指定は current_user.id）の個人目標
    tab='team':       team_id のチーム目標
    """
    today = date.today()
    current_month = today.month
    current_year = today.year
    current_week = _current_week_num()

    if tab == "team":
        if team_id is None:
            # hotfix: team タブで team_id 未指定の場合は空 summary を返す。
            # 422 だと dashboard 全体が error 表示で潰れるため graceful fallback。
            # 将来 team_id 選択 UI 実装時に required に戻す検討。
            return GoalSummaryResponse(monthly=[], weekly=[])
        owner_filter = "team_id = :owner_id AND user_id IS NULL"
        owner_id = team_id
    else:
        owner_id = user_id or current_user.id
        owner_filter = "user_id = :owner_id AND team_id IS NULL"

    # 目標取得（今月 + 今週）
    result = await db.execute(
        text(f"""
            SELECT *
            FROM goals
            WHERE {owner_filter}
              AND period_year = :year
              AND (
                (period_type = 'monthly' AND period_num = :month) OR
                (period_type = 'weekly'  AND period_num = :week)
              )
        """),
        {"owner_id": owner_id, "year": current_year, "month": current_month, "week": current_week},
    )
    goal_rows = {
        (r["period_type"], r["kpi_type"]): r
        for r in result.mappings().all()
    }

    # 実績: 今月分
    actuals_month = await _fetch_actuals(db, tab, owner_id, today, "monthly")
    # 実績: 今週分
    actuals_week = await _fetch_actuals(db, tab, owner_id, today, "weekly")

    kpi_types_team = ["revenue", "deal_count", "close_rate", "lead_count", "conversion_rate"]
    kpi_types_individual = ["revenue", "deal_count", "close_rate"]
    kpi_types = kpi_types_team if tab == "team" else kpi_types_individual

    def build_entries(period_type: str, actuals: dict) -> list[GoalWithActual]:
        entries = []
        for kpi in kpi_types:
            row = goal_rows.get((period_type, kpi))
            target = float(row["target_value"]) if row else 0.0
            actual = actuals.get(kpi, 0.0)
            entries.append(GoalWithActual(
                id=row["id"] if row else None,
                user_id=row["user_id"] if row else (owner_id if tab == "individual" else None),
                team_id=row["team_id"] if row else (owner_id if tab == "team" else None),
                period_type=period_type,
                period_year=current_year,
                period_num=current_month if period_type == "monthly" else current_week,
                kpi_type=kpi,
                target_value=target,
                actual_value=actual,
                achievement_rate=_achievement_rate(actual, target),
            ))
        return entries

    return GoalSummaryResponse(
        monthly=build_entries("monthly", actuals_month),
        weekly=build_entries("weekly", actuals_week),
    )


async def _fetch_actuals(
    db: AsyncSession,
    tab: str,
    owner_id: int,
    today: date,
    period_type: str,
) -> dict[str, float]:
    """KPIタイプ別の実績値を返す"""
    if period_type == "monthly":
        start = today.replace(day=1)
        # 翌月1日
        if today.month == 12:
            end = today.replace(year=today.year + 1, month=1, day=1)
        else:
            end = today.replace(month=today.month + 1, day=1)
    else:
        # 今週月曜日〜翌月曜日
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=7)

    if tab == "team":
        assign_filter = "assigned_to IN (SELECT user_id FROM team_members WHERE team_id = :owner_id)"
    else:
        assign_filter = "assigned_to = :owner_id"

    params = {"owner_id": owner_id, "start": start, "end": end}

    # 売上（受注の total_amount）
    r = await db.execute(
        text("""
            SELECT COALESCE(SUM(total_amount), 0) AS val
            FROM orders
            WHERE created_at >= :start AND created_at < :end
        """),
        params,
    )
    revenue = float(r.scalar() or 0)

    # 商談数（期間内に作成された商談）
    r = await db.execute(
        text(f"""
            SELECT COUNT(*) AS val
            FROM deals
            WHERE {assign_filter}
              AND created_at >= :start AND created_at < :end
        """),
        params,
    )
    deal_count = float(r.scalar() or 0)

    # 成約率（期間内の成約 / 期間内の商談）
    r = await db.execute(
        text(f"""
            SELECT
                COUNT(*) FILTER (WHERE status = 'won') AS won,
                COUNT(*) AS total
            FROM deals
            WHERE {assign_filter}
              AND created_at >= :start AND created_at < :end
        """),
        params,
    )
    row = r.mappings().first() or {}
    total_deals = row.get("total", 0) or 0
    won_deals = row.get("won", 0) or 0
    close_rate = round(won_deals / total_deals * 100, 1) if total_deals > 0 else 0.0

    # リード数（チームタブのみ）
    r = await db.execute(
        text(f"""
            SELECT COUNT(*) AS val
            FROM leads
            WHERE {assign_filter}
              AND created_at >= :start AND created_at < :end
        """),
        params,
    )
    lead_count = float(r.scalar() or 0)

    # コンバージョン率（チームタブのみ）
    r = await db.execute(
        text(f"""
            SELECT
                COUNT(*) FILTER (WHERE converted_deal_id IS NOT NULL) AS converted,
                COUNT(*) AS total
            FROM leads
            WHERE {assign_filter}
              AND created_at >= :start AND created_at < :end
        """),
        params,
    )
    row = r.mappings().first() or {}
    total_leads = row.get("total", 0) or 0
    converted = row.get("converted", 0) or 0
    conversion_rate = round(converted / total_leads * 100, 1) if total_leads > 0 else 0.0

    return {
        "revenue": revenue,
        "deal_count": deal_count,
        "close_rate": close_rate,
        "lead_count": lead_count,
        "conversion_rate": conversion_rate,
    }
