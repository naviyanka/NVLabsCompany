"""Budget Enforcer - checks spending authorization and tracks budget consumption.

Supports multi-metric tracking (cost_cents, tokens, api_calls), multiple window
kinds (monthly, weekly, daily, per_execution, lifetime), hard-stop auto-pause,
and incident recording on budget breaches.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from nexus.governance.budget_incident import BudgetIncident, BudgetIncidentLog


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


class WindowKind(str, Enum):
    """Time window for budget tracking.

    Values:
        MONTHLY: Budget resets monthly.
        WEEKLY: Budget resets weekly.
        DAILY: Budget resets daily.
        PER_EXECUTION: Budget applies to a single execution.
        LIFETIME: Cumulative spending across all time.
    """

    MONTHLY = "monthly"
    WEEKLY = "weekly"
    DAILY = "daily"
    PER_EXECUTION = "per_execution"
    LIFETIME = "lifetime"


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


# Type aliases for callback signatures
AutoPauseCallback = Callable[[uuid.UUID, BudgetIncident], None]
CancelWorkCallback = Callable[[str, uuid.UUID], None]


class BudgetEnforcer:
    """Enforces budget limits across companies, departments, and agents.

    Provides pre-execution budget checks and post-execution cost recording.
    Supports warning thresholds, hard spending limits, multi-metric tracking,
    lifetime windows, auto-pause on hard_stop, and cancel-work-for-scope hooks.
    """

    def __init__(
        self,
        auto_pause_callback: AutoPauseCallback | None = None,
        cancel_work_callback: CancelWorkCallback | None = None,
        hard_stop_enabled: bool = False,
    ) -> None:
        """Initialize the budget enforcer.

        Args:
            auto_pause_callback: Called with (agent_id, incident) when a hard
                stop triggers and an agent needs to be paused.
            cancel_work_callback: Called with (scope_type, scope_id) when a
                hard stop triggers to cancel in-flight work.
            hard_stop_enabled: Whether to enable hard-stop behavior on DENIED.
        """
        # Budget allocations: (scope_type, scope_id) -> total_cents
        self._budgets: dict[tuple[str, uuid.UUID], int] = {}
        # Warning thresholds: (scope_type, scope_id) -> percent
        self._warning_thresholds: dict[tuple[str, uuid.UUID], int] = {}
        # Spent tracking: (scope_type, scope_id) -> spent_cents
        self._spent: dict[tuple[str, uuid.UUID], int] = {}
        # Cost events log
        self._cost_events: list[CostEventRecord] = []

        # Multi-metric tracking: (scope_type, scope_id) -> {metric: amount}
        self._metrics: dict[
            tuple[str, uuid.UUID], dict[str, int]
        ] = {}

        # Metric budgets: (scope_type, scope_id, metric) -> total
        self._metric_budgets: dict[tuple[str, uuid.UUID, str], int] = {}
        # Metric warning thresholds: (scope_type, scope_id, metric) -> percent
        self._metric_warn: dict[tuple[str, uuid.UUID, str], int] = {}

        # Window kinds: (scope_type, scope_id) -> WindowKind
        self._window_kinds: dict[tuple[str, uuid.UUID], WindowKind] = {}

        # Agent mapping: (scope_type, scope_id) -> agent_id
        self._scope_agent: dict[tuple[str, uuid.UUID], uuid.UUID] = {}

        # Callbacks
        self._auto_pause_callback = auto_pause_callback
        self._cancel_work_callback = cancel_work_callback
        self._hard_stop_enabled = hard_stop_enabled

        # Incident log
        self.incident_log = BudgetIncidentLog()

    def set_budget(
        self,
        scope_type: str,
        scope_id: uuid.UUID,
        total_cents: int,
        warn_percent: int = 80,
        metric: str = "cost_cents",
        window_kind: WindowKind | str | None = None,
        agent_id: uuid.UUID | None = None,
    ) -> None:
        """Set or update a budget allocation.

        Args:
            scope_type: Budget scope (company, department, agent, project).
            scope_id: Identifier within the scope.
            total_cents: Total budget amount (in cents for cost_cents, raw
                count for tokens/api_calls).
            warn_percent: Warning threshold as a percentage (0-100).
            metric: The metric this budget applies to. One of cost_cents,
                tokens, or api_calls.
            window_kind: The time window for this budget. Defaults to monthly
                if not specified.
            agent_id: Optional agent associated with this scope for auto-pause.
        """
        key = (scope_type, scope_id)

        # Always set the primary cost budget for backward compatibility
        if metric == "cost_cents":
            self._budgets[key] = total_cents
            self._warning_thresholds[key] = warn_percent
            if key not in self._spent:
                self._spent[key] = 0

        # Set metric-specific budget
        metric_key = (scope_type, scope_id, metric)
        self._metric_budgets[metric_key] = total_cents
        self._metric_warn[metric_key] = warn_percent

        # Initialize multi-metric tracking
        if key not in self._metrics:
            self._metrics[key] = {"cost_cents": 0, "tokens": 0, "api_calls": 0}

        # Set window kind
        if window_kind is not None:
            if isinstance(window_kind, str):
                window_kind = WindowKind(window_kind)
            self._window_kinds[key] = window_kind

        # Associate agent
        if agent_id is not None:
            self._scope_agent[key] = agent_id

    def check_can_spend(
        self,
        scope_type: str,
        scope_id: uuid.UUID,
        amount_cents: int,
        metric: str = "cost_cents",
    ) -> BudgetCheckResult:
        """Check if a spending amount is allowed within budget.

        Args:
            scope_type: Budget scope (company, department, agent, project).
            scope_id: Identifier within the scope.
            amount_cents: Amount to check (cents for cost_cents, raw count
                for tokens/api_calls).
            metric: The metric to check against.

        Returns:
            A BudgetCheckResult with the decision and details.
        """
        key = (scope_type, scope_id)
        metric_key = (scope_type, scope_id, metric)

        # For the default cost_cents metric, use the primary budget
        # for backward compatibility
        if metric == "cost_cents":
            budget_total = self._budgets.get(key)
            if budget_total is None:
                # Check if there is a metric-specific budget
                budget_total = self._metric_budgets.get(metric_key)
            if budget_total is None:
                return BudgetCheckResult(
                    decision=BudgetDecision.ALLOWED,
                    remaining_cents=0,
                    budget_total_cents=0,
                    spent_cents=0,
                    message="No budget configured for this scope",
                )
            spent = self._spent.get(key, 0)
            warn_percent = self._warning_thresholds.get(
                key, self._metric_warn.get(metric_key, 80)
            )
        else:
            # Non-cost metric: use metric-specific budget
            budget_total = self._metric_budgets.get(metric_key)
            if budget_total is None:
                return BudgetCheckResult(
                    decision=BudgetDecision.ALLOWED,
                    remaining_cents=0,
                    budget_total_cents=0,
                    spent_cents=0,
                    message="No budget configured for this scope",
                )
            metrics = self._metrics.get(key, {})
            spent = metrics.get(metric, 0)
            warn_percent = self._metric_warn.get(metric_key, 80)

        remaining = budget_total - spent

        # Check if spending would exceed budget
        if amount_cents > remaining:
            return BudgetCheckResult(
                decision=BudgetDecision.DENIED,
                remaining_cents=remaining,
                budget_total_cents=budget_total,
                spent_cents=spent,
                warning_threshold_percent=warn_percent,
                message=(
                    f"Insufficient budget: requested {amount_cents} "
                    f"but only {remaining} remaining"
                ),
            )

        # Check if we are above warning threshold
        new_spent = spent + amount_cents
        spent_percent = (
            (new_spent / budget_total) * 100 if budget_total > 0 else 0
        )

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
        metric: str = "cost_cents",
        tokens: int = 0,
        api_calls: int = 0,
        agent_id: uuid.UUID | None = None,
    ) -> BudgetDecision:
        """Record a cost event and update spent counters.

        Supports multi-metric tracking. When metric is cost_cents, the
        amount_cents parameter is used. Additional token and api_call
        counts can be passed to track those metrics simultaneously.

        Args:
            scope_type: Budget scope.
            scope_id: Scope identifier.
            amount_cents: Amount spent in cents.
            description: What the cost was for.
            metric: Primary metric being recorded.
            tokens: Number of tokens consumed (tracked as secondary metric).
            api_calls: Number of API calls made (tracked as secondary metric).
            agent_id: Agent that incurred the cost, for auto-pause.

        Returns:
            The current budget decision after recording the event.
        """
        key = (scope_type, scope_id)

        # Record the cost event
        event = CostEventRecord(
            scope_type=scope_type,
            scope_id=scope_id,
            amount_cents=amount_cents,
            description=description,
        )
        self._cost_events.append(event)

        # Update primary spent counter (backward-compatible)
        if key not in self._spent:
            self._spent[key] = 0
        self._spent[key] += amount_cents

        # Update multi-metric tracking
        if key not in self._metrics:
            self._metrics[key] = {"cost_cents": 0, "tokens": 0, "api_calls": 0}
        self._metrics[key]["cost_cents"] += amount_cents
        self._metrics[key]["tokens"] += tokens
        self._metrics[key]["api_calls"] += api_calls

        # Resolve agent_id from parameter or scope mapping
        resolved_agent_id = agent_id or self._scope_agent.get(key)

        # Check budget status after recording
        result = self.check_can_spend(scope_type, scope_id, 0, metric=metric)

        # Also check secondary metrics for breaches
        decisions: list[tuple[BudgetDecision, str]] = [
            (result.decision, metric)
        ]
        if tokens > 0:
            token_result = self.check_can_spend(
                scope_type, scope_id, 0, metric="tokens"
            )
            decisions.append((token_result.decision, "tokens"))
        if api_calls > 0:
            api_result = self.check_can_spend(
                scope_type, scope_id, 0, metric="api_calls"
            )
            decisions.append((api_result.decision, "api_calls"))

        # Find the worst decision
        worst_decision = result.decision
        breach_metric = metric
        for dec, met in decisions:
            if dec == BudgetDecision.DENIED:
                worst_decision = BudgetDecision.DENIED
                breach_metric = met
                break
            if dec == BudgetDecision.WARNING and worst_decision == BudgetDecision.ALLOWED:
                worst_decision = BudgetDecision.WARNING

        # Forget the dedupe key for any metric back under its limit, so a
        # later crossing reports a fresh incident.
        for dec, met in decisions:
            if dec != BudgetDecision.DENIED:
                self.incident_log.clear_dedupe_key(
                    BudgetIncident.build_dedupe_key(scope_type, scope_id, met)
                )

        # Handle hard-stop behavior
        if worst_decision == BudgetDecision.DENIED and self._hard_stop_enabled:
            self._handle_hard_stop(
                scope_type=scope_type,
                scope_id=scope_id,
                agent_id=resolved_agent_id,
                metric=breach_metric,
            )

        return worst_decision

    def _handle_hard_stop(
        self,
        scope_type: str,
        scope_id: uuid.UUID,
        agent_id: uuid.UUID | None,
        metric: str,
    ) -> None:
        """Handle a hard stop: create incident, pause agent, cancel work.

        Args:
            scope_type: Budget scope that was breached.
            scope_id: Scope identifier.
            agent_id: Agent to pause, if applicable.
            metric: The metric that triggered the breach.
        """
        key = (scope_type, scope_id)
        metric_key = (scope_type, scope_id, metric)

        # Determine threshold and actual amounts
        if metric == "cost_cents":
            threshold = self._budgets.get(
                key, self._metric_budgets.get(metric_key, 0)
            )
            actual = self._spent.get(key, 0)
        else:
            threshold = self._metric_budgets.get(metric_key, 0)
            metrics = self._metrics.get(key, {})
            actual = metrics.get(metric, 0)

        overage = max(0, actual - threshold)

        # Determine if agent will be paused
        was_paused = (
            agent_id is not None and self._auto_pause_callback is not None
        )

        # Create incident. The dedupe key means one hard-stop crossing for a
        # (scope, metric) yields one incident no matter how often it re-checks.
        incident = BudgetIncident(
            scope_type=scope_type,
            scope_id=scope_id,
            agent_id=agent_id,
            metric=metric,
            threshold_amount=threshold,
            actual_amount=actual,
            overage_amount=overage,
            was_agent_paused=was_paused,
            dedupe_key=BudgetIncident.build_dedupe_key(
                scope_type, scope_id, metric
            ),
        )
        if not self.incident_log.record(incident):
            # Already reported this crossing — don't re-fire the callbacks.
            return

        # Auto-pause callback
        if agent_id is not None and self._auto_pause_callback is not None:
            self._auto_pause_callback(agent_id, incident)

        # Cancel work callback
        if self._cancel_work_callback is not None:
            self._cancel_work_callback(scope_type, scope_id)

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

    def get_metrics(
        self, scope_type: str, scope_id: uuid.UUID
    ) -> dict[str, int]:
        """Get current metric totals for a scope.

        Args:
            scope_type: Budget scope.
            scope_id: Scope identifier.

        Returns:
            Dict with keys cost_cents, tokens, api_calls and their totals.
        """
        key = (scope_type, scope_id)
        return dict(
            self._metrics.get(key, {"cost_cents": 0, "tokens": 0, "api_calls": 0})
        )
