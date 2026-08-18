"""Budget API endpoints - policy creation and usage reporting."""

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, func

from nexus.api.deps import DbSession
from nexus.models.budget import BudgetPolicy, CostEvent

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


@router.post(
    "/api/v1/companies/{company_id}/budget-policies",
    status_code=status.HTTP_201_CREATED,
    response_model=BudgetPolicyResponse,
)
async def create_budget_policy(
    company_id: uuid.UUID, body: BudgetPolicyCreate, db: DbSession
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
    company_id: uuid.UUID, db: DbSession
) -> Any:
    """Get budget usage for a company."""
    now = datetime.now(timezone.utc)
    window_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    stmt = select(
        func.coalesce(func.sum(CostEvent.cost_cents), 0),
        func.coalesce(func.sum(CostEvent.input_tokens), 0),
        func.coalesce(func.sum(CostEvent.output_tokens), 0),
        func.count(CostEvent.id),
    ).where(
        CostEvent.company_id == company_id,
        CostEvent.occurred_at >= window_start,
    )

    result = await db.execute(stmt)
    row = result.one()
    total_cost, total_input, total_output, count = row

    return BudgetUsageResponse(
        scope_type="company",
        scope_id=company_id,
        total_cost_cents=int(total_cost),
        total_input_tokens=int(total_input),
        total_output_tokens=int(total_output),
        event_count=int(count),
    )


@router.get(
    "/api/v1/agents/{agent_id}/budget-usage",
    response_model=BudgetUsageResponse,
)
async def get_agent_budget_usage(
    agent_id: uuid.UUID, db: DbSession
) -> Any:
    """Get budget usage for an agent."""
    now = datetime.now(timezone.utc)
    window_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    stmt = select(
        func.coalesce(func.sum(CostEvent.cost_cents), 0),
        func.coalesce(func.sum(CostEvent.input_tokens), 0),
        func.coalesce(func.sum(CostEvent.output_tokens), 0),
        func.count(CostEvent.id),
    ).where(
        CostEvent.agent_id == agent_id,
        CostEvent.occurred_at >= window_start,
    )

    result = await db.execute(stmt)
    row = result.one()
    total_cost, total_input, total_output, count = row

    return BudgetUsageResponse(
        scope_type="agent",
        scope_id=agent_id,
        total_cost_cents=int(total_cost),
        total_input_tokens=int(total_input),
        total_output_tokens=int(total_output),
        event_count=int(count),
    )
