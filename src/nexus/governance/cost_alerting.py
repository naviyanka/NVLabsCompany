"""Cost Alerting Service - monitors budget usage and fires alerts on thresholds.

Integrates with BudgetEnforcer cost tracking to detect when spending
approaches or exceeds configured thresholds. Supports callback registration
for flexible alert delivery (email, webhook, in-app notification, etc.).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nexus.governance.budget_enforcer import BudgetEnforcer


class AlertSeverity(StrEnum):
    """Severity levels for cost alerts.

    Values:
        WARNING: Spending has crossed the warning threshold.
        CRITICAL: Spending has crossed the critical threshold.
    """

    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class AlertThreshold:
    """Configurable thresholds for budget alerting.

    Attributes:
        warn_pct: Percentage of budget at which to fire a warning alert.
        critical_pct: Percentage of budget at which to fire a critical alert.
    """

    warn_pct: float = 80.0
    critical_pct: float = 95.0

    def __post_init__(self) -> None:
        """Validate threshold values."""
        if not (0 < self.warn_pct < 100):
            raise ValueError("warn_pct must be between 0 and 100")
        if not (0 < self.critical_pct <= 100):
            raise ValueError("critical_pct must be between 0 and 100")
        if self.warn_pct >= self.critical_pct:
            raise ValueError("warn_pct must be less than critical_pct")


@dataclass
class CostAlert:
    """A cost alert fired when spending crosses a threshold.

    Attributes:
        id: Unique alert identifier.
        agent_id: Agent associated with the budget scope (if applicable).
        scope: Tuple of (scope_type, scope_id) identifying the budget.
        current_spend: Current spending in cents.
        limit: Budget limit in cents.
        severity: Alert severity level.
        timestamp: When the alert was generated.
        message: Human-readable alert description.
    """

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    agent_id: str | None = None
    scope: tuple[str, uuid.UUID] = field(
        default_factory=lambda: ("", uuid.UUID(int=0))
    )
    current_spend: int = 0
    limit: int = 0
    severity: AlertSeverity = AlertSeverity.WARNING
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )
    message: str = ""


# Type alias for alert callback functions
AlertCallback = Callable[[CostAlert], None]


class CostAlertService:
    """Service that monitors budgets and fires alerts on threshold crossings.

    Integrates with BudgetEnforcer to read current spending and budget limits.
    Callbacks are invoked synchronously when check_budgets() identifies scopes
    that have crossed their configured thresholds.

    Example:
        enforcer = BudgetEnforcer()
        service = CostAlertService(enforcer)
        service.set_threshold("agent", agent_id, AlertThreshold(80.0, 95.0))
        service.register_callback(my_alert_handler)
        alerts = service.check_budgets()
    """

    def __init__(self, budget_enforcer: BudgetEnforcer) -> None:
        """Initialize the cost alert service.

        Args:
            budget_enforcer: The BudgetEnforcer instance to monitor.
        """
        self._enforcer = budget_enforcer
        self._thresholds: dict[tuple[str, uuid.UUID], AlertThreshold] = {}
        self._callbacks: list[AlertCallback] = []
        self._fired_alerts: list[CostAlert] = []

    def set_threshold(
        self,
        scope_type: str,
        scope_id: uuid.UUID,
        threshold: AlertThreshold,
    ) -> None:
        """Configure alert thresholds for a budget scope.

        Args:
            scope_type: Budget scope (company, department, agent, project).
            scope_id: Identifier within the scope.
            threshold: AlertThreshold with warn and critical percentages.
        """
        self._thresholds[(scope_type, scope_id)] = threshold

    def register_callback(self, callback: AlertCallback) -> None:
        """Register a callback function for alert delivery.

        Callbacks receive a CostAlert object when a threshold is crossed.

        Args:
            callback: Function to invoke with the alert.
        """
        self._callbacks.append(callback)

    def check_budgets(self) -> list[CostAlert]:
        """Check all monitored budgets and fire alerts for threshold crossings.

        Iterates over all configured thresholds, compares current spending
        against the budget limit, and fires alerts for any that have crossed
        warning or critical thresholds.

        Returns:
            List of CostAlert objects generated during this check.
        """
        alerts: list[CostAlert] = []

        for (scope_type, scope_id), threshold in self._thresholds.items():
            key = (scope_type, scope_id)

            # Read budget and spending from the enforcer
            budget_total = self._enforcer._budgets.get(key)
            if budget_total is None or budget_total <= 0:
                continue

            spent = self._enforcer._spent.get(key, 0)
            spent_pct = (spent / budget_total) * 100

            # Determine severity based on threshold crossings
            severity: AlertSeverity | None = None
            if spent_pct >= threshold.critical_pct:
                severity = AlertSeverity.CRITICAL
            elif spent_pct >= threshold.warn_pct:
                severity = AlertSeverity.WARNING

            if severity is None:
                continue

            # Resolve agent_id if mapped
            agent_id_uuid = self._enforcer._scope_agent.get(key)
            agent_id_str = (
                str(agent_id_uuid) if agent_id_uuid else None
            )

            alert = CostAlert(
                agent_id=agent_id_str,
                scope=(scope_type, scope_id),
                current_spend=spent,
                limit=budget_total,
                severity=severity,
                message=(
                    f"{severity.value.upper()}: {scope_type}/{scope_id} "
                    f"at {spent_pct:.1f}% of budget "
                    f"({spent} / {budget_total} cents)"
                ),
            )

            alerts.append(alert)
            self._fired_alerts.append(alert)

            # Invoke callbacks
            for callback in self._callbacks:
                callback(alert)

        return alerts

    def get_fired_alerts(self) -> list[CostAlert]:
        """Return all alerts that have been fired.

        Returns:
            List of all CostAlert objects generated by this service.
        """
        return list(self._fired_alerts)
