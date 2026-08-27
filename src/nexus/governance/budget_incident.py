"""Budget Incident tracking - records budget breaches and overage events."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class BudgetIncident:
    """A recorded budget incident when a hard stop is triggered.

    Attributes:
        id: Unique incident identifier.
        scope_type: Budget scope (company, department, agent, project).
        scope_id: Identifier within the scope.
        agent_id: Agent that triggered the incident, if applicable.
        metric: The metric that was breached (cost_cents, tokens, api_calls).
        threshold_amount: The budget threshold that was exceeded.
        actual_amount: The actual spending amount at breach time.
        overage_amount: How much the spending exceeds the threshold.
        was_agent_paused: Whether the agent was auto-paused.
        created_at: When the incident was created.
        dedupe_key: Optional idempotency key. When set, the log records only
            the first incident per key, so one threshold crossing that is
            re-checked repeatedly yields a single incident.
    """

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    scope_type: str = ""
    scope_id: uuid.UUID = field(default_factory=uuid.uuid4)
    agent_id: uuid.UUID | None = None
    metric: str = "cost_cents"
    threshold_amount: int = 0
    actual_amount: int = 0
    overage_amount: int = 0
    was_agent_paused: bool = False
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    dedupe_key: str | None = None

    @staticmethod
    def build_dedupe_key(
        scope_type: str, scope_id: uuid.UUID, threshold_type: str
    ) -> str:
        """Build the dedupe key for a (scope, threshold_type) crossing."""
        return f"{scope_type}:{scope_id}:{threshold_type}"


class BudgetIncidentLog:
    """In-memory store for budget incidents.

    Provides methods to record and retrieve budget breach incidents.
    """

    def __init__(self) -> None:
        """Initialize an empty incident log."""
        self._incidents: list[BudgetIncident] = []
        self._seen_keys: set[str] = set()

    def record(self, incident: BudgetIncident) -> bool:
        """Record a budget incident, deduplicating on `dedupe_key`.

        Args:
            incident: The BudgetIncident to store.

        Returns:
            True if the incident was stored, False if an incident with the
            same `dedupe_key` was already recorded.
        """
        if incident.dedupe_key is not None:
            if incident.dedupe_key in self._seen_keys:
                return False
            self._seen_keys.add(incident.dedupe_key)
        self._incidents.append(incident)
        return True

    def clear_dedupe_key(self, dedupe_key: str) -> None:
        """Forget a dedupe key so the same crossing can fire a new incident.

        Called when spending drops back below the threshold.
        """
        self._seen_keys.discard(dedupe_key)

    def get_all(self) -> list[BudgetIncident]:
        """Retrieve all incidents, most recent first.

        Returns:
            List of BudgetIncident objects in reverse chronological order.
        """
        return list(reversed(self._incidents))

    def get_by_scope(
        self, scope_type: str, scope_id: uuid.UUID
    ) -> list[BudgetIncident]:
        """Retrieve incidents filtered by scope.

        Args:
            scope_type: Budget scope type to filter by.
            scope_id: Scope identifier to filter by.

        Returns:
            List of matching BudgetIncident objects, most recent first.
        """
        results = [
            i for i in reversed(self._incidents)
            if i.scope_type == scope_type and i.scope_id == scope_id
        ]
        return results

    def get_by_agent(self, agent_id: uuid.UUID) -> list[BudgetIncident]:
        """Retrieve incidents filtered by agent.

        Args:
            agent_id: Agent identifier to filter by.

        Returns:
            List of matching BudgetIncident objects, most recent first.
        """
        results = [
            i for i in reversed(self._incidents)
            if i.agent_id == agent_id
        ]
        return results
