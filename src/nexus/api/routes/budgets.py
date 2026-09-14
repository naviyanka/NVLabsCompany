"""Budget API endpoints - policy creation and usage reporting.

Spend is commercially sensitive and a budget policy is what stops a runaway
agent from spending without limit, so the company in these URLs is validated
against the caller's own tenant (:data:`~nexus.api.deps.PathCompanyId`) and
writing a policy requires the administrator role.
"""

import uuid
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, status
from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select

from nexus.api.deps import CurrentCompanyId, DbSession, PathCompanyId, RequireAdmin
from nexus.models._time import utcnow
from nexus.models.budget import BudgetPolicy, CostEvent
from nexus.services.budget_service import _calculate_window_start

router = APIRouter(tags=["budgets"])


class BudgetPolicyCreate(BaseModel):
    """Request body for creating a budget policy."""

    scope_type: str
    scope_id: uuid.UUID
    metric: str = "cost_cents"
    window_kind: str = "monthly"
    amount: int
    warn_percent: int = 80
    hard_stop_enabled: bool = True


class BudgetPolicyResponse(BaseModel):
    """Response model for a budget policy."""

    id: uuid.UUID
    company_id: uuid.UUID
    scope_type: str
    scope_id: uuid.UUID
    metric: str
    window_kind: str
    amount: int
    warn_percent: int
    hard_stop_enabled: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime


class BudgetUsageResponse(BaseModel):
    """Response model for budget usage summary."""

    scope_type: str
    scope_id: uuid.UUID
    total_cost_cents: int
    total_input_tokens: int
    total_output_tokens: int
    event_count: int


def _live_or_committed(now: datetime) -> Any:
    """Status filter shared by the budget read endpoints.

    Live holds count like settled spend (that is what stops two workers
    from both passing a check only one fits under); released holds never
    count; an expired hold stops counting on its own so a worker that died
    mid-call does not pin the budget forever. Mirrors
    BudgetService._get_window_usage - keep the two in agreement (R13).
    """
    return or_(
        CostEvent.status == "committed",
        and_(
            CostEvent.status == "reserved",
            or_(
                CostEvent.expires_at.is_(None),
                CostEvent.expires_at > now,
            ),
        ),
    )


@router.post(
    "/api/v1/companies/{company_id}/budget-policies",
    status_code=status.HTTP_201_CREATED,
    response_model=BudgetPolicyResponse,
)
async def create_budget_policy(
    company_id: PathCompanyId,
    body: BudgetPolicyCreate,
    db: DbSession,
    principal: RequireAdmin,
) -> Any:
    """Create a new budget policy for a company."""
    policy = BudgetPolicy(
        company_id=company_id,
        scope_type=body.scope_type,
        scope_id=body.scope_id,
        metric=body.metric,
        window_kind=body.window_kind,
        amount=body.amount,
        warn_percent=body.warn_percent,
        hard_stop_enabled=body.hard_stop_enabled,
    )
    db.add(policy)
    await db.flush()
    return policy


@router.get(
    "/api/v1/companies/{company_id}/budget-usage",
    response_model=BudgetUsageResponse,
)
async def get_company_budget_usage(
    company_id: PathCompanyId, db: DbSession, window: str = "monthly"
) -> Any:
    """Get budget usage for a company within a window (B5: status-correct)."""
    stmt = select(
        func.coalesce(func.sum(CostEvent.cost_cents), 0),
        func.coalesce(func.sum(CostEvent.input_tokens), 0),
        func.coalesce(func.sum(CostEvent.output_tokens), 0),
        func.count(CostEvent.id),
    ).where(
        CostEvent.company_id == company_id,
        CostEvent.occurred_at >= _calculate_window_start(window, utcnow()),
        _live_or_committed(utcnow()),
    )
    result = await db.execute(stmt)
    row = result.one()

    return BudgetUsageResponse(
        scope_type="company",
        scope_id=company_id,
        total_cost_cents=int(row[0]),
        total_input_tokens=int(row[1]),
        total_output_tokens=int(row[2]),
        event_count=int(row[3]),
    )


@router.get(
    "/api/v1/agents/{agent_id}/budget-usage",
    response_model=BudgetUsageResponse,
)
async def get_agent_budget_usage(
    agent_id: uuid.UUID,
    db: DbSession,
    company_id: CurrentCompanyId,
    window: str = "monthly",
) -> Any:
    """Get budget usage for an agent within a window (B5: status-correct)."""
    stmt = select(
        func.coalesce(func.sum(CostEvent.cost_cents), 0),
        func.coalesce(func.sum(CostEvent.input_tokens), 0),
        func.coalesce(func.sum(CostEvent.output_tokens), 0),
        func.count(CostEvent.id),
    ).where(
        CostEvent.agent_id == agent_id,
        CostEvent.company_id == company_id,
        CostEvent.occurred_at >= _calculate_window_start(window, utcnow()),
        _live_or_committed(utcnow()),
    )
    result = await db.execute(stmt)
    row = result.one()

    return BudgetUsageResponse(
        scope_type="agent",
        scope_id=agent_id,
        total_cost_cents=int(row[0]),
        total_input_tokens=int(row[1]),
        total_output_tokens=int(row[2]),
        event_count=int(row[3]),
    )


@router.get("/api/v1/companies/{company_id}/budgets/cost-trend")
async def cost_trend(
    company_id: PathCompanyId,
    db: DbSession,
    days: int = 7,
) -> list[dict[str, Any]]:
    """Daily cost trend for the last N days (B5: status-correct)."""
    now = utcnow()
    results = []
    for i in range(days):
        day = now - timedelta(days=days - 1 - i)
        day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        row = await db.execute(
            select(
                func.coalesce(func.sum(CostEvent.cost_cents), 0),
                func.coalesce(func.sum(CostEvent.input_tokens), 0),
                func.coalesce(func.sum(CostEvent.output_tokens), 0),
            ).where(
                CostEvent.company_id == company_id,
                CostEvent.occurred_at >= day_start,
                CostEvent.occurred_at < day_end,
                _live_or_committed(now),
            )
        )
        r = row.one()
        results.append(
            {
                "date": day_start.strftime("%Y-%m-%d"),
                "cost_cents": int(r[0]),
                "input_tokens": int(r[1]),
                "output_tokens": int(r[2]),
            }
        )
    return results
