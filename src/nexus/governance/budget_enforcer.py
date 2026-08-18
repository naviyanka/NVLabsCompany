"""Budget Enforcer - checks spending authorization and tracks budget consumption."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class BudgetDecision(str, Enum):
    """Possible outcomes of a budget check.

    Values:
        ALLOWED: Spending is within budget.
        WARNING: Spending is within budget but above warning threshold.
        DENIED: Spending would exceed budget limit.
    """

    ALLOWED = "allowed"
    WARNING = "warning"
    DENIED = "denied"


@dataclass
class BudgetCheckResult:
    """Result of a budget check.

    Attributes:
        decision: The budget decision.
        remaining_cents: Amount remaining in budget.
        budget_total_cents: Total budget allocation.
        spent_cents: Amount already spent.
        warning_threshold_percent: Configured warning threshold.
        message: Human-readable explanation.
    """

    decision: BudgetDecision
    remaining_cents: int
    budget_total_cents: int
    spent_cents: int
    warning_threshold_percent: int = 80
    message: str = ""


@dataclass
class CostEventRecord:
    """A recorded cost event.

    Attributes:
        id: Unique event identifier.
        scope_type: Budget scope (company, department, agent, project).
        scope_id: Identifier within the scope.
        amount_cents: Cost in cents.
        description: What the cost was for.
        timestamp: When the cost occurred.
    """

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    scope_type: str = ""
    scope_id: uuid.UUID = field(default_factory=uuid.uuid4)
    amount_cents: int = 0
    description: str = ""
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class BudgetEnforcer:
    """Enforces budget limits across companies, departments, and agents.

    Provides pre-execution budget checks and post-execution cost recording.
    Supports warning thresholds and hard spending limits.
    """

    def __init__(self) -> None:
        """Initialize the budget enforcer."""
        # Budget allocations: (scope_type, scope_id) -> total_cents
        self._budgets: dict[tuple[str, uuid.UUID], int] = {}
        # Warning thresholds: (scope_type, scope_id) -> percent
        self._warning_thresholds: dict[tuple[str, uuid.UUID], int] = {}
        # Spent tracking: (scope_type, scope_id) -> spent_cents
        self._spent: dict[tuple[str, uuid.UUID], int] = {}
        # Cost events log
        self._cost_events: list[CostEventRecord] = []

    def set_budget(
        self,
        scope_type: str,
        scope_id: uuid.UUID,
        total_cents: int,
        warn_percent: int = 80,
    ) -> None:
        """Set or update a budget allocation.

        Args:
            scope_type: Budget scope (company, department, agent, project).
            scope_id: Identifier within the scope.
            total_cents: Total budget in cents.
            warn_percent: Warning threshold as a percentage (0-100).
        """
        key = (scope_type, scope_id)
        self._budgets[key] = total_cents
        self._warning_thresholds[key] = warn_percent
        if key not in self._spent:
            self._spent[key] = 0

    def check_can_spend(
        self, scope_type: str, scope_id: uuid.UUID, amount_cents: int
    ) -> BudgetCheckResult:
        """Check if a spending amount is allowed within budget.

        Args:
            scope_type: Budget scope (company, department, agent, project).
            scope_id: Identifier within the scope.
            amount_cents: Amount in cents to check.

        Returns:
            A BudgetCheckResult with the decision and details.
        """
        key = (scope_type, scope_id)

        budget_total = self._budgets.get(key)
        if budget_total is None:
            # No budget configured - allow by default
            return BudgetCheckResult(
                decision=BudgetDecision.ALLOWED,
                remaining_cents=0,
                budget_total_cents=0,
                spent_cents=0,
                message="No budget configured for this scope",
            )

        spent = self._spent.get(key, 0)
        remaining = budget_total - spent
        warn_percent = self._warning_thresholds.get(key, 80)

        # Check if spending would exceed budget
        if amount_cents > remaining:
            return BudgetCheckResult(
                decision=BudgetDecision.DENIED,
                remaining_cents=remaining,
                budget_total_cents=budget_total,
                spent_cents=spent,
                warning_threshold_percent=warn_percent,
                message=(
                    f"Insufficient budget: requested {amount_cents} cents "
                    f"but only {remaining} cents remaining"
                ),
            )

        # Check if we are above warning threshold
        new_spent = spent + amount_cents
        spent_percent = (new_spent / budget_total) * 100 if budget_total > 0 else 0

        if spent_percent >= warn_percent:
            return BudgetCheckResult(
                decision=BudgetDecision.WARNING,
                remaining_cents=remaining,
                budget_total_cents=budget_total,
                spent_cents=spent,
                warning_threshold_percent=warn_percent,
                message=(
                    f"Budget warning: spending at {spent_percent:.0f}% "
                    f"(threshold: {warn_percent}%)"
                ),
            )

        return BudgetCheckResult(
            decision=BudgetDecision.ALLOWED,
            remaining_cents=remaining,
            budget_total_cents=budget_total,
            spent_cents=spent,
            warning_threshold_percent=warn_percent,
            message="Spending within budget",
        )

    def get_remaining_budget(self, scope_type: str, scope_id: uuid.UUID) -> int:
        """Get remaining budget in cents for a scope.

        Args:
            scope_type: Budget scope.
            scope_id: Scope identifier.

        Returns:
            Remaining budget in cents. Returns 0 if no budget is set.
        """
        key = (scope_type, scope_id)
        budget_total = self._budgets.get(key, 0)
        spent = self._spent.get(key, 0)
        return max(0, budget_total - spent)

    def on_cost_event(
        self,
        scope_type: str,
        scope_id: uuid.UUID,
        amount_cents: int,
        description: str = "",
    ) -> BudgetDecision:
        """Record a cost event and update spent counters.

        Args:
            scope_type: Budget scope.
            scope_id: Scope identifier.
            amount_cents: Amount spent in cents.
            description: What the cost was for.

        Returns:
            The current budget decision after recording the event.
        """
        key = (scope_type, scope_id)

        # Record the event
        event = CostEventRecord(
            scope_type=scope_type,
            scope_id=scope_id,
            amount_cents=amount_cents,
            description=description,
        )
        self._cost_events.append(event)

        # Update spent counter
        if key not in self._spent:
            self._spent[key] = 0
        self._spent[key] += amount_cents

        # Return current status
        result = self.check_can_spend(scope_type, scope_id, 0)
        return result.decision

    def get_cost_events(
        self,
        scope_type: str | None = None,
        scope_id: uuid.UUID | None = None,
        limit: int = 100,
    ) -> list[CostEventRecord]:
        """Retrieve cost events with optional filters.

        Args:
            scope_type: Filter by scope type.
            scope_id: Filter by scope ID.
            limit: Maximum events to return.

        Returns:
            List of CostEventRecord objects.
        """
        results: list[CostEventRecord] = []
        for event in reversed(self._cost_events):
            if scope_type and event.scope_type != scope_type:
                continue
            if scope_id and event.scope_id != scope_id:
                continue
            results.append(event)
            if len(results) >= limit:
                break
        return results
