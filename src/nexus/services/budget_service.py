"""Budget Service - budget enforcement, cost tracking, and usage reporting."""

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.models.budget import BudgetPolicy, CostEvent


@dataclass
class BudgetCheckResult:
    """Result of a budget check operation."""

    allowed: bool
    remaining_cents: int
    used_cents: int
    limit_cents: int
    warn_threshold_reached: bool
    policy_id: uuid.UUID | None = None
    message: str = ""


@dataclass
class UsageSummary:
    """Summary of budget usage for a scope."""

    scope_type: str
    scope_id: uuid.UUID
    total_cost_cents: int
    total_input_tokens: int
    total_output_tokens: int
    event_count: int
    window_start: datetime
    window_end: datetime


class BudgetService:
    """Service layer for budget enforcement, cost recording, and usage reporting.

    Provides budget checking before operations, cost event recording after
    operations, and usage summaries for reporting.
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def check_budget(
        self,
        scope_type: str,
        scope_id: uuid.UUID,
        amount: int,
        company_id: uuid.UUID | None = None,
    ) -> BudgetCheckResult:
        """Check if a budget allows spending the given amount.

        Looks up active budget policies for the scope and evaluates
        whether the requested amount is within limits.

        Args:
            scope_type: Type of scope (company, department, agent, project).
            scope_id: ID of the scoped entity.
            amount: Amount in cents to check.
            company_id: Optional company ID for filtering.

        Returns:
            BudgetCheckResult with allowed/denied status and details.
        """
        # Find active policies for this scope
        stmt = select(BudgetPolicy).where(
            BudgetPolicy.scope_type == scope_type,
            BudgetPolicy.scope_id == scope_id,
            BudgetPolicy.is_active == True,  # noqa: E712
        )
        if company_id:
            stmt = stmt.where(BudgetPolicy.company_id == company_id)

        result = await self._db.execute(stmt)
        policies = result.scalars().all()

        if not policies:
            # No policy means unlimited
            return BudgetCheckResult(
                allowed=True,
                remaining_cents=0,
                used_cents=0,
                limit_cents=0,
                warn_threshold_reached=False,
                message="No budget policy configured",
            )

        # Check against the most restrictive active policy
        for policy in policies:
            if policy.metric != "cost_cents":
                continue

            # Get current usage for this window
            usage = await self._get_window_usage(
                scope_type, scope_id, policy.window_kind
            )
            used = usage.total_cost_cents if usage else 0
            remaining = policy.amount - used
            warn_threshold = policy.amount * policy.warn_percent // 100

            if policy.hard_stop_enabled and (used + amount) > policy.amount:
                return BudgetCheckResult(
                    allowed=False,
                    remaining_cents=max(0, remaining),
                    used_cents=used,
                    limit_cents=policy.amount,
                    warn_threshold_reached=used >= warn_threshold,
                    policy_id=policy.id,
                    message=f"Budget exceeded: used={used}, limit={policy.amount}",
                )

            return BudgetCheckResult(
                allowed=True,
                remaining_cents=max(0, remaining - amount),
                used_cents=used,
                limit_cents=policy.amount,
                warn_threshold_reached=(used + amount) >= warn_threshold,
                policy_id=policy.id,
            )

        # Fallback: no cost_cents policy found
        return BudgetCheckResult(
            allowed=True,
            remaining_cents=0,
            used_cents=0,
            limit_cents=0,
            warn_threshold_reached=False,
            message="No cost_cents policy found",
        )

    async def record_cost(
        self,
        company_id: uuid.UUID,
        agent_id: uuid.UUID | None = None,
        task_id: uuid.UUID | None = None,
        project_id: uuid.UUID | None = None,
        provider: str = "unknown",
        model: str | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_cents: int = 0,
        billing_type: str = "llm_inference",
    ) -> CostEvent:
        """Record a cost event.

        Args:
            company_id: The company being charged.
            agent_id: Optional agent that incurred the cost.
            task_id: Optional task this cost is associated with.
            project_id: Optional project this cost belongs to.
            provider: The service provider (e.g., openai, anthropic).
            model: Optional model identifier.
            input_tokens: Number of input tokens.
            output_tokens: Number of output tokens.
            cost_cents: Total cost in cents.
            billing_type: Type of charge.

        Returns:
            The recorded CostEvent instance.
        """
        event = CostEvent(
            company_id=company_id,
            agent_id=agent_id,
            task_id=task_id,
            project_id=project_id,
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_cents=cost_cents,
            billing_type=billing_type,
        )
        self._db.add(event)
        await self._db.flush()
        return event

    async def get_usage(
        self,
        scope_type: str,
        scope_id: uuid.UUID,
        window: str = "monthly",
    ) -> UsageSummary | None:
        """Get usage summary for a scope within a time window.

        Args:
            scope_type: Type of scope (company, agent, project).
            scope_id: ID of the scoped entity.
            window: Time window (monthly, weekly, daily).

        Returns:
            UsageSummary with aggregated cost data.
        """
        return await self._get_window_usage(scope_type, scope_id, window)

    async def enforce_limit(
        self,
        agent_id: uuid.UUID,
        cost_cents: int,
    ) -> bool:
        """Check if an agent can spend the given amount.

        Convenience method that combines budget lookup and check
        specifically for agent-level enforcement.

        Args:
            agent_id: The agent attempting to spend.
            cost_cents: The amount to spend in cents.

        Returns:
            True if the spend is allowed, False if it would exceed limits.
        """
        result = await self.check_budget("agent", agent_id, cost_cents)
        return result.allowed

    async def _get_window_usage(
        self,
        scope_type: str,
        scope_id: uuid.UUID,
        window: str,
    ) -> UsageSummary | None:
        """Compute usage within a time window for a scope.

        Args:
            scope_type: Scope type for filtering.
            scope_id: Scope ID for filtering.
            window: Time window kind.

        Returns:
            UsageSummary or None if no events found.
        """
        now = datetime.now(timezone.utc)

        if window == "daily":
            window_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif window == "weekly":
            days_since_monday = now.weekday()
            window_start = (now - timedelta(days=days_since_monday)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
        else:  # monthly
            window_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        # Build filter based on scope type
        if scope_type == "agent":
            filter_col = CostEvent.agent_id
        elif scope_type == "project":
            filter_col = CostEvent.project_id
        else:  # company
            filter_col = CostEvent.company_id

        stmt = select(
            func.coalesce(func.sum(CostEvent.cost_cents), 0),
            func.coalesce(func.sum(CostEvent.input_tokens), 0),
            func.coalesce(func.sum(CostEvent.output_tokens), 0),
            func.count(CostEvent.id),
        ).where(
            filter_col == scope_id,
            CostEvent.occurred_at >= window_start,
        )

        result = await self._db.execute(stmt)
        row = result.one_or_none()

        if row is None:
            return None

        total_cost, total_input, total_output, count = row

        return UsageSummary(
            scope_type=scope_type,
            scope_id=scope_id,
            total_cost_cents=int(total_cost),
            total_input_tokens=int(total_input),
            total_output_tokens=int(total_output),
            event_count=int(count),
            window_start=window_start,
            window_end=now,
        )
